"""fast_ingest.py — Parallel embedding ingest dùng ThreadPoolExecutor.

Bypass theflow/kotaemon pipeline để tận dụng parallel Azure API calls.
Tốc độ mục tiêu: ~15 phút thay vì ~2.5 giờ (10 workers x Azure latency ~1.5s/file).

Input: data/corpus/chunks.jsonl (section-based chunks từ parse.py)
Output: C:\\ktem_data\\user_data\\ (Chroma vectorstore + LanceDB docstore + sql.db)

Dùng:
    python fast_ingest.py                  # ingest toàn bộ
    python fast_ingest.py --limit 5        # test 5 file
    python fast_ingest.py --workers 20     # tăng số worker
    python fast_ingest.py --reindex        # bỏ qua skip, ingest lại từ đầu

Chú ý:
    - KHÔNG dùng theflow cache → KHÔNG bị treo khi force-kill
    - Nếu bị ngắt, chạy lại sẽ tự bỏ qua file đã ingest (--reindex để nạp lại)
    - Chạy bằng: kotaemon-app\\.venv\\Scripts\\python.exe fast_ingest.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import chromadb
import lancedb
import openai
import pyarrow as pa


# ─── Paths ───────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
# Hoạt động khi chạy từ kotaemon-app/ (ở đó script được copy vào) hoặc kotaemon-setup/
_REPO_ROOT = _HERE.parent
CORPUS_DIR = _REPO_ROOT / "data" / "corpus"

LANCE_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("attributes", pa.string()),
])


# ─── .env loader ─────────────────────────────────────────────────────────────

def load_env() -> None:
    candidates = [
        _REPO_ROOT / ".env",   # .env ở gốc repo (vị trí chuẩn sau refactor)
        _HERE / ".env",
    ]
    for env_path in candidates:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
            return
    raise SystemExit("Không tìm thấy .env — copy từ .env.example và điền Azure key")


def get_data_dir() -> Path:
    return Path(os.environ.get("KH_APP_DATA_DIR", r"C:\ktem_data"))


# ─── Azure embedding ──────────────────────────────────────────────────────────

def make_azure_client() -> openai.AzureOpenAI:
    return openai.AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    )


def embed_batch(
    client: openai.AzureOpenAI,
    texts: list[str],
    deployment: str,
    retries: int = 4,
) -> list[list[float]]:
    for attempt in range(retries):
        try:
            resp = client.embeddings.create(input=texts, model=deployment)
            return [r.embedding for r in resp.data]
        except openai.RateLimitError:
            wait = 15 * (attempt + 1)
            print(f"    ⏳ Rate limit (attempt {attempt+1}), chờ {wait}s...")
            time.sleep(wait)
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError("embed_batch: hết số lần thử")


# ─── Per-file processing (chạy trong thread) ─────────────────────────────────

def process_file(
    doc_id: str,
    md_path: Path,
    chunks: list[dict],
    client: openai.AzureOpenAI,
    deployment: str,
    batch_size: int,
) -> dict:
    """Embed tất cả chunks của một file. Trả về result dict (chưa ghi store)."""
    file_bytes = md_path.read_bytes()
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    stat = md_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime)

    texts = [c["text"] for c in chunks]
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch_embeddings = embed_batch(client, texts[i : i + batch_size], deployment)
        all_embeddings.extend(batch_embeddings)

    source_id = str(uuid.uuid4())
    return {
        "source_id": source_id,
        "file_name": md_path.name,
        "file_path": str(md_path),
        "file_size": stat.st_size,
        "sha256": sha256,
        "now_str": datetime.now().isoformat(),
        "date_str": mtime.strftime("%Y-%m-%d"),
        "chunks": [
            {
                "chunk_id": str(uuid.uuid4()),
                "text": c["text"],
                "embedding": emb,
            }
            for c, emb in zip(chunks, all_embeddings)
        ],
    }


# ─── Store writes (sequential, main thread) ──────────────────────────────────

def write_result(
    result: dict,
    conn: sqlite3.Connection,
    lance_table,
    chroma_col,
    files_dir: Path,
) -> None:
    src = result["source_id"]
    fp = result["file_path"]
    fn = result["file_name"]
    fs = result["file_size"]
    sha = result["sha256"]
    now_str = result["now_str"]
    date_str = result["date_str"]

    # Bản sao file .md trong files/index_1/
    dest = files_dir / sha
    if not dest.exists():
        shutil.copy2(fp, dest)

    # sql.db: source record
    conn.execute(
        "INSERT OR IGNORE INTO [index__1__source]"
        " (id, name, path, size, date_created, user, note)"
        " VALUES (?,?,?,?,?,?,?)",
        (src, fn, sha, fs, now_str, "default",
         json.dumps({"loader": "fast_ingest"}, ensure_ascii=False)),
    )

    lance_rows: list[dict] = []
    chroma_ids: list[str] = []
    chroma_embeddings: list[list[float]] = []
    chroma_metas: list[dict] = []

    for chunk in result["chunks"]:
        cid = chunk["chunk_id"]
        text = chunk["text"]
        emb = chunk["embedding"]

        # sql.db: 2 rows per chunk (document + vector)
        conn.execute(
            "INSERT OR IGNORE INTO [index__1__index]"
            " (source_id, target_id, relation_type, user)"
            " VALUES (?,?,?,?)",
            (src, cid, "document", ""),
        )
        conn.execute(
            "INSERT OR IGNORE INTO [index__1__index]"
            " (source_id, target_id, relation_type, user)"
            " VALUES (?,?,?,?)",
            (src, cid, "vector", ""),
        )

        # LanceDB: {id, text, attributes}
        attrs = json.dumps(
            {
                "file_path": fp,
                "file_name": fn,
                "file_size": fs,
                "creation_date": date_str,
                "last_modified_date": date_str,
                "file_id": src,
                "collection_name": "default",
            },
            ensure_ascii=False,
        )
        lance_rows.append({"id": cid, "text": text, "attributes": attrs})

        # Chroma: metadata + _node_content (kotaemon TextNode format)
        node_content = json.dumps(
            {
                "id_": cid,
                "embedding": None,
                "metadata": {
                    "file_path": fp,
                    "file_name": fn,
                    "file_size": fs,
                    "creation_date": date_str,
                    "last_modified_date": date_str,
                    "file_id": src,
                    "collection_name": "default",
                },
                "excluded_embed_metadata_keys": [],
                "excluded_llm_metadata_keys": [],
                "relationships": {
                    "1": {
                        "node_id": cid,
                        "node_type": None,
                        "metadata": {},
                        "hash": None,
                        "class_name": "RelatedNodeInfo",
                    }
                },
                "text": "",
                "mimetype": "text/plain",
                "start_char_idx": 0,
                "end_char_idx": len(text),
                "text_template": "{metadata_str}\n\n{content}",
                "metadata_template": "{key}: {value}",
                "metadata_seperator": "\n",
                "content": text,
                "class_name": "TextNode",
            },
            ensure_ascii=False,
        )
        chroma_ids.append(cid)
        chroma_embeddings.append(emb)
        chroma_metas.append(
            {
                "_node_type": "Document",
                "_node_content": node_content,
                "collection_name": "default",
                "creation_date": date_str,
                "last_modified_date": date_str,
                "doc_id": cid,
                "document_id": cid,
                "ref_doc_id": cid,
                "file_id": src,
                "file_name": fn,
                "file_path": fp,
                "file_size": fs,
            }
        )

    lance_table.add(lance_rows)
    # documents= bắt buộc: llama_index gọi node.set_content(text) với giá trị này
    # khi reconstruct TextNode từ Chroma — nếu thiếu sẽ nhận None → ValidationError
    chroma_col.upsert(
        ids=chroma_ids,
        embeddings=chroma_embeddings,
        metadatas=chroma_metas,
        documents=[chunk["text"] for chunk in result["chunks"]],
    )
    conn.commit()


# ─── Integrity check ─────────────────────────────────────────────────────────

def verify_integrity(
    user_data: Path,
    conn: sqlite3.Connection,
    lance_table,
    chroma_col,
    expected_sources: int,
) -> tuple[bool, list[str]]:
    """Kiểm tra tính nhất quán giữa sql.db, Chroma, LanceDB và HNSW .bin files.

    Trả về (ok, messages). Không raise — chỉ report.
    """
    msgs: list[str] = []
    ok = True

    n_src = conn.execute("SELECT COUNT(*) FROM [index__1__source]").fetchone()[0]
    rels = dict(
        conn.execute(
            "SELECT relation_type, COUNT(*) FROM [index__1__index] GROUP BY relation_type"
        ).fetchall()
    )
    n_doc = rels.get("document", 0)
    n_vec = rels.get("vector", 0)
    n_chroma = chroma_col.count()
    n_lance = lance_table.count_rows()

    msgs.append(
        f"sql.db: {n_src} source / {n_doc} doc / {n_vec} vec | "
        f"Chroma: {n_chroma} | LanceDB: {n_lance}"
    )

    if n_src != expected_sources:
        ok = False
        msgs.append(f"  ⚠️  source count {n_src} != expected {expected_sources}")
    if n_doc != n_vec:
        ok = False
        msgs.append(f"  ⚠️  document ({n_doc}) != vector ({n_vec}) trong sql.db")
    if n_chroma != n_lance:
        ok = False
        msgs.append(f"  ⚠️  Chroma ({n_chroma}) != LanceDB ({n_lance})")
    if n_chroma != n_doc:
        ok = False
        msgs.append(f"  ⚠️  Chroma ({n_chroma}) != sql.db document ({n_doc})")

    # HNSW .bin check (LỖI #2 — Unicode path bug)
    vs_dir = user_data / "vectorstore"
    seg_dirs = [d for d in vs_dir.iterdir() if d.is_dir()]
    if not seg_dirs:
        ok = False
        msgs.append(f"  ❌ Không tìm thấy thư mục segment trong {vs_dir}")
    for seg in seg_dirs:
        required = {"data_level0.bin", "header.bin", "length.bin"}
        present = {f.name: f.stat().st_size for f in seg.iterdir() if f.is_file()}
        missing = required - set(present.keys())
        if missing:
            ok = False
            msgs.append(f"  ❌ Segment {seg.name} thiếu file: {missing} (LỖI #2?)")
        for fname in required:
            sz = present.get(fname, 0)
            if sz == 0:
                ok = False
                msgs.append(f"  ❌ Segment {seg.name}/{fname} size=0 (LỖI #2?)")
        msgs.append(
            f"  HNSW {seg.name[:8]}…: "
            + " ".join(f"{n}={present.get(n, 0):,}" for n in sorted(required))
        )

    return ok, msgs


def print_check(label: str, ok: bool, msgs: list[str]) -> None:
    mark = "✅" if ok else "⚠️"
    print(f"\n{mark} CHECKPOINT [{label}]")
    for m in msgs:
        print(f"  {m}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parallel ingest corpus → Chroma + LanceDB + sql.db"
    )
    ap.add_argument("--limit", type=int, default=None, metavar="N",
                    help="Giới hạn số file để test (ví dụ: --limit 5)")
    ap.add_argument("--workers", type=int, default=10,
                    help="Số worker song song (mặc định: 10)")
    ap.add_argument("--batch-size", type=int, default=16, dest="batch_size",
                    help="Số chunk gộp mỗi lần gọi Azure API (mặc định: 16)")
    ap.add_argument("--reindex", action="store_true",
                    help="Bỏ qua kiểm tra đã ingest, embed lại từ đầu")
    ap.add_argument("--corpus", type=Path, default=None, metavar="DIR",
                    help=f"Thư mục corpus (mặc định: {CORPUS_DIR})")
    ap.add_argument("--checkpoint-every", type=int, default=1000, dest="checkpoint_every",
                    metavar="N", help="Verify integrity sau mỗi N file (mặc định: 1000, 0=tắt)")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="Dừng ngay nếu integrity check fail (mặc định: chỉ warn)")
    args = ap.parse_args()

    corpus_dir: Path = args.corpus or CORPUS_DIR
    chunks_jsonl = corpus_dir / "chunks.jsonl"
    md_dir = corpus_dir / "md"

    load_env()
    data_dir = get_data_dir()
    user_data = data_dir / "user_data"
    files_dir = user_data / "files" / "index_1"
    files_dir.mkdir(parents=True, exist_ok=True)

    # Load chunks.jsonl → group by doc_id
    print(f"Đọc {chunks_jsonl} ...")
    chunks_by_doc: dict[str, list[dict]] = {}
    total_chunks = 0
    with open(chunks_jsonl, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            chunks_by_doc.setdefault(c["doc_id"], []).append(c)
            total_chunks += 1
    print(f"  {len(chunks_by_doc)} tài liệu, {total_chunks} chunks")

    # Build doc_uuid → md_path map  (filename: "{ma}__{uuid}.md")
    md_map: dict[str, Path] = {}
    for md in md_dir.glob("*.md"):
        parts = md.stem.split("__", 1)
        if len(parts) == 2:
            md_map[parts[1]] = md
    print(f"  {len(md_map)} file .md tìm thấy")

    # Kiểm tra file đã ingest (theo tên file trong sql.db)
    db_path = user_data / "sql.db"
    conn = sqlite3.connect(str(db_path))
    if args.reindex:
        done_names: set[str] = set()
        baseline_sources = 0
    else:
        done_names = {
            r[0] for r in conn.execute("SELECT name FROM [index__1__source]").fetchall()
        }
        baseline_sources = len(done_names)

    # Tạo work list: (doc_id, md_path, chunks_list)
    work: list[tuple[str, Path, list[dict]]] = []
    for doc_id, chunks in chunks_by_doc.items():
        md_path = md_map.get(doc_id)
        if md_path is None:
            continue
        if md_path.name in done_names:
            continue
        work.append((doc_id, md_path, chunks))

    if args.limit:
        work = work[: args.limit]

    total = len(work)
    print(
        f"\nSẽ ingest: {total} file "
        f"(bỏ qua {baseline_sources} đã có, {args.workers} workers, "
        f"checkpoint mỗi {args.checkpoint_every} file)\n"
    )
    if not total:
        print("Không có file nào cần ingest.")
        conn.close()
        return

    # Mở stores
    lance_db_conn = lancedb.connect(str(user_data / "docstore"))
    try:
        lance_table = lance_db_conn.open_table("index_1")
    except Exception:
        lance_table = lance_db_conn.create_table("index_1", schema=LANCE_SCHEMA)

    chroma_client = chromadb.PersistentClient(path=str(user_data / "vectorstore"))
    chroma_col = chroma_client.get_or_create_collection("index_1")

    # openai client là thread-safe
    client = make_azure_client()
    deployment = os.environ["AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"]

    # Baseline integrity check (trước khi ingest)
    if args.checkpoint_every > 0:
        ok, msgs = verify_integrity(user_data, conn, lance_table, chroma_col, baseline_sources)
        print_check("baseline", ok, msgs)
        if not ok and args.stop_on_fail:
            print("\n❌ Baseline integrity fail. Dừng.")
            conn.close()
            return

    # Chia work thành các batch theo checkpoint_every
    chk = args.checkpoint_every if args.checkpoint_every > 0 else total
    batches: list[list[tuple[str, Path, list[dict]]]] = [
        work[i : i + chk] for i in range(0, total, chk)
    ]
    print(f"Chia thành {len(batches)} batch (≈{chk} file/batch)\n")

    all_embed_errors: list[tuple[str, str]] = []
    all_write_errors: list[tuple[str, str]] = []
    t_global = time.time()
    cumulative_done = 0

    for bi, batch in enumerate(batches, start=1):
        bn = len(batch)
        print(f"{'='*60}")
        print(f"BATCH {bi}/{len(batches)} — {bn} file")
        print(f"{'='*60}")

        # ── Phase 1: Parallel embed ───────────────────────────────────────────
        print(f"Phase 1: Embedding (workers={args.workers}, batch-size={args.batch_size})...")
        results: list[dict | None] = [None] * bn
        done_in_batch = 0
        t_batch = time.time()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_file, doc_id, md_path, chunks,
                    client, deployment, args.batch_size,
                ): i
                for i, (doc_id, md_path, chunks) in enumerate(batch)
            }
            for future in as_completed(futures):
                idx = futures[future]
                done_in_batch += 1
                try:
                    result = future.result()
                    results[idx] = result
                    elapsed = time.time() - t_batch
                    rate = done_in_batch / elapsed if elapsed > 0 else 0
                    remaining = total - cumulative_done - done_in_batch
                    eta = remaining / rate if rate > 0 else 0
                    print(
                        f"  ✅ [{bi}] {done_in_batch}/{bn} "
                        f"({cumulative_done + done_in_batch}/{total}) | "
                        f"{result['file_name']} | "
                        f"{rate:.1f} file/s | ETA toàn cục {eta:.0f}s"
                    )
                except Exception as exc:
                    fname = batch[idx][1].name
                    all_embed_errors.append((fname, str(exc)))
                    print(f"  ❌ [{bi}] {done_in_batch}/{bn} | {fname}: {exc}")

        # ── Phase 2: Sequential write ─────────────────────────────────────────
        good = [r for r in results if r is not None]
        print(f"\nPhase 2: Ghi {len(good)} file vào stores...")
        batch_written = 0
        for i, result in enumerate(good):
            try:
                write_result(result, conn, lance_table, chroma_col, files_dir)
                batch_written += 1
                if (i + 1) % 100 == 0 or i + 1 == len(good):
                    print(f"  đã ghi {i+1}/{len(good)}")
            except Exception as exc:
                all_write_errors.append((result["file_name"], str(exc)))
                print(f"  ❌ {result['file_name']}: {exc}")

        cumulative_done += bn
        expected_sources = baseline_sources + cumulative_done - len(all_embed_errors) - len(all_write_errors)

        # ── Checkpoint integrity ──────────────────────────────────────────────
        if args.checkpoint_every > 0:
            ok, msgs = verify_integrity(
                user_data, conn, lance_table, chroma_col, expected_sources
            )
            label = f"batch {bi}/{len(batches)} — sau {cumulative_done}/{total} file"
            print_check(label, ok, msgs)
            if not ok and args.stop_on_fail:
                print("\n❌ Integrity fail. Dừng (--stop-on-fail).")
                conn.close()
                return

        elapsed_total = time.time() - t_global
        print(
            f"\n→ Hoàn tất batch {bi}: {batch_written}/{bn} ghi OK | "
            f"tổng {cumulative_done}/{total} | "
            f"đã chạy {elapsed_total:.0f}s ({elapsed_total/60:.1f} phút)\n"
        )

    conn.close()

    # ── Tạo FTS index cho LanceDB (kotaemon dùng query_type="fts" khi tìm kiếm) ──
    print("\nTạo FTS index trên LanceDB...")
    lance_table.create_fts_index("text", tokenizer_name="en_stem", replace=True)
    print("  ✅ FTS index OK")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed_total = time.time() - t_global
    n_ok = total - len(all_embed_errors) - len(all_write_errors)
    print(f"\n{'='*60}")
    print(
        f"XONG: {n_ok}/{total} thành công | "
        f"{elapsed_total:.0f}s ({elapsed_total/60:.1f} phút) | "
        f"{n_ok/elapsed_total:.1f} file/s trung bình"
        if elapsed_total > 0 else
        f"XONG: {n_ok}/{total} thành công"
    )
    print(f"{'='*60}")
    if all_embed_errors:
        print(f"\nLỗi embedding ({len(all_embed_errors)}):")
        for name, msg in all_embed_errors[:10]:
            print(f"  {name}: {msg}")
        if len(all_embed_errors) > 10:
            print(f"  ... và {len(all_embed_errors) - 10} lỗi khác")
    if all_write_errors:
        print(f"\nLỗi ghi store ({len(all_write_errors)}):")
        for name, msg in all_write_errors[:10]:
            print(f"  {name}: {msg}")
        if len(all_write_errors) > 10:
            print(f"  ... và {len(all_write_errors) - 10} lỗi khác")


if __name__ == "__main__":
    main()
