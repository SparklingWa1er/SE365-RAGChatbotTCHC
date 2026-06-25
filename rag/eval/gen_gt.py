"""Sinh bộ Ground Truth đánh giá tầng RETRIEVAL từ corpus (tự động bằng Azure gpt-4o).

Mỗi câu hỏi gắn với MỘT thủ tục gốc (gold). Khóa khớp = `ma_thu_tuc`; các thủ tục
TRÙNG TÊN được gộp thành gold-set (cùng tên, khác cấp → đều chấp nhận).

6 NHÓM QUERY (để phân tích lỗi theo nhóm — xem README mục đánh giá):
  factual_lookup   — dùng đúng thuật ngữ trong văn bản (kiểm BM25/lexical)
  paraphrase       — diễn giải lời dân thường, cấm jargon (kiểm embedding/semantic)
  scenario         — câu tình huống gián tiếp, không nêu thẳng tên thủ tục
  aspect_hoso      — hỏi riêng thành phần hồ sơ
  aspect_phi_dk    — hỏi phí/lệ phí hoặc điều kiện
  keyword_short    — truy vấn ngắn 3-6 từ kiểu ô tìm kiếm

Chạy (từ gốc repo):
  .venv\\Scripts\\python.exe rag\\eval\\gen_gt.py                 # 180 câu (30/nhóm)
  .venv\\Scripts\\python.exe rag\\eval\\gen_gt.py --per-type 5    # thử nhanh 30 câu
  .venv\\Scripts\\python.exe rag\\eval\\gen_gt.py --reset         # xóa file cũ, sinh lại

Resumable: chạy lại sẽ BỎ QUA các (procedure, q_type) đã có trong file out.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "rag"))

import flowsettings  # noqa: E402
from kotaemon.llms import AzureChatOpenAI  # noqa: E402

CORPUS = ROOT / "data" / "corpus"
OUT = ROOT / "data" / "eval" / "exp01_retrieval" / "retrieval_gt.jsonl"
SEED = 20260624

# ── Prompt theo từng nhóm. Trả về DUY NHẤT câu hỏi (không tiền tố/giải thích). ──
SYSTEM = (
    "Bạn tạo dữ liệu kiểm thử cho hệ thống tìm kiếm thủ tục hành chính công Việt Nam. "
    "Chỉ in ra DUY NHẤT câu truy vấn, bằng tiếng Việt, không thêm lời dẫn, không giải "
    "thích, không dấu ngoặc kép."
)


# Mỗi hàm prompt nhận (p: dict thủ tục, section: str, text: str) -> nội dung prompt.
def p_factual(p, section, text):
    return (
        f"Đoạn tài liệu sau thuộc thủ tục '{p['ten']}' (lĩnh vực {p['linh_vuc']}), "
        f"phần '{section}':\n---\n{text[:1500]}\n---\n"
        "Đặt MỘT câu hỏi mà người dân có thể hỏi và được trả lời TRỰC TIẾP bởi đoạn trên. "
        "Được phép dùng thuật ngữ hành chính xuất hiện trong đoạn."
    )


def p_paraphrase(p, section, text):
    return (
        f"Thủ tục: '{p['ten']}' (lĩnh vực {p['linh_vuc']}).\n"
        "Viết MỘT câu hỏi tự nhiên bằng lời người dân bình thường về thủ tục này. "
        "TUYỆT ĐỐI không lặp lại nguyên văn tên thủ tục, dùng từ ngữ đời thường, "
        "tránh thuật ngữ hành chính và tên văn bản pháp luật."
    )


def p_scenario(p, section, text):
    dt = ", ".join(p["doi_tuong"]) if p["doi_tuong"] else "người dân"
    return (
        f"Thủ tục: '{p['ten']}' (lĩnh vực {p['linh_vuc']}; đối tượng: {dt}).\n"
        "Viết MỘT câu hỏi dạng TÌNH HUỐNG ngôi thứ nhất ('Tôi...' / 'Mình...') mô tả "
        "hoàn cảnh thực tế dẫn đến nhu cầu làm thủ tục này, rồi hỏi phải làm gì. "
        "KHÔNG nêu thẳng tên thủ tục."
    )


def p_hoso(p, section, text):
    return (
        f"Thủ tục: '{p['ten']}' (lĩnh vực {p['linh_vuc']}). Thành phần hồ sơ thực tế:\n"
        f"---\n{text[:1200]}\n---\n"
        "Viết MỘT câu hỏi tự nhiên, ngắn gọn HỎI RIÊNG về giấy tờ / thành phần hồ sơ "
        "cần chuẩn bị cho thủ tục này."
    )


def p_phi_dk(p, section, text):
    khia = "lệ phí" if "phí" in section.lower() else "điều kiện"
    return (
        f"Thủ tục: '{p['ten']}' (lĩnh vực {p['linh_vuc']}). Phần '{section}':\n"
        f"---\n{text[:1200]}\n---\n"
        f"Viết MỘT câu hỏi tự nhiên HỎI RIÊNG về {khia} của thủ tục này."
    )


def p_keyword(p, section, text):
    return (
        f"Thủ tục: '{p['ten']}' (lĩnh vực {p['linh_vuc']}).\n"
        "Viết MỘT truy vấn tìm kiếm RẤT NGẮN (3-6 từ) như người dùng gõ vào ô tìm kiếm "
        "để tìm thủ tục này. Chỉ từ khóa, KHÔNG thành câu, KHÔNG dấu hỏi."
    )


# (tên nhóm, hàm prompt, section bắt buộc phải có — None = section bất kỳ có nội dung)
QUERY_TYPES = [
    ("factual_lookup", p_factual, ["Trình tự thực hiện", "Cách thức thực hiện",
                                   "Yêu cầu, điều kiện thực hiện"]),
    ("paraphrase", p_paraphrase, None),
    ("scenario", p_scenario, None),
    ("aspect_hoso", p_hoso, ["Thành phần hồ sơ"]),
    ("aspect_phi_dk", p_phi_dk, ["Phí, lệ phí", "Yêu cầu, điều kiện thực hiện"]),
    ("keyword_short", p_keyword, None),
]


def load_corpus():
    """Trả (procs, name_to_codes). procs[id] = {meta..., sections: {sec: text}}."""
    procs: dict[str, dict] = {}
    for line in open(CORPUS / "metadata.jsonl", encoding="utf-8"):
        r = json.loads(line)
        procs[r["id"]] = {
            "ma_thu_tuc": r["ma_thu_tuc"],
            "ten": r["ten"],
            "linh_vuc": (r.get("linh_vuc") or ["(không rõ)"])[0],
            "doi_tuong": r.get("doi_tuong") or [],
            "sections": {},
        }
    for line in open(CORPUS / "chunks.jsonl", encoding="utf-8"):
        r = json.loads(line)
        p = procs.get(r["doc_id"])
        if p is None:
            continue
        sec = r["section"]
        # nối nhiều chunk cùng section; bỏ tiền tố [Tên — Phần] ở đầu text
        body = r["text"].split("]\n", 1)[-1] if r["text"].startswith("[") else r["text"]
        p["sections"][sec] = (p["sections"].get(sec, "") + "\n" + body).strip()

    name_to_codes: dict[str, list[str]] = collections.defaultdict(list)
    for p in procs.values():
        name_to_codes[p["ten"]].append(p["ma_thu_tuc"])
    return procs, name_to_codes


def pick_section(p, allowed):
    """Chọn section phù hợp (có nội dung đủ dài). allowed=None => section dài nhất."""
    secs = p["sections"]
    cands = allowed if allowed else list(secs.keys())
    best, best_len = None, 0
    for s in cands:
        t = secs.get(s, "")
        if len(t) > best_len and len(t) >= 40:
            best, best_len = s, len(t)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=30, help="số câu mỗi nhóm")
    ap.add_argument("--reset", action="store_true", help="xóa file GT cũ trước khi sinh")
    args = ap.parse_args()

    if args.reset and OUT.exists():
        OUT.unlink()

    done: set[tuple[str, str]] = set()
    if OUT.exists():
        for line in open(OUT, encoding="utf-8"):
            r = json.loads(line)
            done.add((r["procedure_id"], r["q_type"]))
        print(f"Đã có {len(done)} câu — sẽ bỏ qua các (thủ tục, nhóm) trùng.")

    print("Nạp corpus...")
    procs, name_to_codes = load_corpus()
    ids = list(procs.keys())

    spec = flowsettings.KH_LLMS["azure"]["spec"].copy()
    spec.pop("__type__")
    llm = AzureChatOpenAI(**spec)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_f = open(OUT, "a", encoding="utf-8")
    n_new = 0

    for q_type, prompt_fn, allowed in QUERY_TYPES:
        rng = random.Random(f"{SEED}-{q_type}")  # mỗi nhóm seed riêng -> ổn định
        shuffled = ids[:]
        rng.shuffle(shuffled)
        made = sum(1 for d in done if d[1] == q_type)
        i = 0
        while made < args.per_type and i < len(shuffled):
            pid = shuffled[i]; i += 1
            if (pid, q_type) in done:
                continue
            p = procs[pid]
            section = pick_section(p, allowed)
            if section is None:
                continue
            text = p["sections"].get(section, "")
            prompt = f"{SYSTEM}\n\n" + prompt_fn(p, section, text)
            try:
                q = llm(prompt).text.strip().strip('"').strip()
            except Exception as e:  # noqa: BLE001
                print(f"  [lỗi LLM] {e}; nghỉ 5s rồi thử thủ tục khác")
                time.sleep(5)
                continue
            if not q or len(q) < 4:
                continue
            gold = sorted(set(name_to_codes[p["ten"]]))
            rec = {
                "id": f"{q_type}-{made:03d}",
                "procedure_id": pid,
                "q_type": q_type,
                "question": q,
                "gold_ma_thu_tuc": gold,
                "primary_ma_thu_tuc": p["ma_thu_tuc"],
                "ten": p["ten"],
                "linh_vuc": p["linh_vuc"],
                "source_section": section,
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            done.add((pid, q_type))
            made += 1; n_new += 1
            print(f"  [{q_type} {made}/{args.per_type}] {q[:70]}")

    out_f.close()
    total = sum(1 for _ in open(OUT, encoding="utf-8"))
    print(f"\nXong. +{n_new} câu mới. Tổng GT: {total} câu -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
