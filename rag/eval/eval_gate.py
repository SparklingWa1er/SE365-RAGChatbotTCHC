"""Đánh giá CỔNG relevance (llm_trulens_score) trên bộ GT viết tay.

Cổng này là cơ chế "không tìm thấy" của Simple/ReAct: sau truy hồi, mỗi doc được
LLM chấm điểm liên quan; chỉ giữ doc có llm_trulens_score > 0. Nếu rỗng -> trả lời
"ngoài phạm vi".

Đo 2 chiều trên bộ manual:
  - manual_inscope : cổng có GIỮ được thủ tục gold không (gate recall) + không bóp về 0.
  - out_of_scope   : cổng có TỪ CHỐI HẾT đúng không (specificity / true-negative rate).

Chạy (từ gốc repo, cần BẬT use_llm_reranking -> tự bật trong script):
  .venv\\Scripts\\python.exe rag\\eval\\eval_gate.py
Output: data/eval/gate_results.csv + gate_summary.json
"""
from __future__ import annotations

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
sys.path.insert(0, str(_HERE))

import flowsettings  # noqa: E402
from ktem.main import App  # noqa: E402
from eval_retrieval import all_doc_ids, _doc_ma  # noqa: E402

EXP = ROOT / "data" / "eval" / "exp01_retrieval"
GT = EXP / "retrieval_gt_manual.jsonl"
OUT_CSV = EXP / "gate_results.csv"
OUT_JSON = EXP / "gate_summary.json"
TOPK = 5  # giống production (top_k mặc định)


def build_gated_retriever(file_index, settings, topk):
    """Dựng retriever CÓ bật llm_scorer (gate). get_pipeline đọc use_llm_reranking."""
    prefix = f"index.options.{file_index.id}."
    stripped = {k[len(prefix):]: v for k, v in settings.items() if k.startswith(prefix)}
    stripped["num_retrieval"] = topk
    stripped["use_llm_reranking"] = True  # bật chấm điểm relevance (gate)
    selected = all_doc_ids(file_index)
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
        if getattr(obj, "llm_scorer", None) is not None:
            return obj  # retriever chính (có gate)
    raise RuntimeError("Không dựng được retriever có llm_scorer — kiểm tra use_llm_reranking")


def main() -> int:
    if not GT.exists():
        print(f"Chưa có GT manual: {GT}. Chạy make_manual_gt.py trước.")
        return 1
    gt = [json.loads(l) for l in open(GT, encoding="utf-8")]
    print(f"GT manual: {len(gt)} câu. Khởi tạo kotaemon (bật gate llm_trulens)...")

    app = App()
    settings = app.default_settings.flatten()
    file_index = next(
        i for i in app.index_manager.indices if type(i).__name__ == "FileIndex"
    )
    retr = build_gated_retriever(file_index, settings, TOPK)

    rows = []
    for n, item in enumerate(gt, 1):
        q = item["question"]
        gold = set(item["gold_ma_thu_tuc"])
        try:
            docs = retr(q)
            docs = retr.generate_relevant_scores(q, docs)
        except Exception as e:  # noqa: BLE001
            print(f"  (lỗi: {e})")
            docs = []
        passed = [d for d in docs if (getattr(d, "metadata", {}) or {})
                  .get("llm_trulens_score", 0.0) > 0]
        passed_ma = {_doc_ma(d) for d in passed}
        n_passed = len(passed)
        gold_survives = bool(gold & passed_ma) if gold else None

        if item["q_type"] == "out_of_scope":
            correct = (n_passed == 0)  # đúng = cổng từ chối hết
        else:
            correct = bool(gold_survives)  # đúng = gold qua được cổng
        rows.append({
            "id": item["id"], "q_type": item["q_type"], "question": q,
            "n_retrieved": len(docs), "n_passed_gate": n_passed,
            "gold_survives": gold_survives, "correct": correct,
        })
        flag = "✓" if correct else "✗"
        print(f"  [{flag}] {item['q_type']:14s} qua_cổng={n_passed}/{len(docs)}  {q[:50]}")

    # ── tổng hợp ──
    insc = [r for r in rows if r["q_type"] == "manual_inscope"]
    oos = [r for r in rows if r["q_type"] == "out_of_scope"]
    gate_recall = sum(r["correct"] for r in insc) / len(insc) if insc else 0.0
    oos_reject = sum(r["correct"] for r in oos) / len(oos) if oos else 0.0
    avg_pass_oos = sum(r["n_passed_gate"] for r in oos) / len(oos) if oos else 0.0

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summary = {
        "n_inscope": len(insc), "n_out_of_scope": len(oos),
        "gate_recall_inscope": gate_recall,      # gold sống sót qua cổng
        "oos_rejection_rate": oos_reject,        # ngoài phạm vi bị từ chối đúng
        "avg_docs_passed_oos": avg_pass_oos,     # trung bình doc lọt cổng khi out-of-scope
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print("\n== CỔNG RELEVANCE (bộ viết tay) ==")
    print(f"  In-scope  — gold sống sót qua cổng : {gate_recall:.3f}  (n={len(insc)})")
    print(f"  Out-scope — từ chối đúng (hết doc) : {oos_reject:.3f}  (n={len(oos)})")
    print(f"  Out-scope — TB doc lọt cổng        : {avg_pass_oos:.2f}")
    print(f"\nĐã ghi: {OUT_CSV}\n        {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
