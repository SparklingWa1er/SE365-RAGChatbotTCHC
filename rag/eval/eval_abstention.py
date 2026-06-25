"""exp02 — Nhóm A: chấm ABSTENTION (từ chối đúng lúc) ở tầng CÂU TRẢ LỜI.

Bổ sung cho eval_gate.py của exp01: gate đo ở tầng RETRIEVAL (doc có lọt cổng không),
script này đo ở tầng ANSWER CUỐI (hệ có thực sự NÓI 'không tìm thấy' không). Căn cứ:
answerability / abstention — SQuAD 2.0 (Rajpurkar 2018), xem GENERATION_EVAL_METHODOLOGY.md.

Phân loại mỗi câu trả lời = {abstain (từ chối/không cung cấp thông tin) | substantive
(trả lời thực chất)} bằng gpt-4o, rồi tính:
  - oos_abstention_rate : % câu OUT_OF_SCOPE mà hệ ABSTAIN (cao = tốt — đúng đắn nói không).
  - oos_over_answer_rate: % câu OUT_OF_SCOPE mà hệ vẫn trả lời thực chất (thấp = tốt —
                          rủi ro bịa thông tin không có căn cứ).
  - inscope_answer_rate : % câu IN-SCOPE mà hệ trả lời thực chất (cao = tốt — không từ chối
                          nhầm câu hợp lệ; đối chiếu gate_recall 0.65 của exp01).

Cần gen_outputs.jsonl có CẢ câu out_of_scope → chạy:
  .venv\\Scripts\\python.exe rag\\eval\\gen_outputs.py --include-oos --per-type 8

Rồi:
  .venv\\Scripts\\python.exe rag\\eval\\eval_abstention.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))

import flowsettings  # noqa: E402
from eval_generation import _json_call, _p, build_judge  # noqa: E402

EXP02 = ROOT / "data" / "eval" / "exp02_generation"


def classify(llm, answer: str) -> str:
    """'abstain' nếu câu trả lời từ chối/không cung cấp thông tin thực chất; else 'substantive'."""
    res = _json_call(llm, (
        "Phân loại CÂU TRẢ LỜI sau của một chatbot thủ tục hành chính:\n"
        "  - \"abstain\": từ chối / nói không tìm thấy / yêu cầu nêu rõ hơn / không cung "
        "cấp thông tin thủ tục thực chất.\n"
        "  - \"substantive\": có cung cấp thông tin/hướng dẫn thực chất về một thủ tục.\n"
        "Trả DUY NHẤT JSON: {\"label\": \"abstain\"} hoặc {\"label\": \"substantive\"}.\n\n"
        f"CÂU TRẢ LỜI:\n{answer[:1500]}"
    ))
    lab = (res or {}).get("label", "")
    return "abstain" if lab == "abstain" else "substantive"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="ReAct")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    suffix = "" if args.engine == "ReAct" else f"_{args.engine}"
    gen_path = EXP02 / f"gen_outputs{suffix}.jsonl"
    cache_path = EXP02 / f"abstention_scores{suffix}.jsonl"
    out_csv = EXP02 / f"abstention_results{suffix}.csv"
    out_json = EXP02 / f"abstention_summary{suffix}.json"
    if not gen_path.exists():
        print(f"Chưa có {gen_path}. Chạy gen_outputs.py trước.")
        return 1
    if args.reset and cache_path.exists():
        cache_path.unlink()

    gen = [json.loads(l) for l in open(gen_path, encoding="utf-8")]
    n_oos = sum(1 for r in gen if r["q_type"] == "out_of_scope")
    if n_oos == 0:
        print("⚠️  gen_outputs chưa có câu out_of_scope. Chạy gen_outputs.py --include-oos trước "
              "(vẫn chấm được phần in-scope).")

    cached: dict[str, dict] = {}
    if cache_path.exists():
        for l in open(cache_path, encoding="utf-8"):
            r = json.loads(l)
            cached[r["id"]] = r
        print(f"Cache: {len(cached)} câu đã chấm — bỏ qua.")

    print(f"Khởi tạo judge (gpt-4o)...  ({len(gen)} câu, oos={n_oos}, engine={args.engine})")
    llm = build_judge()

    cache_f = open(cache_path, "a", encoding="utf-8")
    results = []
    for n, item in enumerate(gen, 1):
        if item["id"] in cached:
            results.append(cached[item["id"]])
            continue
        label = classify(llm, item.get("answer", ""))
        is_oos = item["q_type"] == "out_of_scope"
        # đúng = oos&abstain HOẶC inscope&substantive
        correct = (is_oos and label == "abstain") or (not is_oos and label == "substantive")
        row = {"id": item["id"], "q_type": item["q_type"], "is_oos": is_oos,
               "label": label, "correct": correct, "question": item["question"]}
        results.append(row)
        cache_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        cache_f.flush()
        flag = "✓" if correct else "✗"
        print(f"  [{flag}] {item['q_type']:14s} -> {label:11s}  {item['question'][:45]}")
    cache_f.close()

    with open(out_csv, "w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=list(results[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    oos = [r for r in results if r["is_oos"]]
    insc = [r for r in results if not r["is_oos"]]
    oos_abstain = sum(1 for r in oos if r["label"] == "abstain") / len(oos) if oos else None
    oos_over = sum(1 for r in oos if r["label"] == "substantive") / len(oos) if oos else None
    insc_answer = sum(1 for r in insc if r["label"] == "substantive") / len(insc) if insc else None
    summary = {
        "n": len(results), "engine": args.engine,
        "n_out_of_scope": len(oos), "n_in_scope": len(insc),
        "oos_abstention_rate": oos_abstain,
        "oos_over_answer_rate": oos_over,
        "inscope_answer_rate": insc_answer,
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n== ABSTENTION (engine={args.engine}) ==")
    print(f"  OOS — từ chối đúng (abstain)     : {_p(oos_abstain)}  (n={len(oos)})")
    print(f"  OOS — trả lời nhầm (over-answer) : {_p(oos_over)}  (thấp = tốt)")
    print(f"  In-scope — trả lời thực chất     : {_p(insc_answer)}  (n={len(insc)}; cao = tốt)")
    print(f"\nĐã ghi: {out_csv}\n        {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
