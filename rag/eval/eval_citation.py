"""exp02 — Bước ③: chấm CITATION (ALCE-style) trên gen_outputs.jsonl.

Inline citation 【n】 là điểm bán hàng chính của hệ. Đo theo ALCE (Gao 2023) — dùng
gpt-4o làm judge entailment thay NLI tiếng Anh (xem GENERATION_EVAL_METHODOLOGY.md §2.2/2.3):
  - citation_recall   : tỉ lệ CÂU có trích dẫn mà HỢP các nguồn được dẫn ENTAIL câu đó
                        (mỗi câu được nguồn của nó hỗ trợ đầy đủ không).
  - citation_precision: tỉ lệ TRÍCH DẪN 【n】 mà nguồn tương ứng thực sự hỗ trợ câu
                        (phạt trích dẫn thừa/lạc).
  - citation_f1       : harmonic mean.

Phụ trợ (minh bạch): tỉ lệ câu mang thông tin nhưng KHÔNG có 【n】 (uncited claims).

Nguồn cho 【n】 lấy từ field citations[].snippet (spans đã khớp evidence ↔ answer, dựng
bởi match_evidence_with_context ở engine.build_citations). KHÔNG chạy lại pipeline.
Cache resumable theo id.

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\eval_citation.py
  .venv\\Scripts\\python.exe rag\\eval\\eval_citation.py --engine simple --limit 5
"""
from __future__ import annotations

import argparse
import csv
import json
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
from eval_generation import _json_call, _p, build_judge, mean  # noqa: E402

EXP02 = ROOT / "data" / "eval" / "exp02_generation"
CITE_RE = re.compile(r"【(\d+)】")


