"""Đánh giá tầng RETRIEVAL trên bộ GT (data/eval/retrieval_gt.jsonl).

Chạy headless (bootstrap như query_test): dựng retriever search-all -> với mỗi câu
hỏi lấy danh sách thủ tục xếp hạng (dedup theo `ma_thu_tuc`, giữ rank tốt nhất) ->
tính Hit@k / MRR / nDCG so với gold-set. Tổng hợp TOÀN BỘ + TÁCH theo q_type
(và theo lĩnh vực) để phân tích lỗi từng nhóm.

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\eval_retrieval.py
  .venv\\Scripts\\python.exe rag\\eval\\eval_retrieval.py --topk 20 --limit 30

Output: in bảng + ghi data/eval/retrieval_results.csv (per-question) và
        data/eval/retrieval_summary.json (tổng hợp).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))

import flowsettings  # noqa: E402  (theflow nạp file-based)
from ktem.main import App  # noqa: E402

EXP = ROOT / "data" / "eval" / "exp01_retrieval"
GT = EXP / "retrieval_gt.jsonl"
OUT_CSV = EXP / "retrieval_results.csv"
OUT_JSON = EXP / "retrieval_summary.json"
KS = (1, 3, 5, 10)


def all_doc_ids(file_index):
    from ktem.db.engine import engine
    from sqlmodel import Session, select

    Source = file_index._resources["Source"]
    with Session(engine) as s:
        return [r[0].id for r in s.execute(select(Source)).all()]


def build_retrievers(file_index, settings, topk, mode=None):
    prefix = f"index.options.{file_index.id}."
    stripped = {k[len(prefix):]: v for k, v in settings.items() if k.startswith(prefix)}
    stripped["num_retrieval"] = max(topk, stripped.get("num_retrieval", 15))
    if mode:
        stripped["retrieval_mode"] = mode  # 'hybrid' | 'vector' | 'text'
    selected = all_doc_ids(file_index)
    print(f"  (tổng tài liệu trong index: {len(selected)})")
    retrievers = []
    for cls in file_index._retriever_pipeline_cls:
        obj = cls.get_pipeline(stripped, file_index.config, selected)
        if obj is None:
            continue
        obj.Source = file_index._resources["Source"]
        obj.Index = file_index._resources["Index"]
        obj.VS = file_index._vs
        obj.DS = file_index._docstore
        obj.FSPath = file_index._fs_path
        obj.user_id = "default"
        if hasattr(obj, "top_k"):
            obj.top_k = topk
        retrievers.append(obj)
    return retrievers


def _doc_ma(doc) -> str | None:
    """Mã thủ tục của doc. Doc retrieve KHÔNG mang ma_thu_tuc trong metadata; nó nằm
    ở tiền tố file_name dạng '<ma_thu_tuc>__<uuid>.md'."""
    m = getattr(doc, "metadata", {}) or {}
    if m.get("ma_thu_tuc"):
        return m["ma_thu_tuc"]
    fn = m.get("file_name") or ""
    return fn.split("__", 1)[0] if "__" in fn else None


def _doc_score(doc) -> float:
    m = getattr(doc, "metadata", {}) or {}
    return m.get("reranking_score") or getattr(doc, "score", 0.0) or 0.0


def ranked_procedures(retrievers, question, topk):
    """Danh sách ma_thu_tuc xếp hạng, dedup giữ lần xuất hiện đầu (rank tốt nhất)."""
    docs = []
    for r in retrievers:
        try:
            docs += r(question)
        except Exception as e:  # noqa: BLE001
            print(f"    (retriever lỗi: {e})")
    # nhiều retriever -> sắp theo score giảm dần để hợp nhất công bằng
    docs.sort(key=_doc_score, reverse=True)
    seen, order = set(), []
    for d in docs:
        ma = _doc_ma(d)
        if ma and ma not in seen:
            seen.add(ma)
            order.append(ma)
    return order[:topk]


def metrics_for(ranked, gold):
    """gold: set ma_thu_tuc. Trả dict hit@k, rr, ndcg@10, recall@5."""
    gold = set(gold)
    out = {}
    first_rank = next((i + 1 for i, m in enumerate(ranked) if m in gold), None)
    out["rr"] = 1.0 / first_rank if first_rank else 0.0
    for k in KS:
        out[f"hit@{k}"] = 1.0 if any(m in gold for m in ranked[:k]) else 0.0
    out["recall@5"] = len(gold & set(ranked[:5])) / len(gold) if gold else 0.0
    # nDCG@10 (relevance nhị phân)
    dcg = sum(1.0 / math.log2(i + 2) for i, m in enumerate(ranked[:10]) if m in gold)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    out["_first_rank"] = first_rank or 0
    return out


def mean(rows, key):
    vals = [r[key] for r in rows if key in r]
    return sum(vals) / len(vals) if vals else 0.0


def fmt_table(title, groups, rows_by_group):
    cols = [f"hit@{k}" for k in KS] + ["recall@5", "mrr", "ndcg@10", "n"]
    print(f"\n{title}")
    head = f"  {'nhóm':<18}" + "".join(f"{c:>10}" for c in cols)
    print(head)
    print("  " + "-" * (len(head) - 2))
    for g in groups:
        rows = rows_by_group[g]
        if not rows:
            continue
        cells = [f"{mean(rows, f'hit@{k}'):.3f}" for k in KS]
        cells += [f"{mean(rows, 'recall@5'):.3f}", f"{mean(rows, 'rr'):.3f}",
                  f"{mean(rows, 'ndcg@10'):.3f}", str(len(rows))]
        print(f"  {g:<18}" + "".join(f"{c:>10}" for c in cells))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=20, help="số kết quả lấy về (>=10)")
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N câu đầu (debug)")
    ap.add_argument("--mode", default=None, choices=["hybrid", "vector", "text"],
                    help="retrieval_mode (mặc định lấy từ settings = hybrid)")
    ap.add_argument("--gt", default=str(GT), help="đường dẫn file GT")
    ap.add_argument("--suffix", default="", help="hậu tố tên file output (vd '_vector')")
    args = ap.parse_args()

    gt_path = Path(args.gt)
    if not gt_path.exists():
        print(f"Chưa có GT: {gt_path}. Chạy gen_gt.py trước.")
        return 1
    gt = [json.loads(l) for l in open(gt_path, encoding="utf-8")]
    gt = [r for r in gt if r.get("gold_ma_thu_tuc")]  # bỏ câu ngoài phạm vi (đo ở eval_gate)
    if args.limit:
        gt = gt[: args.limit]
    print(f"GT: {len(gt)} câu. Khởi tạo kotaemon...")

    app = App()
    settings = app.default_settings.flatten()
    file_index = next(
        i for i in app.index_manager.indices if type(i).__name__ == "FileIndex"
    )
    retrievers = build_retrievers(file_index, settings, args.topk, args.mode)
    print(f"  retrieval_mode = {args.mode or 'hybrid (mặc định)'}")

    results = []
    for n, item in enumerate(gt, 1):
        ranked = ranked_procedures(retrievers, item["question"], args.topk)
        m = metrics_for(ranked, item["gold_ma_thu_tuc"])
        row = {**{k: item[k] for k in ("id", "q_type", "linh_vuc", "question",
                                       "primary_ma_thu_tuc")}, **m}
        results.append(row)
        if n % 10 == 0 or n == len(gt):
            print(f"  ...{n}/{len(gt)} (hit@5 tích lũy = {mean(results, 'hit@5'):.3f})")

    # ── ghi CSV per-question ──
    out_csv = OUT_CSV.with_name(f"retrieval_results{args.suffix}.csv")
    out_json = OUT_JSON.with_name(f"retrieval_summary{args.suffix}.json")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "q_type", "linh_vuc", "primary_ma_thu_tuc", "_first_rank",
              "rr", "ndcg@10", "recall@5"] + [f"hit@{k}" for k in KS] + ["question"]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    # ── tổng hợp ──
    by_type = defaultdict(list)
    for r in results:
        by_type[r["q_type"]].append(r)
    by_lv = defaultdict(list)
    for r in results:
        by_lv[r["linh_vuc"]].append(r)

    fmt_table("== TỔNG THỂ ==", ["(tất cả)"], {"(tất cả)": results})
    fmt_table("== THEO NHÓM QUERY (phân tích lỗi) ==",
              sorted(by_type), by_type)
    top_lv = sorted(by_lv, key=lambda k: -len(by_lv[k]))[:10]
    fmt_table("== THEO LĨNH VỰC (top 10 nhiều câu nhất) ==", top_lv, by_lv)

    summary = {
        "n": len(results),
        "overall": {c: mean(results, c) for c in
                    [f"hit@{k}" for k in KS] + ["recall@5", "rr", "ndcg@10"]},
        "by_q_type": {g: {c: mean(rows, c) for c in
                          [f"hit@{k}" for k in KS] + ["recall@5", "rr", "ndcg@10"]}
                      | {"n": len(rows)} for g, rows in by_type.items()},
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nĐã ghi: {out_csv}\n        {out_json}")

    # gợi ý đọc kết qual
    worst = min(by_type, key=lambda g: mean(by_type[g], "hit@5"))
    best = max(by_type, key=lambda g: mean(by_type[g], "hit@5"))
    print(f"\nNhóm YẾU nhất: {worst} (hit@5={mean(by_type[worst],'hit@5'):.3f}) | "
          f"MẠNH nhất: {best} (hit@5={mean(by_type[best],'hit@5'):.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
