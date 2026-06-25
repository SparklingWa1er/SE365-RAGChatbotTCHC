"""Sinh báo cáo HTML tự chứa (self-contained) từ các kết quả đánh giá retrieval.

Đọc:
  data/eval/retrieval_summary.json          (hybrid, 180 câu tự sinh)
  data/eval/retrieval_summary_vector.json   (vector-only, để so BM25)
  data/eval/retrieval_summary_manual.json   (20 câu viết tay in-scope)  [nếu có]
  data/eval/gate_summary.json               (cổng relevance)            [nếu có]
  data/eval/retrieval_results.csv           (per-question, để soi câu lỗi)

Xuất: data/eval/report.html  (mở trực tiếp bằng trình duyệt, không cần internet).

Chạy: .venv\\Scripts\\python.exe rag\\eval\\make_report.py
"""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVAL = ROOT / "data" / "eval" / "exp01_retrieval"
OUT = EVAL / "report.html"

KS = ["hit@1", "hit@3", "hit@5", "hit@10"]
ALL_METRICS = KS + ["recall@5", "rr", "ndcg@10"]
LABEL = {"hit@1": "Hit@1", "hit@3": "Hit@3", "hit@5": "Hit@5", "hit@10": "Hit@10",
         "recall@5": "Recall@5", "rr": "MRR", "ndcg@10": "nDCG@10"}
QTYPE_VI = {
    "factual_lookup": "Khớp từ khóa", "paraphrase": "Diễn giải",
    "scenario": "Tình huống", "aspect_hoso": "Khía cạnh hồ sơ",
    "aspect_phi_dk": "Khía cạnh phí/ĐK", "keyword_short": "Từ khóa ngắn",
    "manual_inscope": "Viết tay (in-scope)",
}


def load(name):
    p = EVAL / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def bar(value, color="#0e7490", w=260):
    """Một thanh ngang SVG cho [0,1]."""
    fill = max(0, min(1, value)) * w
    return (
        f'<svg width="{w + 52}" height="20" style="vertical-align:middle">'
        f'<rect x="0" y="3" width="{w}" height="14" rx="3" fill="#eef2f7"/>'
        f'<rect x="0" y="3" width="{fill:.0f}" height="14" rx="3" fill="{color}"/>'
        f'<text x="{w + 6}" y="14" font-size="12" fill="#334155">{value:.3f}</text>'
        f"</svg>"
    )


def metric_row(label, vals, color="#0e7490"):
    cells = "".join(f"<td>{bar(vals[m], color)}</td>" for m in ALL_METRICS)
    return f"<tr><th>{html.escape(label)}</th>{cells}</tr>"


def grouped_bars(value_a, value_b, la="hybrid", lb="vector"):
    """2 thanh chồng để so sánh."""
    return (bar(value_a, "#0e7490") + "<br>" + bar(value_b, "#c2691a"))


