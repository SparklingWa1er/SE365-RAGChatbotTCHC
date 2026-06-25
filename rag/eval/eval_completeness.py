"""exp02 — Nhóm A: chấm CONTEXT RECALL + ANSWER COMPLETENESS trên gen_outputs.jsonl.

Hai metric reference-based, dùng CHUNG một "checklist gold" trích từ corpus (section
đúng của thủ tục gold) → tiết kiệm call (xem GENERATION_EVAL_METHODOLOGY.md §2.1):

  - context_recall     : tỉ lệ điểm-thông-tin gold XUẤT HIỆN trong các đoạn CONTEXT đã gom
                         (RAGAS context recall). Bù cho context_precision: đo "có bỏ SÓT
                         thông tin cần thiết khi gom nguồn không". Cao = retrieval/assembly đủ.
  - answer_completeness: tỉ lệ điểm-thông-tin gold XUẤT HIỆN trong CÂU TRẢ LỜI cuối
                         (G-Eval rubric). Đo "synthesis có liệt kê đủ không" — đặc thù thủ
                         tục HC (thiếu một giấy tờ = dân đi lại nhiều lần).

VÌ SAO reference-based ở đây (khác faithfulness reference-free): completeness/recall buộc
phải có "đáng lẽ phải có gì" → checklist gold là chuẩn so sánh. Checklist kéo BÁN TỰ ĐỘNG
từ corpus có cấu trúc (section "Thành phần hồ sơ"/"Phí, lệ phí"...) nên không soạn tay.

PHẠM VI: chỉ chấm câu in-scope có section gold xác định được. Câu mơ hồ (scenario) hoặc
hỏi một-điểm (factual đơn) thì completeness trivial → vẫn chấm nhưng đọc theo nhóm. Câu
out_of_scope KHÔNG áp dụng (không có thủ tục gold).

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\eval_completeness.py
  .venv\\Scripts\\python.exe rag\\eval\\eval_completeness.py --q-types aspect_hoso,aspect_phi_dk
"""
from __future__ import annotations

import argparse
import csv
import json
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
from eval_generation import _json_call, _p, build_judge, mean  # noqa: E402
from gen_gt import load_corpus  # noqa: E402  (tái dùng đọc corpus -> procs[id].sections)

EXP01 = ROOT / "data" / "eval" / "exp01_retrieval"
EXP02 = ROOT / "data" / "eval" / "exp02_generation"
GOLD_SECTION_TRIM = 2500   # cắt section gold khi tách checklist
CTX_TRIM = 600             # cắt mỗi context khi chấm phủ
MAX_CHECKLIST = 15         # trần điểm/câu (chống section quá dài bùng call)


def gt_index() -> dict[str, dict]:
    """Map GT id -> {procedure_id, source_section} (từ GT gốc auto + manual)."""
    idx = {}
    for fn in ("retrieval_gt.jsonl", "retrieval_gt_manual.jsonl"):
        p = EXP01 / fn
        if not p.exists():
            continue
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            idx[r["id"]] = {"procedure_id": r.get("procedure_id"),
                            "source_section": r.get("source_section"),
                            "gold_ma_thu_tuc": r.get("gold_ma_thu_tuc", [])}
    return idx


def gold_section_text(procs, ma2id, gt_row) -> tuple[str, str]:
    """Trả (tên section dùng làm gold, text). Ưu tiên source_section của câu; nếu là
    '(viết tay)'/None hoặc không có → nối toàn bộ section của thủ tục gold."""
    pid = gt_row.get("procedure_id")
    if not pid:  # manual: map qua ma_thu_tuc
        for ma in gt_row.get("gold_ma_thu_tuc", []):
            pid = ma2id.get(ma)
            if pid:
                break
    p = procs.get(pid)
    if not p:
        return "", ""
    secs = p["sections"]
    sname = gt_row.get("source_section")
    if sname and sname in secs and len(secs[sname]) >= 40:
        return sname, secs[sname][:GOLD_SECTION_TRIM]
    # fallback: toàn bộ thủ tục (cho câu viết tay / không rõ section)
    joined = "\n\n".join(f"[{k}] {v}" for k, v in secs.items() if v)
    return "(toàn thủ tục)", joined[:GOLD_SECTION_TRIM]


def make_checklist(llm, question, sname, gold_text) -> list[str]:
    """Call 1: tách section gold thành các ĐIỂM THÔNG TIN atomic liên quan câu hỏi."""
    res = _json_call(llm, (
        "Cho CÂU HỎI và đoạn TÀI LIỆU GỐC (phần '{sname}' của thủ tục đúng). Hãy liệt kê "
        "các ĐIỂM THÔNG TIN cốt lõi mà MỘT câu trả lời ĐẦY ĐỦ cho câu hỏi này BẮT BUỘC "
        "phải nêu (mỗi điểm là một ý atomic, ngắn gọn). Chỉ lấy điểm LIÊN QUAN câu hỏi, tối "
        "đa {mx} điểm. Trả DUY NHẤT JSON: {{\"points\": [\"...\", ...]}}.\n\n"
        "CÂU HỎI: {q}\n\nTÀI LIỆU GỐC ({sname}):\n{txt}"
    ).format(sname=sname, mx=MAX_CHECKLIST, q=question, txt=gold_text))
    pts = (res or {}).get("points") or []
    return [p for p in pts if isinstance(p, str) and len(p.strip()) >= 4][:MAX_CHECKLIST]


