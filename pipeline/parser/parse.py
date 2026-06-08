"""Parser: data/raw/<uuid>.json  ->  corpus Markdown + chunks cho kotaemon.

Mỗi thủ tục hành chính được render thành 1 file Markdown tự chứa, gồm:
  - Frontmatter YAML (metadata: mã, lĩnh vực, cấp, cơ quan, đối tượng...) để lọc/RAG
  - Các section sạch: Trình tự, Cách thức, Thành phần hồ sơ, Điều kiện,
    Căn cứ pháp lý, Kết quả.

Ngoài ra xuất `chunks.jsonl` (mỗi dòng = 1 section kèm metadata) cho trường hợp
muốn tự kiểm soát chunking thay vì để kotaemon tự cắt.

Chạy:
  python parse.py                 # parse toàn bộ data/raw/*.json
  python parse.py --limit 20      # thử 20 file
  python parse.py --out ../data/corpus
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# pipeline/parser/parse.py -> lên 3 cấp tới gốc repo (parser -> pipeline -> repo)
ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data" / "raw"
INDEX_FILE = ROOT / "data" / "index.jsonl"
DEFAULT_OUT = ROOT / "data" / "corpus"
DETAIL_URL = "https://dichvucong.gov.vn/thu-tuc-hanh-chinh/{id}"

# --- Ánh xạ enum sang tiếng Việt -------------------------------------------
SUBMISSION = {"DIRECT": "Trực tiếp", "ONLINE": "Trực tuyến", "POSTAL": "Qua bưu điện"}
TIME_UNIT = {
    "WORKING_DAY": "ngày làm việc", "DAY": "ngày", "MONTH": "tháng",
    "HOUR": "giờ", "YEAR": "năm", "OTHER": "",
}
FORMALITY_TYPE = {
    "STANDARD": "Thủ tục chuẩn",
    "STANDARD_INTERNAL": "Thủ tục nội bộ",
    "SPECIFIC": "Thủ tục đặc thù",
}
LEVEL_FLAGS = [
    ("isWard", "Xã/Phường"), ("isProvince", "Tỉnh/Thành phố"),
    ("isMinistry", "Bộ/Trung ương"), ("isOtherAgency", "Cơ quan khác"),
    ("isVertical", "Ngành dọc"),
]


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def load_index() -> dict[str, dict]:
    """Map id -> item danh sách (bổ sung metadata khi detail để trống)."""
    idx: dict[str, dict] = {}
    if INDEX_FILE.exists():
        for line in INDEX_FILE.open(encoding="utf-8"):
            line = line.strip()
            if line:
                it = json.loads(line)
                if it.get("id"):
                    idx[it["id"]] = it
    return idx


def clean(text: Any) -> str:
    """Chuẩn hóa khoảng trắng, bỏ ký tự điều khiển, giữ xuống dòng có ý nghĩa."""
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def yaml_escape(s: str) -> str:
    s = (s or "").replace('"', "'").replace("\n", " ").strip()
    return f'"{s}"'


def sanitize_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", s).strip() or "untitled"


def names(items: list[dict] | None, key: str = "name") -> list[str]:
    out = []
    for it in items or []:
        v = (it.get(key) or "").strip() if isinstance(it, dict) else str(it).strip()
        if v:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# Trích metadata (gộp detail + index)
# ---------------------------------------------------------------------------
def extract_meta(d: dict, idx_item: dict) -> dict:
    code = d.get("code") or idx_item.get("code") or ""
    linh_vuc = names(d.get("categoriesDetails")) or idx_item.get("categories") or []
    co_quan_th = names(d.get("departmentsExecuting")) or idx_item.get("departments") or []
    doi_tuong = names(d.get("formalityTargetType")) or idx_item.get("formalityTargetType") or []
    # formalityTargetType đôi khi là list[str]
    if not doi_tuong:
        ftt = d.get("formalityTargetType")
        if isinstance(ftt, list):
            doi_tuong = [x for x in ftt if isinstance(x, str) and x.strip()]
    cap = [vi for flag, vi in LEVEL_FLAGS if d.get(flag)]
    return {
        "id": d.get("id"),
        "ma_thu_tuc": code,
        "ten": clean(d.get("name") or idx_item.get("name")),
        "linh_vuc": linh_vuc,
        "cap_thuc_hien": cap,
        "co_quan_ban_hanh": clean(d.get("departmentPromulgateName")
                                  or idx_item.get("departmentPromulgate")),
        "co_quan_thuc_hien": co_quan_th,
        "doi_tuong": doi_tuong,
        "loai": FORMALITY_TYPE.get(d.get("type"), d.get("type") or ""),
        "so_quyet_dinh": clean(d.get("decisionNo")),
        "url": DETAIL_URL.format(id=d.get("id")),
    }


# ---------------------------------------------------------------------------
# Render từng section -> trả về list (tên_section, nội_dung_markdown)
# ---------------------------------------------------------------------------
def sec_trinh_tu(d: dict) -> str:
    parts = []
    for step in d.get("executionSteps") or []:
        nm = clean(step.get("name"))
        desc = clean(step.get("description"))
        if nm:
            parts.append(f"**{nm}**")
        if desc:
            parts.append(desc)
    return "\n\n".join(parts)


def fmt_fee(f: Any) -> str:
    """Chuẩn hóa 1 khoản phí -> chuỗi đọc được.

    value = 0/None -> 'Miễn phí'; có số tiền -> '<số> <đơn vị>' (đơn vị mặc định
    'đồng', dấu phân cách hàng nghìn kiểu VN). Ưu tiên name/description nếu có.
    Tránh in nguyên dict thô như '{'type': 'FEE', 'value': 0, ...}'.
    """
    if not isinstance(f, dict):
        return clean(f)
    name = clean(f.get("name"))
    desc = clean(f.get("description"))
    val = f.get("value")
    try:
        num = float(val) if val not in (None, "") else None
    except (TypeError, ValueError):
        num = None
    cur = clean(f.get("currencyId")) or "đồng"
    money = ""
    if num is not None:
        money = "Miễn phí" if num == 0 else f"{num:,.0f} {cur}".replace(",", ".")
    label = name or desc
    if label and money and money != "Miễn phí":
        return f"{label}: {money}"
    return label or money or "Không có thông tin"


def sec_cach_thuc(d: dict) -> str:
    rows = []
    for m in d.get("executionMethods") or []:
        hinh_thuc = SUBMISSION.get(m.get("submissionMethod"), m.get("submissionMethod") or "")
        t = m.get("processingTime")
        unit = TIME_UNIT.get(m.get("processingTimeUnit"), m.get("processingTimeUnit") or "")
        thoi_han = f"{t} {unit}".strip() if t not in (None, "", 0) else (clean(m.get("description")) or "—")
        fees = m.get("fees") or []
        phi = "; ".join(fmt_fee(f) for f in fees) if fees else "Không có thông tin"
        rows.append(f"| {hinh_thuc} | {thoi_han} | {phi} |")
    if not rows:
        return ""
    head = "| Hình thức nộp | Thời hạn giải quyết | Phí, lệ phí |\n|---|---|---|"
    return head + "\n" + "\n".join(rows)


def sec_ho_so(d: dict) -> str:
    rows = []
    seen = set()
    for case in (d.get("executionCases") or []) + (d.get("cases") or []):
        for pc in case.get("profileComponents") or []:
            nm = clean(pc.get("name"))
            if not nm or nm in seen:
                continue
            seen.add(nm)
            chinh = pc.get("originalQty") or 0
            sao = pc.get("copyQty") or 0
            mau = "Có" if pc.get("hasElectronicForm") else ""
            bb = "Bắt buộc" if pc.get("required") else ""
            rows.append(f"| {nm} | {chinh} | {sao} | {mau} | {bb} |")
    if not rows:
        return ""
    head = "| Tên giấy tờ | Bản chính | Bản sao | Mẫu đơn | Bắt buộc |\n|---|---|---|---|---|"
    return head + "\n" + "\n".join(rows)


def sec_dieu_kien(d: dict) -> str:
    return clean(d.get("requirementsAndConditions"))


def sec_can_cu(d: dict) -> str:
    out = []
    for lb in d.get("legalBasisesDetails") or []:
        nm = clean(lb.get("name"))
        cd = clean(lb.get("code"))
        out.append(f"- {nm}" + (f" (Mã: {cd})" if cd else ""))
    return "\n".join(out)


def sec_ket_qua(d: dict) -> str:
    out = []
    for r in d.get("resultsDetails") or []:
        nm = clean(r.get("name"))
        cd = clean(r.get("code"))
        out.append(f"- {nm}" + (f" (Mã: {cd})" if cd else ""))
    return "\n".join(out)


SECTIONS = [
    ("Trình tự thực hiện", sec_trinh_tu),
    ("Cách thức thực hiện", sec_cach_thuc),
    ("Thành phần hồ sơ", sec_ho_so),
    ("Yêu cầu, điều kiện thực hiện", sec_dieu_kien),
    ("Căn cứ pháp lý", sec_can_cu),
    ("Kết quả thực hiện", sec_ket_qua),
]


# ---------------------------------------------------------------------------
# Lắp ráp Markdown + frontmatter
# ---------------------------------------------------------------------------
def build_markdown(meta: dict, sections: list[tuple[str, str]]) -> str:
    fm = ["---"]
    fm.append(f"ma_thu_tuc: {yaml_escape(meta['ma_thu_tuc'])}")
    fm.append(f"ten: {yaml_escape(meta['ten'])}")
    fm.append(f"linh_vuc: {yaml_escape('; '.join(meta['linh_vuc']))}")
    fm.append(f"cap_thuc_hien: {yaml_escape('; '.join(meta['cap_thuc_hien']))}")
    fm.append(f"co_quan_thuc_hien: {yaml_escape('; '.join(meta['co_quan_thuc_hien']))}")
    fm.append(f"co_quan_ban_hanh: {yaml_escape(meta['co_quan_ban_hanh'])}")
    fm.append(f"doi_tuong: {yaml_escape('; '.join(meta['doi_tuong']))}")
    fm.append(f"loai: {yaml_escape(meta['loai'])}")
    fm.append(f"url: {yaml_escape(meta['url'])}")
    fm.append("---")

    body = [f"# {meta['ten']}", ""]
    info = [f"**Mã thủ tục:** {meta['ma_thu_tuc']}"]
    if meta["linh_vuc"]:
        info.append(f"**Lĩnh vực:** {'; '.join(meta['linh_vuc'])}")
    if meta["cap_thuc_hien"]:
        info.append(f"**Cấp thực hiện:** {'; '.join(meta['cap_thuc_hien'])}")
    if meta["co_quan_thuc_hien"]:
        info.append(f"**Cơ quan thực hiện:** {'; '.join(meta['co_quan_thuc_hien'])}")
    if meta["doi_tuong"]:
        info.append(f"**Đối tượng thực hiện:** {'; '.join(meta['doi_tuong'])}")
    body.append("  \n".join(info))
    body.append("")

    for title, content in sections:
        if content.strip():
            body.append(f"## {title}")
            body.append("")
            body.append(content)
            body.append("")

    return "\n".join(fm) + "\n\n" + "\n".join(body).strip() + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Parse JSON thủ tục -> Markdown corpus")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Thư mục xuất corpus")
    ap.add_argument("--limit", type=int, default=None, help="Giới hạn số file (thử nghiệm)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    md_dir = out_dir / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = out_dir / "chunks.jsonl"
    meta_path = out_dir / "metadata.jsonl"

    idx = load_index()
    files = sorted(RAW_DIR.glob("*.json"))
    if args.limit:
        files = files[: args.limit]

    n_doc = n_chunk = n_empty = 0
    with chunks_path.open("w", encoding="utf-8") as fch, \
         meta_path.open("w", encoding="utf-8") as fmeta:
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            fid = d.get("id") or f.stem
            meta = extract_meta(d, idx.get(fid, {}))
            sections = [(t, fn(d)) for t, fn in SECTIONS]
            non_empty = [(t, c) for t, c in sections if c.strip()]
            if not non_empty:
                n_empty += 1
                continue

            md = build_markdown(meta, sections)
            fname = sanitize_filename(f"{meta['ma_thu_tuc']}__{fid}") + ".md"
            (md_dir / fname).write_text(md, encoding="utf-8")

            # chunk theo section (để dùng pipeline tùy biến nếu muốn)
            for title, content in non_empty:
                rec = {
                    "doc_id": fid,
                    "ma_thu_tuc": meta["ma_thu_tuc"],
                    "ten": meta["ten"],
                    "section": title,
                    "text": f"[{meta['ten']} — {title}]\n{content}",
                    "metadata": {k: meta[k] for k in
                                 ("ma_thu_tuc", "linh_vuc", "cap_thuc_hien",
                                  "co_quan_thuc_hien", "doi_tuong", "loai", "url")},
                }
                fch.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_chunk += 1

            fmeta.write(json.dumps(meta, ensure_ascii=False) + "\n")
            n_doc += 1

    print(f"Đã parse {n_doc} thủ tục -> {md_dir}")
    print(f"  Chunks (theo section): {n_chunk} -> {chunks_path}")
    print(f"  Metadata: {meta_path}")
    if n_empty:
        print(f"  Bỏ qua {n_empty} file rỗng (không có section nào).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