def split_sentences(text: str) -> list[str]:
    """Tách câu thô cho tiếng Việt: theo . ! ? ; xuống dòng. Giữ marker 【n】 trong câu."""
    text = re.sub(r"\s+", " ", text or "").strip()
    # tách sau dấu kết câu, nhưng KHÔNG tách số thập phân / số mục "1." đầu dòng đã bị gộp
    parts = re.split(r"(?<=[\.\!\?;:])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


def idx_to_source(citations: list[dict]) -> dict[int, dict]:
    """Map số trích dẫn n -> {title, snippet} từ các citation 'cited' (có indices)."""
    out: dict[int, dict] = {}
    for c in citations:
        for n in (c.get("indices") or []):
            out[int(n)] = {"title": c.get("title", "-"),
                           "snippet": c.get("snippet", ""),
                           "is_web": bool(c.get("is_web"))}
    return out


def score_record(llm, item: dict) -> dict:
    """Trả per-record: n_sent, n_cited_sent, n_uncited_claim, recall_num, n_cit, prec_num."""
    answer = item.get("answer", "")
    idx2src = idx_to_source(item.get("citations", []))
    sents = split_sentences(answer)

    # Gom dữ liệu các câu CÓ trích dẫn để chấm trong MỘT call/record.
    payload = []   # [{sent, cites:[{n, title, snippet}]}]
    for s in sents:
        ns = [int(x) for x in CITE_RE.findall(s)]
        ns = [n for n in ns if n in idx2src]
        if ns:
            payload.append({
                "sent": CITE_RE.sub("", s).strip(),  # bỏ marker khi đưa judge
                "cites": [{"n": n, **idx2src[n]} for n in ns],
            })

    n_sent = len(sents)
    n_cited_sent = len(payload)
    # câu mang thông tin nhưng không có citation: ước lượng = câu không-trích-dẫn đủ dài,
    # không phải câu xã giao (heuristic minh bạch, không vào recall/precision).
    n_uncited_claim = sum(
        1 for s in sents
        if not CITE_RE.search(s) and len(s) > 30
        and not re.search(r"(xin chào|cảm ơn|vui lòng|bạn cần|sau đây|như sau)", s.lower())
    )

    if not payload:
        return {"n_sent": n_sent, "n_cited_sent": 0, "n_uncited_claim": n_uncited_claim,
                "recall_num": 0, "n_cit": 0, "prec_num": 0,
                "recall": None, "precision": None}

    block = []
    for i, p in enumerate(payload, 1):
        srcs = "\n".join(
            f"   【{c['n']}】 {c['title']}: {(c['snippet'] or '')[:400]}" for c in p["cites"]
        )
        block.append(f"CÂU {i}: {p['sent']}\n  NGUỒN ĐƯỢC DẪN:\n{srcs}")
    vd = _json_call(llm, (
        "Bạn kiểm tra TRÍCH DẪN. Với mỗi CÂU và các NGUỒN nó dẫn, hãy xác định:\n"
        "  - union_supports: HỢP TẤT CẢ nguồn được dẫn có ĐỦ để suy ra nội dung câu không "
        "(true/false).\n"
        "  - per_cite: với TỪNG nguồn 【n】, nguồn đó có GÓP PHẦN hỗ trợ câu không (true), "
        "hay thừa/lạc (false).\n"
        "Trả DUY NHẤT JSON: {\"items\":[{\"sent\":1,\"union_supports\":true,"
        "\"per_cite\":[{\"n\":1,\"supports\":true}]}, ...]}.\n\n"
        + "\n\n".join(block)
    ))
    items = (vd or {}).get("items") or []
    by_sent = {it.get("sent"): it for it in items}

    recall_num = 0
    n_cit = 0
    prec_num = 0
    for i, p in enumerate(payload, 1):
        it = by_sent.get(i, {})
        if it.get("union_supports"):
            recall_num += 1
        pc = {d.get("n"): d.get("supports") for d in (it.get("per_cite") or [])}
        for c in p["cites"]:
            n_cit += 1
            if pc.get(c["n"]):
                prec_num += 1

    recall = recall_num / n_cited_sent if n_cited_sent else None
    precision = prec_num / n_cit if n_cit else None
    return {"n_sent": n_sent, "n_cited_sent": n_cited_sent,
            "n_uncited_claim": n_uncited_claim, "recall_num": recall_num,
            "n_cit": n_cit, "prec_num": prec_num,
            "recall": recall, "precision": precision}


def f1(p, r):
    if p is None or r is None or (p + r) == 0:
        return None
    return 2 * p * r / (p + r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="ReAct")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    suffix = "" if args.engine == "ReAct" else f"_{args.engine}"
    gen_path = EXP02 / f"gen_outputs{suffix}.jsonl"
    cache_path = EXP02 / f"citation_scores{suffix}.jsonl"
    out_csv = EXP02 / f"citation_results{suffix}.csv"
    out_json = EXP02 / f"citation_summary{suffix}.json"
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

    print(f"Khởi tạo judge (gpt-4o)...  ({len(gen)} câu, engine={args.engine})")
    llm = build_judge()

    cache_f = open(cache_path, "a", encoding="utf-8")
    results = []
    for n, item in enumerate(gen, 1):
        if item["id"] in cached:
            results.append(cached[item["id"]])
            continue
        sc = score_record(llm, item)
        row = {"id": item["id"], "q_type": item["q_type"],
               "citation_recall": sc["recall"], "citation_precision": sc["precision"],
               "citation_f1": f1(sc["precision"], sc["recall"]),
               "n_cited_sent": sc["n_cited_sent"], "n_cit": sc["n_cit"],
               "n_uncited_claim": sc["n_uncited_claim"], "question": item["question"]}
        results.append(row)
        cache_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        cache_f.flush()
        print(f"  [{n}/{len(gen)}] {item['q_type']:14s} "
              f"R={_p(sc['recall'])} P={_p(sc['precision'])} "
              f"cit={sc['n_cit']} uncited={sc['n_uncited_claim']}  {item['question'][:36]}")
    cache_f.close()

    fields = ["id", "q_type", "citation_recall", "citation_precision", "citation_f1",
              "n_cited_sent", "n_cit", "n_uncited_claim", "question"]
    with open(out_csv, "w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    by_type = defaultdict(list)
    for r in results:
        by_type[r["q_type"]].append(r)
    ov_r = mean(results, "citation_recall")
    ov_p = mean(results, "citation_precision")
    summary = {
        "n": len(results), "engine": args.engine,
        "overall": {"citation_recall": ov_r, "citation_precision": ov_p,
                    "citation_f1": f1(ov_p, ov_r),
                    "avg_uncited_claim": mean(results, "n_uncited_claim")},
        "by_q_type": {g: {"citation_recall": mean(rows, "citation_recall"),
                          "citation_precision": mean(rows, "citation_precision"),
                          "n": len(rows)} for g, rows in by_type.items()},
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n== CITATION (engine={args.engine}, n={len(results)}) ==")
    print(f"  citation_recall    : {_p(ov_r)}")
    print(f"  citation_precision : {_p(ov_p)}")
    print(f"  citation_f1        : {_p(f1(ov_p, ov_r))}")
    print(f"  TB câu claim không trích dẫn: {_p(mean(results,'n_uncited_claim'))}")
    print(f"\nĐã ghi: {out_csv}\n        {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