def score_coverage(llm, question, checklist, contexts, answer) -> dict:
    """Call 2: mỗi điểm checklist có trong CONTEXT? có trong ANSWER? (1 call/câu)."""
    ctx = "\n\n".join(f"[Đoạn {i}] {(c.get('text') or '')[:CTX_TRIM]}"
                      for i, c in enumerate(contexts, 1))
    numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(checklist, 1))
    vd = _json_call(llm, (
        "Cho danh sách ĐIỂM THÔNG TIN cần có, kèm NGỮ CẢNH (đoạn nguồn đã thu thập) và "
        "CÂU TRẢ LỜI. Với MỖI điểm, xác định:\n"
        "  - in_context: điểm đó có được nêu trong NGỮ CẢNH không (true/false).\n"
        "  - in_answer : điểm đó có được nêu trong CÂU TRẢ LỜI không (true/false).\n"
        "Trả DUY NHẤT JSON: {\"verdicts\":[{\"idx\":1,\"in_context\":true,\"in_answer\":true}]}.\n\n"
        f"ĐIỂM THÔNG TIN:\n{numbered}\n\nNGỮ CẢNH:\n{ctx}\n\nCÂU TRẢ LỜI:\n{answer}"
    ))
    vs = (vd or {}).get("verdicts") or []
    n = len(checklist)
    n_ctx = sum(1 for v in vs if v.get("in_context"))
    n_ans = sum(1 for v in vs if v.get("in_answer"))
    return {"n_points": n,
            "context_recall": n_ctx / n if n else None,
            "answer_completeness": n_ans / n if n else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="ReAct")
    ap.add_argument("--q-types", default="", help="lọc nhóm (vd aspect_hoso,aspect_phi_dk)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    suffix = "" if args.engine == "ReAct" else f"_{args.engine}"
    gen_path = EXP02 / f"gen_outputs{suffix}.jsonl"
    cache_path = EXP02 / f"completeness_scores{suffix}.jsonl"
    out_csv = EXP02 / f"completeness_results{suffix}.csv"
    out_json = EXP02 / f"completeness_summary{suffix}.json"
    if not gen_path.exists():
        print(f"Chưa có {gen_path}. Chạy gen_outputs.py trước.")
        return 1
    if args.reset and cache_path.exists():
        cache_path.unlink()

    only = set(t for t in args.q_types.split(",") if t) if args.q_types else None
    gen = [json.loads(l) for l in open(gen_path, encoding="utf-8")]
    # loại out_of_scope (không có thủ tục gold) + lọc nhóm nếu chỉ định
    gen = [r for r in gen if r["q_type"] != "out_of_scope"]
    if only:
        gen = [r for r in gen if r["q_type"] in only]
    if args.limit:
        gen = gen[: args.limit]

    cached: dict[str, dict] = {}
    if cache_path.exists():
        for l in open(cache_path, encoding="utf-8"):
            r = json.loads(l)
            cached[r["id"]] = r
        print(f"Cache: {len(cached)} câu đã chấm — bỏ qua.")

    print(f"Nạp corpus + GT map...  ({len(gen)} câu, engine={args.engine})")
    procs, _ = load_corpus()
    ma2id = {}
    for pid, p in procs.items():
        ma2id.setdefault(p["ma_thu_tuc"], pid)
    gtmap = gt_index()
    llm = build_judge()

    cache_f = open(cache_path, "a", encoding="utf-8")
    results, skipped = [], 0
    for n, item in enumerate(gen, 1):
        if item["id"] in cached:
            results.append(cached[item["id"]])
            continue
        gt_row = gtmap.get(item["id"], {})
        sname, gold_text = gold_section_text(procs, ma2id, gt_row)
        if not gold_text:
            skipped += 1
            print(f"  [skip] {item['id']} — không map được section gold")
            continue
        checklist = make_checklist(llm, item["question"], sname, gold_text)
        if not checklist:
            skipped += 1
            print(f"  [skip] {item['id']} — checklist rỗng")
            continue
        sc = score_coverage(llm, item["question"], checklist,
                            item.get("contexts", []), item["answer"])
        row = {"id": item["id"], "q_type": item["q_type"],
               "gold_section": sname, "n_points": sc["n_points"],
               "context_recall": sc["context_recall"],
               "answer_completeness": sc["answer_completeness"],
               "question": item["question"]}
        results.append(row)
        cache_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        cache_f.flush()
        print(f"  [{n}/{len(gen)}] {item['q_type']:14s} pts={sc['n_points']:2d} "
              f"ctxrec={_p(sc['context_recall'])} compl={_p(sc['answer_completeness'])}  "
              f"{item['question'][:38]}")
    cache_f.close()

    fields = ["id", "q_type", "gold_section", "n_points", "context_recall",
              "answer_completeness", "question"]
    with open(out_csv, "w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    by_type = defaultdict(list)
    for r in results:
        by_type[r["q_type"]].append(r)
    summary = {
        "n": len(results), "engine": args.engine, "n_skipped": skipped,
        "overall": {"context_recall": mean(results, "context_recall"),
                    "answer_completeness": mean(results, "answer_completeness")},
        "by_q_type": {g: {"context_recall": mean(rows, "context_recall"),
                          "answer_completeness": mean(rows, "answer_completeness"),
                          "n": len(rows)} for g, rows in by_type.items()},
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n== CONTEXT RECALL + COMPLETENESS (engine={args.engine}, n={len(results)}, "
          f"skip={skipped}) ==")
    print(f"  context_recall     : {_p(summary['overall']['context_recall'])}")
    print(f"  answer_completeness: {_p(summary['overall']['answer_completeness'])}")
    print("\n== THEO NHÓM ==")
    print(f"  {'nhóm':<16}{'ctxrec':>9}{'compl':>9}{'n':>5}")
    for g in sorted(by_type):
        s = summary["by_q_type"][g]
        print(f"  {g:<16}{_p(s['context_recall']):>9}{_p(s['answer_completeness']):>9}{s['n']:>5}")
    print(f"\nĐã ghi: {out_csv}\n        {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
