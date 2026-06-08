"""Crawler thu thập toàn bộ thủ tục hành chính từ dichvucong.gov.vn.

Quy trình 2 pha:
  1) LIST  : duyệt phân trang con trỏ (lastId) -> thu thập mọi (id, code, name...)
             ghi vào data/index.jsonl
  2) DETAIL: với mỗi id, gọi API chi tiết -> lưu data/raw/<uuid>.json

Đặc tính:
  - Resume được: bỏ qua thủ tục đã có file, lưu state phân trang.
  - Lịch sự: delay + jitter giữa request, retry kèm backoff cho lỗi mạng/5xx.
  - Ghi nhận thất bại vào data/failures.jsonl để chạy lại bằng `--retry-failed`.

Cách dùng (từ thư mục pipeline/crawler/):
  python crawl.py                 # chạy đầy đủ (list nếu cần, rồi detail)
  python crawl.py --list-only     # chỉ làm mới index danh sách
  python crawl.py --limit 20      # chỉ tải 20 thủ tục đầu (smoke test)
  python crawl.py --retry-failed  # tải lại các id từng lỗi
  python crawl.py --force         # tải lại cả những file đã có
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests

import config as C


# ---------------------------------------------------------------------------
# Tiện ích
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def polite_sleep() -> None:
    time.sleep(C.REQUEST_DELAY + random.uniform(0, C.DELAY_JITTER))


def ensure_dirs() -> None:
    C.RAW_DIR.mkdir(parents=True, exist_ok=True)
    if C.DOWNLOAD_PDF:
        C.PDF_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    """Ghi JSON UTF-8 không BOM (an toàn cho mọi trình đọc)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # ghi nguyên tử, tránh file hỏng khi gián đoạn


def append_jsonl(path: Path, obj: Any) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_state() -> dict:
    if C.STATE_FILE.exists():
        return json.loads(C.STATE_FILE.read_text(encoding="utf-8"))
    return {"list_done": False, "last_id": "", "list_count": 0}


def save_state(state: dict) -> None:
    write_json(C.STATE_FILE, state)


# ---------------------------------------------------------------------------
# Lớp client gọi API có retry
# ---------------------------------------------------------------------------
class DvcClient:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update(C.HEADERS)

    def _post(self, endpoint: str, body: dict, *, blob: bool = False):
        url = C.BASE_URL + endpoint
        last_err: Exception | None = None
        for attempt in range(1, C.MAX_RETRIES + 1):
            try:
                r = self.s.post(url, json=body, timeout=C.TIMEOUT)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r.content if blob else r.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                wait = C.RETRY_BACKOFF ** (attempt - 1)
                log(f"  ! lỗi ({e}); thử lại {attempt}/{C.MAX_RETRIES} sau {wait:.1f}s")
                time.sleep(wait)
        raise RuntimeError(f"Thất bại sau {C.MAX_RETRIES} lần: {endpoint} {body}: {last_err}")

    def list_page(self, last_id: str, limit: int) -> dict:
        body = {"limit": limit, "lastId": last_id, "q": "",
                "categoryId": "", "departmentCode": ""}
        resp = self._post(C.LIST_ENDPOINT, body)
        if resp.get("code") != "OK":
            raise RuntimeError(f"List trả về code={resp.get('code')}: {resp.get('message')}")
        return resp["data"]

    def detail(self, formality_id: str) -> dict:
        resp = self._post(C.DETAIL_ENDPOINT, {"id": formality_id})
        if resp.get("code") != "OK":
            raise RuntimeError(f"Detail {formality_id} code={resp.get('code')}: {resp.get('message')}")
        return resp["data"]

    def pdf(self, formality_id: str) -> bytes:
        return self._post(C.PDF_ENDPOINT, {"id": formality_id}, blob=True)


# ---------------------------------------------------------------------------
# Pha 1: LIST
# ---------------------------------------------------------------------------
def crawl_list(client: DvcClient, state: dict) -> int:
    """Duyệt toàn bộ danh sách bằng phân trang con trỏ. Ghi nối vào index.jsonl."""
    last_id = state.get("last_id", "")
    count = state.get("list_count", 0)
    total = None
    log(f"Bắt đầu LIST (resume từ lastId={last_id!r}, đã có {count})")

    while True:
        data = client.list_page(last_id, C.PAGE_SIZE)
        items = data.get("items", [])
        total = data.get("total", total)
        if not items:
            break
        for it in items:
            append_jsonl(C.INDEX_FILE, it)
        count += len(items)
        last_id = data.get("lastId") or items[-1].get("id", "")
        state.update(last_id=last_id, list_count=count)
        save_state(state)
        log(f"  LIST: {count}/{total} (lastId={last_id})")
        # con trỏ không đổi hoặc trang ngắn -> hết dữ liệu
        if not data.get("lastId") or len(items) < C.PAGE_SIZE:
            break
        polite_sleep()

    state["list_done"] = True
    save_state(state)
    log(f"LIST xong: {count} thủ tục (total báo cáo: {total}).")
    return count


