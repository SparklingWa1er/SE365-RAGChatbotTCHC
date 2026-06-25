"""exp02 — Bước ①: SINH OUTPUT của pipeline trên subset GT (nền cho mọi metric generation/citation).

Với mỗi câu hỏi GT, chạy TOÀN BỘ pipeline reasoning (mặc định ReAct hai pha — đúng
đường production) rồi LƯU lại:
  - answer    : câu trả lời cuối có inline citation 【n】 (answer.text)
  - contexts  : các đoạn evidence pipeline đã gom & assemble (corpus + web)
  - citations : map 【n】 -> đoạn nguồn (dựng từ build_citations của engine API)
  - metadata  : q_type, gold_ma_thu_tuc (chép từ GT) để phân nhóm + chấm sau

Đây là phần TỐN NHẤT (ReAct ~8-20 call gpt-4o/câu) nên tách riêng + CACHE RESUMABLE:
chạy lại sẽ bỏ qua id đã có trong file out. Chấm điểm (eval_generation/eval_citation)
chạy trên file này, KHÔNG chạy lại pipeline.

Tái dùng nguyên cỗ máy headless của tầng API (app/api/engine.py) — KHÔNG reimplement
reasoning. Lấy mẫu PHÂN TẦNG đều theo q_type (xem GENERATION_EVAL_METHODOLOGY.md §4.1).

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\gen_outputs.py --per-type 1            # thử 6 câu (1/nhóm)
  .venv\\Scripts\\python.exe rag\\eval\\gen_outputs.py --per-type 8            # ~50 câu phân tầng
  .venv\\Scripts\\python.exe rag\\eval\\gen_outputs.py --engine simple --per-type 8   # so sánh engine
  .venv\\Scripts\\python.exe rag\\eval\\gen_outputs.py --include-oos           # thêm câu ngoài phạm vi
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))          # gốc repo -> package `app`, `rag`
sys.path.insert(0, str(ROOT / "rag"))  # rag/ -> theflow tìm flowsettings.py

EXP01 = ROOT / "data" / "eval" / "exp01_retrieval"
EXP02 = ROOT / "data" / "eval" / "exp02_generation"
GT_AUTO = EXP01 / "retrieval_gt.jsonl"
GT_MANUAL = EXP01 / "retrieval_gt_manual.jsonl"

# Thứ tự nhóm để lấy mẫu phân tầng (6 nhóm tự sinh; manual_inscope/out_of_scope tách riêng).
AUTO_TYPES = ["factual_lookup", "paraphrase", "scenario",
              "aspect_hoso", "aspect_phi_dk", "keyword_short"]


def load_gt(include_oos: bool) -> list[dict]:
    """Nạp GT auto + manual. Trả list dict đã chuẩn hoá các khoá cần dùng."""
    rows: list[dict] = []
    for line in open(GT_AUTO, encoding="utf-8"):
        rows.append(json.loads(line))
    for line in open(GT_MANUAL, encoding="utf-8"):
        r = json.loads(line)
        if r["q_type"] == "out_of_scope" and not include_oos:
            continue
        rows.append(r)
    return rows


def stratified(rows: list[dict], per_type: int) -> list[dict]:
    """Lấy đều `per_type` câu mỗi q_type, theo thứ tự id (tái lập được). 0 = lấy hết."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["q_type"]].append(r)
    out: list[dict] = []
    # giữ thứ tự nhóm ổn định: auto trước, rồi manual_inscope, out_of_scope
    order = AUTO_TYPES + [t for t in by_type if t not in AUTO_TYPES]
    for t in order:
        items = sorted(by_type.get(t, []), key=lambda x: x["id"])
        out.extend(items if per_type <= 0 else items[:per_type])
    return out


def drive_stream(pipeline, question: str, conv_id: str):
    """Chạy hết generator pipeline.stream, gom text channel 'chat' và bắt return value.

    pipeline.stream là generator đồng bộ: yield Document(channel=...) và `return answer`
    ở cuối (xem react.py / simple.py). Ta cần CẢ answer (cho citation) lẫn text hiển thị.
    """
    chat_text = ""
    answer = None
    gen = pipeline.stream(question, conv_id, [])
    try:
        while True:
            doc = next(gen)
            ch = getattr(doc, "channel", None)
            if ch == "chat":
                if doc.content is None:
                    chat_text = ""          # reset (think-tag / web-mark render lại)
                else:
                    chat_text += doc.content
    except StopIteration as stop:
        answer = stop.value
    return answer, chat_text


