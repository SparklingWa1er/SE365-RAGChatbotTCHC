# Crawler — Thủ tục hành chính (dichvucong.gov.vn)

Thu thập toàn bộ thủ tục hành chính công từ Cổng Dịch vụ công Quốc gia để làm
knowledge base cho chatbot RAG.

## Nguồn dữ liệu — API nội bộ (đã reverse-engineer + verify)

Trang `dichvucong.gov.vn` là SPA; nội dung nạp qua REST API ẩn (không công bố).
Base: `https://dichvucong.gov.vn/api/v1`, envelope `{code:"OK", data:{...}}`.

| Mục đích | Method | Endpoint | Body |
|---|---|---|---|
| Danh sách | POST | `/submitting/formality/list-all-formality-by-citizen` | `{limit,lastId,q,categoryId,departmentCode}` |
| Chi tiết | POST | `/configuring/formality/get-formality-by-citizen` | `{id:"<uuid>"}` |
| PDF gốc | POST→blob | `/configuring/formality/export-pdf-formality-detail-by-citizen` | `{id:"<uuid>"}` |

- **Phân trang con trỏ**: lặp lại với `lastId` = `data.lastId` của trang trước.
- Không cần token cho các endpoint `*-by-citizen` (public).
- Tổng: ~5208 thủ tục (06/2026).

## Cài đặt & chạy

```bash
pip install -r requirements.txt

python crawl.py                 # đầy đủ: LIST (nếu chưa xong) -> DETAIL
python crawl.py --list-only     # chỉ quét danh sách -> data/index.jsonl
python crawl.py --detail-only   # chỉ tải chi tiết theo index hiện có
python crawl.py --limit 20      # smoke test 20 thủ tục
python crawl.py --retry-failed  # tải lại các id từng lỗi
python crawl.py --force         # tải lại cả file đã có
python crawl.py --refresh-list  # quét lại danh sách từ đầu
```

Bật `DOWNLOAD_PDF = True` trong `config.py` nếu muốn lưu kèm PDF gốc.

## Đầu ra

```
data/
  index.jsonl          # mỗi dòng = 1 item danh sách (id, code, name, departments...)
  raw/<uuid>.json      # chi tiết đầy đủ 1 thủ tục (đầu vào cho bước parse/chunk)
  pdf/<code>.pdf       # PDF gốc (nếu bật DOWNLOAD_PDF)
  crawl_state.json     # trạng thái phân trang để resume
  failures.jsonl       # id tải lỗi để retry
```

## Đặc tính

- **Resume được**: bỏ qua file đã tải, lưu con trỏ phân trang.
- **Lịch sự**: delay + jitter giữa request; retry kèm backoff cho lỗi mạng/5xx.
- **Ghi nguyên tử**: file tạm `.tmp` rồi `replace`, tránh JSON hỏng khi gián đoạn.

## Các trường chính trong `raw/<uuid>.json`

`executionSteps` (trình tự), `executionMethods` (cách thức + thời hạn + phí),
`executionCases[].profileComponents` (**THÀNH PHẦN HỒ SƠ** — chú ý: nằm ở đây,
KHÔNG phải trường `profileComponents` top-level vốn luôn rỗng),
`requirementsAndConditions` (điều kiện), `legalBasisesDetails` (căn cứ pháp lý),
`resultsDetails` (kết quả), `categoriesDetails` (lĩnh vực),
`departments*`/`*Agencies` (cơ quan), `formalityTargetType` (đối tượng).

Mỗi mục hồ sơ: `name`, `code`, `originalQty` (bản chính), `copyQty` (bản sao),
`required`, `hasElectronicForm` (có mẫu đơn), `attachments`.
→ JSON đã đủ thành phần hồ sơ; **không cần tải PDF**.

→ Bước tiếp theo (parser): map các trường này thành chunk theo section + metadata
(mã, lĩnh vực, cấp thực hiện, cơ quan) cho pipeline ingest của kotaemon.