# ---------------------------------------------------------------------------
# Pha 2: DETAIL
# ---------------------------------------------------------------------------
def iter_index() -> Iterator[dict]:
    """Đọc index.jsonl, khử trùng lặp theo id (giữ lần xuất hiện đầu)."""
    seen: set[str] = set()
    for it in read_jsonl(C.INDEX_FILE):
        fid = it.get("id")
        if fid and fid not in seen:
            seen.add(fid)
            yield it


def detail_path(formality_id: str) -> Path:
    return C.RAW_DIR / f"{formality_id}.json"


def crawl_details(client: DvcClient, *, force: bool, limit: int | None) -> None:
    items = list(iter_index())
    if limit:
        items = items[:limit]
    log(f"Bắt đầu DETAIL cho {len(items)} thủ tục (force={force}).")

    ok = skip = fail = 0
    for i, it in enumerate(items, 1):
        fid = it["id"]
        path = detail_path(fid)
        if path.exists() and not force:
            skip += 1
            continue
        try:
            data = client.detail(fid)
            write_json(path, data)
            if C.DOWNLOAD_PDF:
                code = (data.get("code") or fid).replace("/", "_")
                (C.PDF_DIR / f"{code}.pdf").write_bytes(client.pdf(fid))
            ok += 1
            if ok % 25 == 0 or i == len(items):
                log(f"  DETAIL {i}/{len(items)} | ok={ok} skip={skip} fail={fail}")
        except Exception as e:  # noqa: BLE001 - ghi nhận để retry, không dừng cả mẻ
            fail += 1
            log(f"  x LỖI {fid} ({it.get('code')}): {e}")
            append_jsonl(C.FAIL_FILE, {"id": fid, "code": it.get("code"), "error": str(e)})
        polite_sleep()

    log(f"DETAIL xong: ok={ok}, skip(đã có)={skip}, fail={fail}.")
    if fail:
        log(f"  -> {fail} mục lỗi đã ghi vào {C.FAIL_FILE.name}; chạy `--retry-failed` để thử lại.")


def retry_failed(client: DvcClient) -> None:
    if not C.FAIL_FILE.exists():
        log("Không có file thất bại để retry.")
        return
    ids = {row["id"] for row in read_jsonl(C.FAIL_FILE)}
    log(f"Retry {len(ids)} mục lỗi...")
    C.FAIL_FILE.unlink()  # xóa log cũ; mục nào vẫn lỗi sẽ được ghi lại
    ok = fail = 0
    for fid in ids:
        try:
            write_json(detail_path(fid), client.detail(fid))
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            append_jsonl(C.FAIL_FILE, {"id": fid, "error": str(e)})
        polite_sleep()
    log(f"Retry xong: ok={ok}, vẫn lỗi={fail}.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crawler thủ tục hành chính dichvucong.gov.vn")
    ap.add_argument("--list-only", action="store_true", help="Chỉ làm mới danh sách (pha LIST).")
    ap.add_argument("--detail-only", action="store_true", help="Bỏ qua LIST, chỉ tải chi tiết.")
    ap.add_argument("--retry-failed", action="store_true", help="Tải lại các id từng lỗi.")
    ap.add_argument("--force", action="store_true", help="Tải lại cả file đã tồn tại.")
    ap.add_argument("--limit", type=int, default=None, help="Giới hạn số thủ tục (smoke test).")
    ap.add_argument("--refresh-list", action="store_true",
                    help="Xóa index/state cũ và quét lại danh sách từ đầu.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    ensure_dirs()
    client = DvcClient()

    if args.retry_failed:
        retry_failed(client)
        return 0

    if args.refresh_list:
        C.INDEX_FILE.unlink(missing_ok=True)
        C.STATE_FILE.unlink(missing_ok=True)
        log("Đã xóa index/state cũ.")

    state = load_state()
    if not args.detail_only and (not state.get("list_done") or args.list_only or args.refresh_list):
        crawl_list(client, state)
    elif args.detail_only:
        log(f"--detail-only: bỏ qua LIST (index hiện có {state.get('list_count')} mục).")
    else:
        log(f"LIST đã hoàn tất trước đó ({state.get('list_count')} mục). Dùng --refresh-list để quét lại.")

    if not args.list_only:
        crawl_details(client, force=args.force, limit=args.limit)

    log("HOÀN TẤT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
