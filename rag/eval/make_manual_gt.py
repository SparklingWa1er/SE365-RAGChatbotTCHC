"""Bộ GT VIẾT TAY: câu hỏi người thật (in-scope) + câu NGOÀI PHẠM VI (đo gate).

Khác bộ tự sinh: câu do người soạn, lời tự nhiên, đa dạng cách hỏi; gồm 10 câu
ngoài phạm vi (gold rỗng) để đo cổng "không tìm thấy" (xem eval_gate.py).

Gold (ma_thu_tuc) được gắn tay tới thủ tục dân sinh có thật trong corpus; script tự
mở rộng gold-set theo các thủ tục TRÙNG TÊN (giống bộ tự sinh).

Chạy: .venv\\Scripts\\python.exe rag\\eval\\make_manual_gt.py
Output: data/eval/retrieval_gt_manual.jsonl
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
META = ROOT / "data" / "corpus" / "metadata.jsonl"
OUT = ROOT / "data" / "eval" / "exp01_retrieval" / "retrieval_gt_manual.jsonl"

# (câu hỏi, ma_thu_tuc gold). Lời tự nhiên, đa dạng (tình huống / hỏi khía cạnh / từ khóa).
INSCOPE = [
    ("Vợ chồng tôi mới sinh em bé, giờ phải đi làm giấy khai sinh ở đâu và mang theo gì?", "1.001193"),
    ("Tụi mình chuẩn bị cưới, muốn ra phường đăng ký kết hôn thì thủ tục thế nào?", "1.000894"),
    ("Tôi mới mua nhà và chuyển sang quận khác, làm sao để nhập hộ khẩu về chỗ ở mới?", "1.004222"),
    ("Giấy tạm trú của tôi sắp hết hạn, muốn gia hạn thêm thì làm thế nào?", "1.002755"),
    ("Tôi lỡ làm mất hộ chiếu, giờ phải đi trình báo ở đâu?", "1.010386"),
    ("Thẻ căn cước của tôi bị hỏng, muốn làm lại cái mới thì sao?", "1.014064"),
    ("Trước đây gia đình quên đăng ký khai tử cho ông, giờ muốn đăng ký lại có được không?", "1.005461"),
    ("Tôi muốn mở một quán cà phê nhỏ, cần đăng ký hộ kinh doanh như thế nào?", "1.001612"),
    ("Cháu tôi mồ côi cha mẹ, tôi muốn làm người giám hộ hợp pháp thì thủ tục ra sao?", "1.004837"),
    ("Tòa đã xử cho tôi ly hôn xong, giờ cần ghi vào sổ hộ tịch thì làm gì?", "2.000698"),
    ("Hai vợ chồng tôi muốn nhận một bé trong nước làm con nuôi, thủ tục thế nào?", "2.001263"),
    ("Bằng lái xe của tôi sắp hết hạn, muốn đổi bằng mới thì làm ở đâu?", "3.000347"),
    ("Tôi muốn đăng ký xe tạm thời online trên cổng dịch vụ công thì làm thế nào?", "1.013083"),
    ("Tôi sắp đi làm xa nhà mấy tháng, có cần khai báo tạm vắng không và làm sao?", "1.003677"),
    ("Đăng ký khai sinh cho con có mất lệ phí không?", "1.001193"),
    ("Đăng ký kết hôn cần mang theo những giấy tờ gì?", "1.000894"),
    ("đăng ký hộ kinh doanh cá thể", "1.001612"),
    ("làm lại thẻ căn cước bị mất", "1.014064"),
    ("Muốn đăng ký thường trú vào nhà đang thuê thì cần điều kiện gì?", "1.004222"),
    ("đổi giấy phép lái xe quá hạn", "3.000347"),
]

# Câu NGOÀI PHẠM VI corpus thủ tục hành chính (gold rỗng -> gate nên trả "không thấy").
OUT_OF_SCOPE = [
    "Thời tiết Hà Nội ngày mai thế nào?",
    "Cách nấu phở bò ngon tại nhà?",
    "Tỉ số trận đấu của đội tuyển Việt Nam tối qua là bao nhiêu?",
    "Giá Bitcoin hôm nay là bao nhiêu?",
    "Gợi ý cho tôi một bộ phim hay để xem cuối tuần.",
    "Dịch câu 'tôi yêu Việt Nam' sang tiếng Nhật giúp tôi.",
    "Công thức tính diện tích hình tròn là gì?",
    "Quán ăn ngon gần đây ở quận 1 là ở đâu?",
    "Ai là người giàu nhất thế giới hiện nay?",
    "Làm sao để giảm cân nhanh trong một tuần?",
]


def main() -> int:
    rows = [json.loads(l) for l in open(META, encoding="utf-8")]
    by_ma = {r["ma_thu_tuc"]: r for r in rows}
    name_to_codes = collections.defaultdict(list)
    for r in rows:
        name_to_codes[r["ten"]].append(r["ma_thu_tuc"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for i, (q, ma) in enumerate(INSCOPE):
            p = by_ma.get(ma)
            if p is None:
                print(f"  [CẢNH BÁO] không thấy mã {ma} trong corpus — bỏ qua: {q[:40]}")
                continue
            gold = sorted(set(name_to_codes[p["ten"]]))
            f.write(json.dumps({
                "id": f"manual-{i:03d}",
                "q_type": "manual_inscope",
                "question": q,
                "gold_ma_thu_tuc": gold,
                "primary_ma_thu_tuc": ma,
                "ten": p["ten"],
                "linh_vuc": (p.get("linh_vuc") or ["(không rõ)"])[0],
                "source_section": "(viết tay)",
            }, ensure_ascii=False) + "\n")
            n += 1
        for i, q in enumerate(OUT_OF_SCOPE):
            f.write(json.dumps({
                "id": f"oos-{i:03d}",
                "q_type": "out_of_scope",
                "question": q,
                "gold_ma_thu_tuc": [],
                "primary_ma_thu_tuc": None,
                "ten": None,
                "linh_vuc": "(ngoài phạm vi)",
                "source_section": "(viết tay)",
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"Đã ghi {n} câu ({len(INSCOPE)} in-scope + {len(OUT_OF_SCOPE)} ngoài phạm vi) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
