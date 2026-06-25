"""Sinh các figure thống kê (PNG) + dataset_stats.json cho báo cáo đánh giá.

Đọc corpus (metadata.jsonl, chunks.jsonl) + GT + kết quả eval, vẽ figure vào
data/eval/figures/ và ghi data/eval/dataset_stats.json.

Chạy: .venv\\Scripts\\python.exe rag\\eval\\make_figures.py
"""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({
    "font.family": "DejaVu Sans",  # đủ dấu tiếng Việt
    "font.size": 11,
    "axes.edgecolor": "#cbd5e1",
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.color": "#eef2f6",
    "grid.linewidth": 1,
    "figure.dpi": 130,
})

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "data" / "corpus"
EVAL = ROOT / "data" / "eval" / "exp01_retrieval"
FIG = EVAL / "figures"
FIG.mkdir(parents=True, exist_ok=True)

ACC, ACC2, INK, MUT = "#0e7490", "#c2691a", "#16202e", "#5b6b7f"
GOOD, WARN = "#15803d", "#b45309"
QVI = {"factual_lookup": "Khớp từ khóa", "paraphrase": "Diễn giải",
       "scenario": "Tình huống", "aspect_hoso": "Khía cạnh hồ sơ",
       "aspect_phi_dk": "Khía cạnh phí/ĐK", "keyword_short": "Từ khóa ngắn"}


def jl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ->", name)


# ════════════════════════════ CORPUS ════════════════════════════
def corpus_stats():
    meta = jl(CORPUS / "metadata.jsonl")
    lv = collections.Counter()
    for r in meta:
        for x in (r.get("linh_vuc") or ["(trống)"]):
            lv[x] += 1
    sec = collections.Counter()
    per_proc = collections.Counter()
    n_chunks = 0
    for line in open(CORPUS / "chunks.jsonl", encoding="utf-8"):
        r = json.loads(line)
        sec[r["section"]] += 1
        per_proc[r["doc_id"]] += 1
        n_chunks += 1

    # FIG 1: top 20 lĩnh vực
    top = lv.most_common(20)
    fig, ax = plt.subplots(figsize=(8, 6))
    names = [k for k, _ in top][::-1]
    vals = [v for _, v in top][::-1]
    ax.barh(names, vals, color=ACC)
    for i, v in enumerate(vals):
        ax.text(v + 1, i, str(v), va="center", fontsize=9, color=MUT)
    ax.set_title("Top 20 lĩnh vực theo số thủ tục", fontweight="bold", color=INK)
    ax.set_xlabel("Số thủ tục")
    style(ax)
    save(fig, "fig1_linhvuc.png")

    # FIG 2: độ phủ section
    order = ["Trình tự thực hiện", "Cách thức thực hiện", "Kết quả thực hiện",
             "Thành phần hồ sơ", "Căn cứ pháp lý", "Phí, lệ phí",
             "Yêu cầu, điều kiện thực hiện", "Địa chỉ tiếp nhận hồ sơ"]
    order = [s for s in order if s in sec] + [s for s in sec if s not in order]
    vals = [sec[s] for s in order]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(range(len(order)), vals, color=ACC)
    bars[order.index("Phí, lệ phí")].set_color(ACC2) if "Phí, lệ phí" in order else None
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([s.replace(" thực hiện", "") for s in order], rotation=35,
                       ha="right", fontsize=9)
    for i, v in enumerate(vals):
        ax.text(i, v + 40, str(v), ha="center", fontsize=8, color=MUT)
    ax.set_title("Độ phủ section trên 5.208 thủ tục", fontweight="bold", color=INK)
    ax.set_ylabel("Số chunk")
    style(ax)
    save(fig, "fig2_sections.png")

    # FIG 3: histogram số chunk / thủ tục
    counts = list(per_proc.values())
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(counts, bins=range(1, max(counts) + 2), color=ACC, edgecolor="white")
    mean_c = sum(counts) / len(counts)
    ax.axvline(mean_c, color=ACC2, ls="--", lw=1.5, label=f"TB = {mean_c:.1f}")
    ax.set_title("Phân bố số chunk mỗi thủ tục", fontweight="bold", color=INK)
    ax.set_xlabel("Số chunk")
    ax.set_ylabel("Số thủ tục")
    ax.legend()
    style(ax)
    save(fig, "fig3_chunks_hist.png")

    return {
        "n_procedures": len(meta), "n_chunks": n_chunks,
        "n_linh_vuc": len(lv), "chunks_per_proc_mean": round(mean_c, 2),
        "chunks_per_proc_min": min(counts), "chunks_per_proc_max": max(counts),
        "top_linh_vuc": top[:10],
        "sections": [(s, sec[s]) for s in order],
    }


# ════════════════════════════ GT ════════════════════════════
def gt_stats():
    auto = jl(EVAL / "retrieval_gt.jsonl")
    man = jl(EVAL / "retrieval_gt_manual.jsonl")
    qc = collections.Counter(r["q_type"] for r in auto)
    mc = collections.Counter(r["q_type"] for r in man)
    qlen = [len(r["question"]) for r in auto]

    # FIG 4: phân bố nhóm query
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    g = list(QVI)
    axes[0].bar([QVI[x] for x in g], [qc[x] for x in g], color=ACC)
    axes[0].set_title("180 câu tự sinh — theo nhóm", fontweight="bold", color=INK)
    axes[0].set_ylabel("Số câu")
    axes[0].tick_params(axis="x", rotation=35)
    for lbl in axes[0].get_xticklabels():
        lbl.set_ha("right"); lbl.set_fontsize(9)
    style(axes[0])

    mlabels = ["In-scope\n(viết tay)", "Ngoài\nphạm vi"]
    mvals = [mc.get("manual_inscope", 0), mc.get("out_of_scope", 0)]
    axes[1].bar(mlabels, mvals, color=[ACC, ACC2])
    axes[1].set_title("30 câu viết tay", fontweight="bold", color=INK)
    for i, v in enumerate(mvals):
        axes[1].text(i, v + 0.3, str(v), ha="center", color=MUT)
    style(axes[1])
    save(fig, "fig4_gt_qtype.png")

    return {
        "n_auto": len(auto), "n_manual": len(man),
        "per_type_auto": dict(qc), "per_type_manual": dict(mc),
        "q_len_mean": round(sum(qlen) / len(qlen), 1),
        "q_len_min": min(qlen), "q_len_max": max(qlen),
    }


