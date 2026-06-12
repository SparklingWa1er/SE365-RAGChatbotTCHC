# Frontend (UI React) — cài đặt, chạy & hợp đồng API

> UI React mới = **demo chính** của dự án (Gradio chỉ là phụ). Stack: **Vite 5 +
> React 19 + TypeScript + Tailwind 4** (đã có sẵn `package.json`, `vite.config.ts`,
> `src/`). Backend là tầng FastAPI mỏng ở `app/api/` (xem mã nguồn + Swagger
> `http://127.0.0.1:8000/docs`). Tài liệu này tự chứa cách cài/chạy + "hợp đồng"
> API & SSE để FE cắm vào backend.

## 0. Yêu cầu & cài đặt

- **Node.js ≥ 20** kèm `npm` (đã test Node 22 / npm 10).

```powershell
cd frontend
npm install        # tải node_modules (chỉ lần đầu / khi đổi package.json)
```

## 1. Chạy backend trước

```powershell
# từ gốc repo, dùng venv của dự án
.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
# Swagger UI để thử endpoint: http://127.0.0.1:8000/docs
```

API gốc: `http://127.0.0.1:8000/api`. CORS đã mở cho `http://localhost:5173` và
`http://127.0.0.1:5173` (cổng mặc định của Vite) — xem `app/api/main.py` nếu cần thêm origin.

## 2. Chạy frontend (terminal thứ 2)

```powershell
cd frontend
npm run dev        # dev server → http://127.0.0.1:5173
```

Mở **http://127.0.0.1:5173**. `vite.config.ts` đã cấu hình **proxy `/api` →
`http://127.0.0.1:8000`** nên không lo CORS, không hardcode host. **Chạy backend
(mục 1) trước** rồi mới tới frontend.

**Host LAN (build tĩnh + preview):**

```powershell
npm run build      # → frontend/dist/
npm run preview    # host:true, port 4173, có proxy /api riêng → http://<IP-máy>:4173
```

> Backend (`uvicorn`, mục 1) phải chạy song song trong cả 2 chế độ dev và preview.
> Sau khi ingest lại corpus → **restart uvicorn** để nạp lại vector store.

### Bố trí thư mục `src/`

```
frontend/
  package.json, vite.config.ts, tsconfig*.json, components.json
  src/
    api/        # client gọi /api + parser SSE (xem mục 4)
    components/ # ChatPanel, MessageList, Sidebar hội thoại, CitationsPanel...
    pages/      # Chat
```

## 3. Endpoint (tóm tắt — schema đầy đủ ở Swagger `:8000/docs`)

| Method | Path | Dùng để |
|---|---|---|
| POST | `/api/chat` | Gửi tin nhắn, nhận **SSE stream** (xem mục 4). Tạo hội thoại nếu thiếu id. |
| POST | `/api/chat/{id}/regen` | Trả lời lại lượt cuối (SSE). |
| POST | `/api/chat/stop` | Dừng stream `{conversation_id}`. |
| GET | `/api/conversations` | Danh sách hội thoại. |
| POST | `/api/conversations` | Tạo mới. |
| GET | `/api/conversations/{id}` | Messages + suggestions + selected. |
| PATCH | `/api/conversations/{id}` | Đổi tên / is_public. |
| DELETE | `/api/conversations/{id}` | Xoá. |
| GET | `/api/suggestions/default` | Câu gợi ý mặc định (tiếng Việt). |
| POST | `/api/conversations/{id}/suggestions` | Sinh follow-up theo lịch sử. |
| GET | `/api/settings/schema` | Engine + option để render form Settings. |
| GET / PUT | `/api/settings` | Đọc / lưu setting (override). |
| GET | `/api/indices` | Danh sách index. |
| GET | `/api/indices/{id}/files` | File để lọc phạm vi tra cứu. |
| GET | `/api/health`, `/api/config` | Trạng thái + cờ feature. |

### Body `POST /api/chat`
```json
{
  "conversation_id": "abc",          // null = tạo mới (đọc id ở header X-Conversation-Id)
  "message": "Lệ phí cấp hộ chiếu?",
  "settings_override": {             // optional
    "reasoning_type": "ReAct",      // "ReAct" | "simple" | "complex" | "ReWOO"
    "llm": "", "language": "vi",
    "use_mindmap": true, "use_citation": "inline"
  },
  "selected_file_ids": []           // [] = search toàn bộ corpus
}
```
Header trả về: `X-Conversation-Id` (dùng cho các lượt sau cùng hội thoại).

## 4. Hợp đồng SSE (quan trọng nhất)

Response của `/api/chat` và `/regen` là `text/event-stream`. Mỗi dòng: `data: <json>\n\n`.
Các loại event (`type`):

| type | payload | Ý nghĩa / cách render |
|---|---|---|
| `answer.reset` | — | Xoá text đang hiển thị (chuẩn bị render lại, vd sau khi chèn link citation). |
| `answer` | `{ text }` | **Text ĐẦY ĐỦ hiện tại** (không phải delta) — cứ ghi đè vùng câu trả lời. Có HTML `<a class='citation'>【n】</a>`. |
| `info` | `{ html }` | HTML panel: bước reasoning (Thought/Action) + nguồn có tô sáng. Render bằng `dangerouslySetInnerHTML`. Cũng là **đầy đủ tích luỹ**. |
| `plot` | `{ spec }` | JSON Plotly (nếu bật citation viz). Render bằng react-plotly nếu cần. |
| `citations` | `{ items: [...] }` | **Nguồn có cấu trúc** (xem dưới) — ưu tiên dùng cho danh sách nguồn. |
| `done` | `{ conversation_id, suggestions, cancelled? }` | Kết thúc. `suggestions`: `[["câu 1"],["câu 2"],...]`. `cancelled:true` nếu bị dừng. |

`citations.items[]`:
```ts
{
  indices: number[],   // số 【n】 trỏ về nguồn này
  title: string,       // tên thủ tục (hoặc nhãn 🌐 ... · web)
  snippet: string,     // đoạn được trích (đã ghép các span)
  score: number|null,  // llm_trulens_score
  is_web: boolean,     // true = nguồn web (Brave), chưa thẩm định
  url: string|null     // link nếu là nguồn web
}
```

> Lưu ý: `answer` và `info` gửi **toàn bộ trạng thái mỗi lần** (đã tích luỹ ở backend),
> nên client chỉ cần GHI ĐÈ, không tự nối chuỗi. Dùng `EventSource` không gửi được body
> POST → dùng `fetch` + đọc `ReadableStream` rồi tự tách theo `\n\n`, hoặc thư viện như
> `@microsoft/fetch-event-source`.

## 5. Trạng thái & ghi chú deploy

UI React đã code xong phần lõi: client `api/` (`streamChat()` fetch + parse SSE theo mục 4
+ các hàm REST), sidebar hội thoại, khung chat (render `answer` + citation link), panel
nguồn (event `citations`), ô gợi ý (`done.suggestions`), nút regen/stop, trang Settings
(`/api/settings/schema`).

Deploy demo: chạy `uvicorn` (backend) + `npm run dev` (dev) hoặc `npm run build && npm run
preview` (LAN) như mục 1–2. Bản tĩnh nằm ở `frontend/dist/` — có thể cho web server bất kỳ
serve, miễn proxy `/api` về backend FastAPI.