def main() -> int:
    hyb = load("retrieval_summary.json")
    vec = load("retrieval_summary_vector.json")
    man = load("retrieval_summary_manual.json")
    gate = load("gate_summary.json")
    if hyb is None:
        print("Thiếu retrieval_summary.json — chạy eval_retrieval.py trước.")
        return 1

    # đọc per-question để liệt kê câu lỗi (hit@5 == 0)
    fails = []
    csvp = EVAL / "retrieval_results.csv"
    if csvp.exists():
        for r in csv.DictReader(open(csvp, encoding="utf-8")):
            if float(r.get("hit@5", 1)) == 0.0:
                fails.append(r)

    p = []
    p.append('<title>Đánh giá tầng Retrieval — RAG Thủ tục hành chính</title>')
    p.append("""<style>
      :root{--ink:#16202e;--muted:#5b6b7f;--line:#dfe5ec;--ground:#f4f6f9;
        --accent:#0e7490;--accent2:#c2691a;--good:#15803d;--warn:#b45309;
        --sans:'Segoe UI',system-ui,-apple-system,sans-serif;
        --serif:Georgia,'Times New Roman',serif;
        --mono:'Cascadia Code',Consolas,monospace}
      *{box-sizing:border-box}
      body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
        line-height:1.55;font-size:15px}
      .wrap{max-width:980px;margin:0 auto;padding:40px 24px 72px}
      h1{font-family:var(--serif);font-size:30px;font-weight:600;margin:0 0 6px;
        letter-spacing:-.01em;text-wrap:balance}
      h2{font-family:var(--serif);font-size:21px;font-weight:600;margin:40px 0 14px;
        padding-bottom:8px;border-bottom:2px solid var(--ink)}
      .sub{color:var(--muted);margin:0 0 8px;font-size:14px}
      .cards{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}
      .card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 20px;
        min-width:140px;flex:1}
      .card .v{font-size:32px;font-weight:700;font-variant-numeric:tabular-nums;
        font-family:var(--serif);letter-spacing:-.02em}
      .card .k{color:var(--muted);font-size:12.5px;margin-top:2px}
      .card.good .v{color:var(--good)} .card.warn .v{color:var(--warn)}
      table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);
        border-radius:10px;overflow:hidden;font-variant-numeric:tabular-nums}
      th,td{padding:9px 14px;text-align:left;font-size:14px;border-bottom:1px solid var(--line)}
      tr:last-child td{border-bottom:none}
      thead th{background:#eef2f6;font-size:11px;text-transform:uppercase;
        letter-spacing:.06em;color:var(--muted);font-weight:600}
      tbody th{font-weight:600;white-space:nowrap}
      .legend{font-size:13px;color:var(--muted);margin:10px 0}
      .dot{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;
        vertical-align:middle}
      .note{background:#fdf6ec;border:1px solid #f0d9b5;border-left:4px solid var(--accent2);
        border-radius:8px;padding:12px 16px;font-size:14px;color:#7c4a12;margin:16px 0}
      .ok{background:#eef7f0;border-color:#cce6d4;border-left-color:var(--good);color:#1a5c33}
      code{background:#eef2f6;padding:1px 6px;border-radius:4px;font-size:13px;
        font-family:var(--mono)}
      .fail{font-size:13px} .fail td{color:#6b1f1f}
      svg text{font-variant-numeric:tabular-nums}
    </style>""")
    p.append('<div class="wrap">')
    p.append("<h1>Đánh giá tầng Retrieval</h1>")
    p.append('<p class="sub">Chatbot RAG Thủ tục hành chính công · hybrid (Chroma + LanceDB BM25) + reranker · '
             f'gold = <code>ma_thu_tuc</code> · n = {hyb["n"]} câu tự sinh + '
             f'{(man or {}).get("n", 0)} câu viết tay</p>')

    # ── thẻ tổng quan ──
    o = hyb["overall"]
    def card(k, v, cls=""):
        return f'<div class="card {cls}"><div class="v">{v:.3f}</div><div class="k">{k}</div></div>'
    cls5 = "good" if o["hit@5"] >= 0.9 else "warn"
    clsm = "good" if o["rr"] >= 0.75 else "warn"
    p.append('<div class="cards">')
    p.append(card("Hit@5", o["hit@5"], cls5))
    p.append(card("Hit@10", o["hit@10"], "good" if o["hit@10"] >= 0.9 else "warn"))
    p.append(card("MRR", o["rr"], clsm))
    p.append(card("nDCG@10", o["ndcg@10"], "good" if o["ndcg@10"] >= 0.75 else "warn"))
    p.append("</div>")
    verdict = ("ok", "Đạt ngưỡng kết luận “retrieval tốt” (Hit@5 ≥ 0.90, MRR ≥ 0.75)."
               ) if o["hit@5"] >= 0.9 and o["rr"] >= 0.75 else (
               "note", "Chưa đạt đồng thời Hit@5 ≥ 0.90 và MRR ≥ 0.75.")
    p.append(f'<div class="note {verdict[0]}">{verdict[1]} '
             f'Với n={hyb["n"]}, khoảng tin cậy 95% của Hit@5 ≈ ±{1.96 * (o["hit@5"]*(1-o["hit@5"])/hyb["n"])**0.5:.3f}.</div>')

    # ── theo nhóm query ──
    p.append("<h2>Theo nhóm query (phân tích lỗi)</h2>")
    p.append('<div class="legend"><span class="dot" style="background:#0e7490"></span>điểm số (0–1, càng dài càng tốt)</div>')
    p.append("<table><thead><tr><th>Nhóm</th>" +
             "".join(f"<th>{LABEL[m]}</th>" for m in ALL_METRICS) + "</tr></thead><tbody>")
    bt = hyb["by_q_type"]
    for g in sorted(bt, key=lambda k: -bt[k]["hit@5"]):
        label = f'{QTYPE_VI.get(g, g)} (n={bt[g]["n"]})'
        p.append(metric_row(label, bt[g]))
    p.append("</tbody></table>")

    # ── hybrid vs vector ──
    if vec:
        p.append("<h2>Đóng góp của BM25: hybrid vs vector-only</h2>")
        p.append('<div class="legend">'
                 '<span class="dot" style="background:#0e7490"></span>hybrid &nbsp;&nbsp;'
                 '<span class="dot" style="background:#c2691a"></span>vector-only</div>')
        p.append("<table><thead><tr><th>Metric</th><th>Hybrid</th><th>Vector-only</th>"
                 "<th>Δ (BM25 đóng góp)</th></tr></thead><tbody>")
        for m in ALL_METRICS:
            a, b = hyb["overall"][m], vec["overall"][m]
            d = a - b
            sign = "+" if d >= 0 else ""
            col = "#15803d" if d > 0.002 else ("#b91c1c" if d < -0.002 else "#64748b")
            p.append(f"<tr><th>{LABEL[m]}</th><td>{bar(a,'#0e7490')}</td>"
                     f"<td>{bar(b,'#c2691a')}</td>"
                     f'<td style="color:{col};font-weight:600">{sign}{d:.3f}</td></tr>')
        p.append("</tbody></table>")

    # ── manual + gate ──
    if man or gate:
        p.append("<h2>Bộ viết tay & cổng “không tìm thấy”</h2>")
        p.append('<div class="cards">')
        if man:
            p.append(card(f'Hit@5 viết tay (n={man["n"]})', man["overall"]["hit@5"],
                          "good" if man["overall"]["hit@5"] >= 0.9 else "warn"))
            p.append(card("MRR viết tay", man["overall"]["rr"]))
        if gate:
            p.append(card(f'Cổng giữ gold (in-scope, n={gate["n_inscope"]})',
                          gate["gate_recall_inscope"],
                          "good" if gate["gate_recall_inscope"] >= 0.9 else "warn"))
            p.append(card(f'Cổng từ chối đúng (ngoài phạm vi, n={gate["n_out_of_scope"]})',
                          gate["oos_rejection_rate"],
                          "good" if gate["oos_rejection_rate"] >= 0.9 else "warn"))
        p.append("</div>")
        if gate:
            p.append(f'<p class="sub">Trung bình {gate["avg_docs_passed_oos"]:.2f} tài liệu '
                     "lọt cổng khi hỏi ngoài phạm vi (lý tưởng = 0).</p>")

    # ── câu lỗi ──
    if fails:
        p.append(f"<h2>Câu trượt top-5 (hybrid tự sinh) — {len(fails)} câu</h2>")
        p.append("<table class='fail'><thead><tr><th>ID</th><th>Nhóm</th>"
                 "<th>Lĩnh vực</th><th>Mã gold</th><th>Câu hỏi</th></tr></thead><tbody>")
        for r in fails[:40]:
            p.append("<tr><td>{id}</td><td>{q}</td><td>{lv}</td><td>{ma}</td>"
                     "<td>{qt}</td></tr>".format(
                         id=html.escape(r["id"]),
                         q=html.escape(QTYPE_VI.get(r["q_type"], r["q_type"])),
                         lv=html.escape(r["linh_vuc"]),
                         ma=html.escape(r["primary_ma_thu_tuc"] or "-"),
                         qt=html.escape(r["question"][:90])))
        p.append("</tbody></table>")

    p.append('<p class="sub" style="margin-top:40px">Sinh tự động bởi '
             '<code>rag/eval/make_report.py</code>. Số liệu từ các file '
             '<code>data/eval/*summary*.json</code>.</p>')
    p.append("</div>")

    OUT.write_text("\n".join(p), encoding="utf-8")
    print(f"Đã ghi báo cáo: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
