"""Ablation đánh giá HIỆU QUẢ memory của agent (rag/memory.py).

Đo trực tiếp trên BƯỚC CONTEXTUALIZE — nơi memory phát huy tác dụng: viết lại câu
hỏi follow-up (có tham chiếu ngầm) thành câu hỏi ĐỘC LẬP để retrieve đúng. Một câu
được coi là ĐÚNG nếu chứa thực thể kỳ vọng (tên thủ tục/địa phương...) sau khi viết
lại. So sánh có/không từng lớp → cho ra con số định lượng cho báo cáo.

Hai benchmark tách bạch theo lớp:
  B1 · Lớp A (Summary-Buffer): tham chiếu nằm Ở LƯỢT CŨ, ngoài cửa sổ n_last lượt gần
       nhất. Baseline (chỉ cửa sổ ngắn) sẽ mất ngữ cảnh; +summary giữ lại được.
  B2 · Lớp B (Episodic): bối cảnh nằm ở HỘI THOẠI TRƯỚC (history hiện tại rỗng).
       Không episodic thì không thể giải; +episodic recall lại được từ kho ký ức.

Chạy (từ gốc repo, cần Azure trong .env):
  .venv\\Scripts\\python.exe rag\\eval\\eval_memory.py
Output: data/eval/exp03_memory/memory_ablation.json (+ bảng in ra màn hình).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unicodedata
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))
sys.path.insert(0, str(_HERE))

import flowsettings  # noqa: E402,F401  (theflow nạp file-based)
from ktem.main import App  # noqa: E402
from ktem.embeddings.manager import embedding_models_manager as embeddings  # noqa: E402
from ktem.llms.manager import llms  # noqa: E402
from ktem.reasoning.react import ContextualizeQuestionPipeline  # noqa: E402

from rag.memory import EpisodicMemory, MemoryManager  # noqa: E402

OUT_DIR = ROOT / "data" / "eval" / "exp03_memory"
OUT_JSON = OUT_DIR / "memory_ablation.json"

# Cửa sổ lịch sử ngắn để MÔ PHỎNG giới hạn buffer (entity ở lượt 1 sẽ rơi ra ngoài).
WINDOW = 2
KEEP_RECENT = 2


def _norm(s: str) -> str:
    """Bỏ dấu + thường hoá để so khớp thực thể không phụ thuộc dấu/hoa-thường."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


def _hit(text: str, expected: list[str]) -> bool:
    t = _norm(text)
    return any(_norm(e) in t for e in expected)


# ─────────────────────────── Bộ dữ liệu B1 (Lớp A) ──────────────────────────
# Mỗi case: lịch sử nhiều lượt (thực thể chính ở LƯỢT ĐẦU), rồi follow-up tham chiếu
# ngầm. `expected` = các biến thể từ khoá mà câu viết lại ĐÚNG phải chứa.
B1_CASES = [
    {
        "history": [
            ("Hồ sơ xin cấp hộ chiếu phổ thông gồm những gì?",
             "Cần tờ khai, ảnh, CCCD..."),
            ("Tờ khai lấy ở đâu?", "Tải trên Cổng dịch vụ công hoặc tại cơ quan."),
            ("Ảnh cần kích thước bao nhiêu?", "Ảnh 4x6 nền trắng."),
        ],
        "follow_up": "Thế lệ phí của thủ tục này là bao nhiêu?",
        "expected": ["hộ chiếu"],
    },
    {
        "history": [
            ("Thủ tục đăng ký kết hôn cần giấy tờ gì?",
             "Tờ khai đăng ký kết hôn, giấy xác nhận tình trạng hôn nhân..."),
            ("Nộp ở đâu?", "UBND cấp xã nơi cư trú."),
            ("Có cần đặt lịch hẹn trước không?", "Tuỳ địa phương, nên đặt trước."),
        ],
        "follow_up": "Cơ quan nào có thẩm quyền giải quyết việc đó?",
        "expected": ["kết hôn"],
    },
    {
        "history": [
            ("Cấp giấy phép xây dựng nhà ở riêng lẻ cần hồ sơ gì?",
             "Đơn đề nghị, giấy tờ đất, bản vẽ thiết kế..."),
            ("Bản vẽ do ai lập?", "Đơn vị có chứng chỉ hành nghề."),
            ("Nộp bản giấy hay online?", "Có thể nộp trực tuyến."),
        ],
        "follow_up": "Thời hạn giải quyết thủ tục đó là bao lâu?",
        "expected": ["giấy phép xây dựng", "xây dựng"],
    },
    {
        "history": [
            ("Đăng ký thường trú cho con mới sinh làm thế nào?",
             "Cần giấy khai sinh, sổ hộ khẩu/giấy tờ cư trú..."),
            ("Làm khai sinh trước hay thường trú trước?", "Khai sinh trước."),
            ("Khai sinh nộp ở đâu?", "UBND cấp xã."),
        ],
        "follow_up": "Vậy hồ sơ của việc đăng ký kia gồm những gì?",
        "expected": ["thường trú"],
    },
]

