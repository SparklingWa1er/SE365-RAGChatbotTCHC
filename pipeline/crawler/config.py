"""Cấu hình crawler cho Cổng Dịch vụ công Quốc gia (dichvucong.gov.vn).

Tất cả endpoint dưới đây được phát hiện bằng cách phân tích bundle JS của SPA
(reverse-engineer phần network layer), đã verify chạy thật ngày 2026-06.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
BASE_URL = "https://dichvucong.gov.vn/api/v1"

# POST. Body: {limit, lastId, q, categoryId, departmentCode, ...}
# Trả về: {code:"OK", data:{items:[...], lastId, total}}  (phân trang con trỏ)
LIST_ENDPOINT = "/submitting/formality/list-all-formality-by-citizen"

# POST. Body: {"id": "<uuid>"}  -> chi tiết đầy đủ 1 thủ tục
DETAIL_ENDPOINT = "/configuring/formality/get-formality-by-citizen"

# POST -> trả về blob PDF. Body: {"id": "<uuid>"}  (tùy chọn, dùng để lưu PDF gốc)
PDF_ENDPOINT = "/configuring/formality/export-pdf-formality-detail-by-citizen"

# Header tối thiểu mà server chấp nhận (không cần token cho các API "by-citizen").
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json",
    "Origin": "https://dichvucong.gov.vn",
    "Referer": "https://dichvucong.gov.vn/tra-cuu-thu-tuc/danh-sach",
}

# ---------------------------------------------------------------------------
# Hành vi crawl
# ---------------------------------------------------------------------------
PAGE_SIZE = 50            # số item mỗi trang list (server chấp nhận tới ~50)
REQUEST_DELAY = 0.4       # giây nghỉ giữa các request (lịch sự với server)
DELAY_JITTER = 0.3        # cộng thêm ngẫu nhiên 0..JITTER giây
TIMEOUT = 40              # giây timeout mỗi request
MAX_RETRIES = 4           # số lần thử lại khi lỗi mạng/5xx
RETRY_BACKOFF = 2.0       # hệ số backoff theo cấp số nhân
DOWNLOAD_PDF = False      # True nếu muốn tải kèm PDF gốc mỗi thủ tục

# ---------------------------------------------------------------------------
# Đường dẫn lưu trữ
# ---------------------------------------------------------------------------
# pipeline/crawler/config.py -> lên 3 cấp tới gốc repo (crawler -> pipeline -> repo)
ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # data/raw/<uuid>.json  (chi tiết thô)
PDF_DIR = DATA_DIR / "pdf"          # data/pdf/<code>.pdf   (nếu DOWNLOAD_PDF)
INDEX_FILE = DATA_DIR / "index.jsonl"     # mỗi dòng = 1 item từ list
STATE_FILE = DATA_DIR / "crawl_state.json"  # trạng thái để resume
FAIL_FILE = DATA_DIR / "failures.jsonl"     # các id tải lỗi để retry sau