# ════════════════════════════ EVAL ════════════════════════════
def eval_figs():
    hyb = json.loads((EVAL / "retrieval_summary.json").read_text(encoding="utf-8"))
    vec = json.loads((EVAL / "retrieval_summary_vector.json").read_text(encoding="utf-8"))
    bt = hyb["by_q_type"]

    # FIG 5: Hit@1/5/10 theo nhóm
    g = sorted(bt, key=lambda k: -bt[k]["hit@5"])
    labels = [QVI.get(x, x) for x in g]
    import numpy as np
    x = np.arange(len(g)); w = 0.26
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for i, (k, c) in enumerate([("hit@1", ACC), ("hit@5", ACC2), ("hit@10", "#94a3b8")]):
        ax.bar(x + (i - 1) * w, [bt[t][k] for t in g], w, label=k.replace("hit@", "Hit@"),
               color=c)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.set_title("Hit@k theo nhóm query (hybrid)", fontweight="bold", color=INK)
    ax.legend(ncol=3, frameon=False)
    style(ax)
    save(fig, "fig5_hit_by_qtype.png")

    # FIG 6: hybrid vs vector
    mets = ["hit@1", "hit@5", "hit@10", "recall@5", "rr", "ndcg@10"]
    ml = ["Hit@1", "Hit@5", "Hit@10", "Recall@5", "MRR", "nDCG@10"]
    x = np.arange(len(mets)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.bar(x - w / 2, [hyb["overall"][m] for m in mets], w, label="Hybrid", color=ACC)
    ax.bar(x + w / 2, [vec["overall"][m] for m in mets], w, label="Vector-only", color=ACC2)
    ax.set_xticks(x); ax.set_xticklabels(ml)
    ax.set_ylim(0, 1.05)
    ax.set_title("Hybrid vs Vector-only (180 câu)", fontweight="bold", color=INK)
    ax.legend(frameon=False)
    style(ax)
    save(fig, "fig6_hybrid_vs_vector.png")

    # FIG 7: phân bố thứ hạng câu trả lời đúng đầu tiên (hybrid)
    ranks = []
    for r in csv.DictReader(open(EVAL / "retrieval_results.csv", encoding="utf-8")):
        ranks.append(int(r["_first_rank"]))
    rc = collections.Counter(ranks)
    cats = ["1", "2", "3", "4", "5", "6–10", "11–20", "Trượt (0)"]
    def bucket(rr):
        if rr == 0:
            return "Trượt (0)"
        if rr <= 5:
            return str(rr)
        if rr <= 10:
            return "6–10"
        return "11–20"
    bc = collections.Counter(bucket(r) for r in ranks)
    vals = [bc.get(c, 0) for c in cats]
    cols = [ACC] * 5 + ["#94a3b8", "#cbd5e1", "#dc2626"]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(cats, vals, color=cols)
    for i, v in enumerate(vals):
        ax.text(i, v + 1, str(v), ha="center", fontsize=9, color=MUT)
    ax.set_title("Thứ hạng thủ tục đúng đầu tiên (hybrid, n=180)",
                 fontweight="bold", color=INK)
    ax.set_ylabel("Số câu")
    style(ax)
    save(fig, "fig7_rank_dist.png")

    # FIG 8: cổng relevance
    gate = json.loads((EVAL / "gate_summary.json").read_text(encoding="utf-8"))
    man = json.loads((EVAL / "retrieval_summary_manual.json").read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(7.5, 4))
    labels = ["Hit@5\nviết tay", "Cổng giữ gold\n(in-scope)",
              "Cổng từ chối\n(ngoài phạm vi)"]
    vals = [man["overall"]["hit@5"], gate["gate_recall_inscope"],
            gate["oos_rejection_rate"]]
    cols = [ACC, WARN if vals[1] < 0.9 else GOOD, GOOD if vals[2] >= 0.9 else WARN]
    bars = ax.bar(labels, vals, color=cols, width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center",
                fontweight="bold", color=INK)
    ax.set_ylim(0, 1.1)
    ax.axhline(0.9, color=MUT, ls=":", lw=1)
    ax.set_title("Bộ viết tay & cổng “không tìm thấy”", fontweight="bold", color=INK)
    style(ax)
    save(fig, "fig8_gate.png")

    return {"hybrid": hyb["overall"], "vector": vec["overall"],
            "by_q_type": bt, "gate": gate, "manual": man["overall"],
            "rank_buckets": {c: bc.get(c, 0) for c in cats}}


def main():
    print("Vẽ figure...")
    stats = {"corpus": corpus_stats(), "gt": gt_stats(), "eval": eval_figs()}
    (EVAL / "dataset_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã ghi {EVAL/'dataset_stats.json'} + figure trong {FIG}/")


if __name__ == "__main__":
    raise SystemExit(main())