# ─────────────────────────── Bộ dữ liệu B2 (Lớp B) ──────────────────────────
# `past` = các lượt ở HỘI THOẠI TRƯỚC (sẽ observe vào kho ký ức). `follow_up` hỏi ở
# hội thoại MỚI (history rỗng), tham chiếu ngầm bối cảnh cũ.
B2_CASES = [
    {
        "past": [
            ("Tôi đang làm thủ tục cấp hộ chiếu lần đầu ở Đà Nẵng",
             "Bạn cần chuẩn bị CCCD và tờ khai..."),
        ],
        "follow_up": "Khi đến nộp thì cần mang theo những gì?",
        "expected": ["hộ chiếu"],
    },
    {
        "past": [
            ("Tôi muốn đăng ký kinh doanh hộ cá thể bán cà phê",
             "Hộ kinh doanh cần giấy đề nghị đăng ký..."),
        ],
        "follow_up": "Lệ phí đăng ký là bao nhiêu?",
        "expected": ["kinh doanh", "hộ cá thể", "hộ kinh doanh"],
    },
    {
        "past": [
            ("Tôi cần làm thủ tục cấp đổi giấy phép lái xe ô tô hạng B2",
             "Bạn cần đơn, giấy khám sức khoẻ, GPLX cũ..."),
        ],
        "follow_up": "Hồ sơ gồm những giấy tờ nào?",
        "expected": ["giấy phép lái xe", "lái xe", "gplx"],
    },
]


def make_ctx(llm):
    ctx = ContextualizeQuestionPipeline()
    ctx.llm = llm
    ctx.lang = "Vietnamese"
    ctx.n_last_interactions = WINDOW
    return ctx


def standalone(ctx, question, history, extra_context=""):
    return (ctx(question=question, history=history, extra_context=extra_context).text or "").strip()


def run_b1(ctx, mgr_summary):
    """Lớp A: baseline (cửa sổ ngắn) vs +summary."""
    rows = []
    base_hits = summ_hits = 0
    for c in B1_CASES:
        base = standalone(ctx, c["follow_up"], c["history"], "")
        summary = mgr_summary.summarize(c["history"])
        extra = mgr_summary.build_extra_context(summary, [])
        withs = standalone(ctx, c["follow_up"], c["history"], extra)
        bh, sh = _hit(base, c["expected"]), _hit(withs, c["expected"])
        base_hits += bh
        summ_hits += sh
        rows.append({"follow_up": c["follow_up"], "expected": c["expected"],
                     "baseline": base, "baseline_hit": bh,
                     "with_summary": withs, "with_summary_hit": sh})
    n = len(B1_CASES)
    return {"n": n, "baseline_acc": base_hits / n, "summary_acc": summ_hits / n,
            "rows": rows}


def run_b2(ctx, llm, embedding):
    """Lớp B: no-episodic vs +episodic (recall xuyên hội thoại)."""
    tmp = tempfile.mkdtemp(prefix="memeval_")
    store = EpisodicMemory(embedding, tmp)
    mgr = MemoryManager(llm, "Vietnamese", episodic=store,
                        enable_summary=False, keep_recent=KEEP_RECENT, recall_k=3)
    rows = []
    base_hits = epi_hits = 0
    for i, c in enumerate(B2_CASES):
        user = f"evaluser{i}"  # mỗi case một user để cách ly
        for q, a in c["past"]:
            mgr.observe(user, "past_conv", q, a)
        # hội thoại MỚI: history rỗng
        base = standalone(ctx, c["follow_up"], [], "")
        recalled = mgr.recall(user, c["follow_up"], conv_id="new_conv")
        extra = mgr.build_extra_context("", recalled)
        withe = standalone(ctx, c["follow_up"], [], extra)
        bh, eh = _hit(base, c["expected"]), _hit(withe, c["expected"])
        base_hits += bh
        epi_hits += eh
        rows.append({"follow_up": c["follow_up"], "expected": c["expected"],
                     "recalled": recalled,
                     "baseline": base, "baseline_hit": bh,
                     "with_episodic": withe, "with_episodic_hit": eh})
    n = len(B2_CASES)
    return {"n": n, "baseline_acc": base_hits / n, "episodic_acc": epi_hits / n,
            "rows": rows}


def _print_block(title, rows, key_with, label_with):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    for r in rows:
        print(f"\n• Follow-up : {r['follow_up']}")
        print(f"  kỳ vọng   : {r['expected']}")
        if "recalled" in r:
            print(f"  recalled  : {r['recalled']}")
        print(f"  baseline  : [{'✓' if r['baseline_hit'] else '✗'}] {r['baseline']}")
        print(f"  {label_with:<9} : [{'✓' if r[key_with+'_hit'] else '✗'}] {r[key_with]}")


def main() -> int:
    print("Khởi tạo kotaemon (App)...")
    App()  # nạp embedding/LLM manager từ sql.db + .env
    llm = llms.get_default()
    embedding = embeddings.get_default()

    ctx = make_ctx(llm)
    mgr_summary = MemoryManager(llm, "Vietnamese", episodic=None,
                                enable_summary=True, keep_recent=KEEP_RECENT)

    print(f"\nĐang chạy ablation (WINDOW={WINDOW} lượt gần nhất)...")
    b1 = run_b1(ctx, mgr_summary)
    b2 = run_b2(ctx, llm, embedding)

    _print_block("B1 · Lớp A (Summary-Buffer) — tham chiếu ở lượt CŨ (ngoài cửa sổ)",
                 b1["rows"], "with_summary", "+summary")
    _print_block("B2 · Lớp B (Episodic) — bối cảnh ở HỘI THOẠI TRƯỚC",
                 b2["rows"], "with_episodic", "+episodic")

    print("\n" + "#" * 78)
    print("TỔNG KẾT — độ chính xác giải tham chiếu (càng cao càng tốt)")
    print("#" * 78)
    print(f"B1 Lớp A: baseline = {b1['baseline_acc']:.0%}  →  +summary  = {b1['summary_acc']:.0%}  (n={b1['n']})")
    print(f"B2 Lớp B: baseline = {b2['baseline_acc']:.0%}  →  +episodic = {b2['episodic_acc']:.0%}  (n={b2['n']})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps({"config": {"window": WINDOW, "keep_recent": KEEP_RECENT},
                    "B1_summary": b1, "B2_episodic": b2},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nĐã lưu: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
