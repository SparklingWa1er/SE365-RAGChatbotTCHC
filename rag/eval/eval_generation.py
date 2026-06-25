"""exp02 — Bước ②: chấm tầng GENERATION (RAG Triad reference-free) trên gen_outputs.jsonl.

Ba metric, gpt-4o làm judge (xem GENERATION_EVAL_METHODOLOGY.md §2.1):
  - faithfulness     : tách answer thành claim nguyên tử → tỉ lệ claim được context hỗ trợ
                       (RAGAS / FactScore). Bắt hallucination.
  - answer_relevance : LLM sinh ngược N câu hỏi từ answer → cosine với câu hỏi gốc
                       (RAGAS). Bắt trả lời lạc đề / lan man. Answer "né" (abstention) → 0.
  - context_precision: tỉ lệ đoạn context thực sự liên quan câu hỏi (RAGAS / TruLens
                       context-relevance — CÙNG họ với gate llm_trulens_score của hệ).

KHÔNG chạy lại pipeline — chỉ đọc gen_outputs.jsonl (bước ①). Cache resumable theo id.

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\eval_generation.py                 # engine ReAct
  .venv\\Scripts\\python.exe rag\\eval\\eval_generation.py --engine simple
  .venv\\Scripts\\python.exe rag\\eval\\eval_generation.py --limit 5       # thử nhanh
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))

import flowsettings  # noqa: E402

EXP02 = ROOT / "data" / "eval" / "exp02_generation"
N_GEN_Q = 3          # số câu hỏi sinh ngược cho answer_relevance
CTX_TRIM_FAITH = 1500  # cắt mỗi context khi chấm faithfulness (token)
CTX_TRIM_PREC = 700    # cắt mỗi context khi chấm context_precision


# ── LLM judge + embedding (dựng trực tiếp như gen_gt.py) ──────────────────────
def build_judge():
    from kotaemon.llms import AzureChatOpenAI
    spec = flowsettings.KH_LLMS["azure"]["spec"].copy()
    spec.pop("__type__")
    return AzureChatOpenAI(**spec)


def build_embedder():
    from kotaemon.embeddings import AzureOpenAIEmbeddings
    spec = flowsettings.KH_EMBEDDINGS["azure"]["spec"].copy()
    spec.pop("__type__")
    return AzureOpenAIEmbeddings(**spec)


def _json_call(llm, prompt: str) -> dict | list | None:
    """Gọi LLM, bóc JSON (chịu được rào ```json). None nếu parse thất bại."""
    raw = llm(prompt).text or ""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"[\{\[].*[\}\]]", raw, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _embed_text(embedder, text: str) -> list[float]:
    out = embedder(text)
    # AzureOpenAIEmbeddings trả list[DocumentWithEmbedding]; lấy .embedding của phần tử đầu
    doc = out[0] if isinstance(out, list) else out
    return getattr(doc, "embedding", None) or doc.metadata.get("embedding")


# ── Các metric ────────────────────────────────────────────────────────────────
def _contexts_block(contexts, trim) -> str:
    parts = []
    for i, c in enumerate(contexts, 1):
        tag = "🌐 web" if c.get("is_web") else "corpus"
        parts.append(f"[Nguồn {i} · {tag}] {c.get('file_name','-')}\n{(c.get('text') or '')[:trim]}")
    return "\n\n".join(parts)


def faithfulness(llm, question, answer, contexts) -> dict:
    """RAGAS: tách claim → kiểm từng claim được context hỗ trợ. Trả {score, n_claims, n_supported}."""
    ex = _json_call(llm, (
        "Tách câu trả lời sau thành danh sách các MỆNH ĐỀ nguyên tử (mỗi mệnh đề là một "
        "khẳng định độc lập, ngắn gọn, có thể kiểm chứng). Bỏ câu xã giao/dẫn nhập không "
        "mang thông tin. Trả về DUY NHẤT JSON: {\"claims\": [\"...\", ...]}.\n\n"
        f"CÂU HỎI: {question}\n\nCÂU TRẢ LỜI:\n{answer}"
    ))
    claims = (ex or {}).get("claims") or []
    if not claims:
        # Không có claim thông tin (vd câu né/chào hỏi) → faithfulness không áp dụng.
        return {"score": None, "n_claims": 0, "n_supported": 0}
    ctxs = _contexts_block(contexts, CTX_TRIM_FAITH)
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
    vd = _json_call(llm, (
        "Cho NGỮ CẢNH (các đoạn nguồn) và danh sách MỆNH ĐỀ rút từ câu trả lời. Với mỗi "
        "mệnh đề, xác định nó có được SUY RA TRỰC TIẾP từ ngữ cảnh không (supported=true) "
        "hay không (false — kể cả khi đúng thực tế nhưng ngữ cảnh không nói). Trả DUY NHẤT "
        "JSON: {\"verdicts\": [{\"idx\": 1, \"supported\": true}, ...]}.\n\n"
        f"NGỮ CẢNH:\n{ctxs}\n\nMỆNH ĐỀ:\n{numbered}"
    ))
    verdicts = (vd or {}).get("verdicts") or []
    n_sup = sum(1 for v in verdicts if v.get("supported"))
    n = len(claims)
    return {"score": n_sup / n if n else None, "n_claims": n, "n_supported": n_sup}


def answer_relevance(llm, embedder, question, answer) -> dict:
    """RAGAS: sinh ngược câu hỏi từ answer → cosine với câu hỏi gốc. Answer né → 0."""
    res = _json_call(llm, (
        f"Cho CÂU TRẢ LỜI sau, hãy sinh {N_GEN_Q} câu hỏi mà câu trả lời này trả lời trực "
        "tiếp. Nếu câu trả lời mang tính NÉ TRÁNH/không cung cấp thông tin (vd 'không tìm "
        "thấy', 'vui lòng nêu rõ hơn'), đặt noncommittal=1. Trả DUY NHẤT JSON: "
        "{\"questions\": [\"...\"], \"noncommittal\": 0}.\n\n"
        f"CÂU TRẢ LỜI:\n{answer}"
    ))
    if not res:
        return {"score": None, "noncommittal": None}
    if res.get("noncommittal"):
        return {"score": 0.0, "noncommittal": 1}
    gen_qs = res.get("questions") or []
    if not gen_qs:
        return {"score": None, "noncommittal": 0}
    q_emb = _embed_text(embedder, question)
    sims = [_cos(q_emb, _embed_text(embedder, gq)) for gq in gen_qs]
    return {"score": sum(sims) / len(sims), "noncommittal": 0}


def context_precision(llm, question, contexts) -> dict:
    """RAGAS/TruLens: tỉ lệ đoạn context liên quan câu hỏi (1 call batch)."""
    if not contexts:
        return {"score": None, "n_ctx": 0, "n_relevant": 0}
    block = _contexts_block(contexts, CTX_TRIM_PREC)
    vd = _json_call(llm, (
        "Cho CÂU HỎI và danh sách đoạn NGỮ CẢNH. Với mỗi đoạn, xác định nó có LIÊN QUAN và "
        "hữu ích để trả lời câu hỏi không (relevant=true/false). Trả DUY NHẤT JSON: "
        "{\"verdicts\": [{\"idx\": 1, \"relevant\": true}, ...]} (idx theo số 'Nguồn i').\n\n"
        f"CÂU HỎI: {question}\n\nNGỮ CẢNH:\n{block}"
    ))
    verdicts = (vd or {}).get("verdicts") or []
    n_rel = sum(1 for v in verdicts if v.get("relevant"))
    n = len(contexts)
    return {"score": n_rel / n if n else None, "n_ctx": n, "n_relevant": n_rel}


def mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="ReAct")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    suffix = "" if args.engine == "ReAct" else f"_{args.engine}"
    gen_path = EXP02 / f"gen_outputs{suffix}.jsonl"
    cache_path = EXP02 / f"generation_scores{suffix}.jsonl"
    out_csv = EXP02 / f"generation_results{suffix}.csv"
    out_json = EXP02 / f"generation_summary{suffix}.json"
    if not gen_path.exists():
        print(f"Chưa có {gen_path}. Chạy gen_outputs.py trước.")
        return 1
    if args.reset and cache_path.exists():
        cache_path.unlink()

    gen = [json.loads(l) for l in open(gen_path, encoding="utf-8")]
    if args.limit:
        gen = gen[: args.limit]

    cached: dict[str, dict] = {}
    if cache_path.exists():
        for l in open(cache_path, encoding="utf-8"):
            r = json.loads(l)
            cached[r["id"]] = r
        print(f"Cache: {len(cached)} câu đã chấm — bỏ qua.")

    print(f"Khởi tạo judge (gpt-4o) + embedder...  ({len(gen)} câu, engine={args.engine})")
    llm = build_judge()
    embedder = build_embedder()

    cache_f = open(cache_path, "a", encoding="utf-8")
    results = []
    for n, item in enumerate(gen, 1):
        if item["id"] in cached:
            results.append(cached[item["id"]])
            continue
        q, a, ctxs = item["question"], item["answer"], item.get("contexts", [])
        f = faithfulness(llm, q, a, ctxs)
        ar = answer_relevance(llm, embedder, q, a)
        cp = context_precision(llm, q, ctxs)
        row = {
            "id": item["id"], "q_type": item["q_type"], "linh_vuc": item.get("linh_vuc"),
            "faithfulness": f["score"], "n_claims": f["n_claims"],
            "answer_relevance": ar["score"], "noncommittal": ar["noncommittal"],
            "context_precision": cp["score"], "n_ctx": cp["n_ctx"],
            "question": q,
        }
        results.append(row)
        cache_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        cache_f.flush()
        print(f"  [{n}/{len(gen)}] {item['q_type']:14s} "
              f"faith={_p(f['score'])} ansrel={_p(ar['score'])} ctxprec={_p(cp['score'])}  {q[:40]}")
    cache_f.close()

    # ── ghi CSV ──
    fields = ["id", "q_type", "linh_vuc", "faithfulness", "n_claims",
              "answer_relevance", "noncommittal", "context_precision", "n_ctx", "question"]
    with open(out_csv, "w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    # ── tổng hợp ──
    metrics = ["faithfulness", "answer_relevance", "context_precision"]
    by_type = defaultdict(list)
    for r in results:
        by_type[r["q_type"]].append(r)
    summary = {
        "n": len(results), "engine": args.engine,
        "overall": {m: mean(results, m) for m in metrics},
        "by_q_type": {g: {m: mean(rows, m) for m in metrics} | {"n": len(rows)}
                      for g, rows in by_type.items()},
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== TỔNG THỂ (engine={}) ==".format(args.engine))
    for m in metrics:
        print(f"  {m:20s}: {_p(summary['overall'][m])}  (n={len(results)})")
    print("\n== THEO NHÓM ==")
    print(f"  {'nhóm':<16}{'faith':>9}{'ansrel':>9}{'ctxprec':>9}{'n':>5}")
    for g in sorted(by_type):
        s = summary["by_q_type"][g]
        print(f"  {g:<16}{_p(s['faithfulness']):>9}{_p(s['answer_relevance']):>9}"
              f"{_p(s['context_precision']):>9}{s['n']:>5}")
    print(f"\nĐã ghi: {out_csv}\n        {out_json}")
    return 0


def _p(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "—"


if __name__ == "__main__":
    raise SystemExit(main())