def serialize_contexts(docs: list) -> list[dict]:
    """Đoạn evidence đã gom (full text — cần cho entailment). Giữ metadata citable."""
    out = []
    for d in docs or []:
        m = getattr(d, "metadata", None) or {}
        out.append({
            "doc_id": getattr(d, "doc_id", None),
            "file_name": m.get("file_name", "-"),
            "is_web": bool(m.get("is_web")),
            "web_url": m.get("web_url"),
            "score": m.get("llm_trulens_score"),
            "text": getattr(d, "text", "") or "",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="ReAct", help="reasoning engine (ReAct | simple | ...)")
    ap.add_argument("--per-type", type=int, default=8, help="số câu mỗi q_type (0 = hết)")
    ap.add_argument("--include-oos", action="store_true", help="gồm cả câu out_of_scope")
    ap.add_argument("--limit", type=int, default=0, help="trần tổng số câu (debug)")
    ap.add_argument("--reset", action="store_true", help="xoá file out trước khi sinh")
    args = ap.parse_args()

    EXP02.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.engine == "ReAct" else f"_{args.engine}"
    out_path = EXP02 / f"gen_outputs{suffix}.jsonl"
    if args.reset and out_path.exists():
        out_path.unlink()

    # Cache resumable: bỏ qua id đã sinh.
    done: set[str] = set()
    if out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:  # noqa: BLE001
                pass
        print(f"Đã có {len(done)} câu trong {out_path.name} — sẽ bỏ qua các id trùng.")

    rows = stratified(load_gt(args.include_oos), args.per_type)
    rows = [r for r in rows if r["id"] not in done]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("Không còn câu nào để sinh (đã xong hết).")
        return 0
    print(f"Engine={args.engine} · sẽ sinh {len(rows)} câu · out={out_path}")

    # --- Bootstrap headless: tái dùng cỗ máy của tầng API (KHÔNG dựng lại reasoning) ---
    print("Khởi tạo kotaemon (headless)...")
    from app.api import engine as eng  # noqa: E402  (bootstrap sys.path đã xong ở trên)

    # Cấu hình eval CỐ ĐỊNH: ép engine + TẮT mindmap (tiết kiệm 1 call/câu, không ảnh
    # hưởng metric) — xem GENERATION_EVAL_METHODOLOGY.md §4.2.
    overrides = {"reasoning_type": args.engine, "use_mindmap": False}
    settings = eng.build_settings(overrides)

    out_f = open(out_path, "a", encoding="utf-8")
    n_ok = n_err = 0
    t0 = time.perf_counter()
    for i, item in enumerate(rows, 1):
        q = item["question"]
        conv_id = f"eval-{item['id']}"
        # Pipeline MỚI mỗi câu (get_pipeline reset collected_docs → cô lập state request).
        try:
            pipeline, _ = eng.create_pipeline(settings, selected_file_ids=None)
            answer, chat_text = drive_stream(pipeline, q, conv_id)
            answer_text = (getattr(answer, "text", None) or chat_text or "").strip()
            contexts = serialize_contexts(
                pipeline._dedup_collected() if hasattr(pipeline, "_dedup_collected")
                else getattr(pipeline, "_last_docs", []) or []
            )
            try:
                citations = eng.build_citations(pipeline, answer) or []
            except Exception:  # noqa: BLE001
                citations = []
            # Bỏ content_html (toàn văn + tag HTML cho panel UI) — trùng với contexts.text
            # và không cần cho chấm. Giữ snippet (spans khớp) + indices/title/cờ web.
            for c in citations:
                c.pop("content_html", None)
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"  [LỖI] {item['id']}: {e}")
            n_err += 1
            continue

        rec = {
            "id": item["id"],
            "q_type": item["q_type"],
            "question": q,
            "gold_ma_thu_tuc": item.get("gold_ma_thu_tuc", []),
            "primary_ma_thu_tuc": item.get("primary_ma_thu_tuc"),
            "ten": item.get("ten"),
            "linh_vuc": item.get("linh_vuc"),
            "engine": args.engine,
            "answer": answer_text,
            "n_contexts": len(contexts),
            "n_citations": len(citations),
            "contexts": contexts,
            "citations": citations,
        }
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        dt = time.perf_counter() - t0
        print(f"  [{i}/{len(rows)}] {item['q_type']:14s} "
              f"ctx={len(contexts)} cite={len(citations)} "
              f"ans={len(answer_text)}c  ({dt/i:.1f}s/câu)  {q[:50]}")

    out_f.close()
    print(f"\nXong. OK={n_ok} lỗi={n_err}. File: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
