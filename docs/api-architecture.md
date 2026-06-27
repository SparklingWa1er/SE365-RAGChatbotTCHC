# Kiến trúc API cho UI React

Tài liệu này mô tả tầng API (FastAPI) cho phép thay UI Gradio bằng frontend React,
**giữ nguyên toàn bộ backend RAG** (kotaemon vendored + `rag/`).

## 1. Nguyên tắc

- FastAPI **import thẳng** `ktem`/`rag` trong cùng process Python (cùng `.venv`) — không
  phải microservice. Chỉ thêm tầng API, không sửa reasoning/vector store.
- Backend hoàn toàn UI-agnostic. Điểm gọi duy nhất:
  - `reasoning_cls.get_pipeline(settings, state, retrievers)` → dựng pipeline.
  - `pipeline.stream(query, conv_id, history)` → yield `Document` có `.channel`.
- `BaseApp.__init__` (ktem/app.py) **không** dựng UI Gradio — chỉ đăng ký
  `index_manager`, `default_settings`, `reasonings`. Vì vậy ta khởi tạo `BaseApp()` một
  lần lúc startup để có đủ context (xem `app/api/context.py`).
- Chạy **từ gốc repo**, KHÔNG set `THEFLOW_SETTINGS_MODULE` (tránh vòng lặp import —
  xem CLAUDE.md). `app/api/main.py` tự chèn `sys.path` y như `app/app.py`.

```
React (Vite)  ──HTTP+SSE──►  FastAPI (app/api)  ──import──►  ktem + rag (KHÔNG sửa)
                                  │                              get_pipeline / stream
                                  ├─ routers/                    ktem DB (sql.db)
                                  ├─ adapters/  Document→JSON     vector store / LanceDB
                                  └─ context.py (BaseApp 1 lần)
```

## 2. Stream event schema (SSE)

`pipeline.stream()` yield `Document` với `channel ∈ {chat, info, plot}`. Adapter
(`app/api/adapters/stream.py`) biến mỗi Document thành **một SSE event JSON**:

| channel / loại | nội dung gốc | SSE event |
|---|---|---|
| `chat` (content=None) | reset text | `{"type":"answer.reset"}` |
| `chat` (có content) | text tích luỹ | `{"type":"answer","text":<full text hiện tại>}` |
| `info` | HTML panel (bước reasoning + nguồn) | `{"type":"info","html":<html>}` |
| `plot` | plotly JSON | `{"type":"plot","spec":<json>}` |
| `CitationsPayload` (sentinel) | citation có cấu trúc | `{"type":"citations","items":[{indices,title,snippet,score,is_web,url}]}` |
| (cuối) | — | `{"type":"done","conversation_id":...,"suggestions":[...]}` (kèm `"cancelled":true` nếu bị dừng) |

> `info` trả HTML thô (giống Gradio) để React render nhanh bằng `dangerouslySetInnerHTML`
> (các bước reasoning + panel nguồn có tô sáng). NGOÀI RA, sau khi stream xong, adapter
> phát thêm event `citations` JSON có cấu trúc — dựng từ `match_evidence_with_context()` +
> `collected_docs` (KHÔNG đụng backend). React nên ưu tiên dùng `citations` cho danh sách
> nguồn, còn `info` cho phần trình bày bước suy luận.

Định dạng SSE trên dây: mỗi event là `data: <json>\n\n`.

## 3. Danh sách endpoint

### Chat
| Method | Path | Mô tả |
|---|---|---|
| `POST` | `/api/chat` | Gửi tin nhắn, **stream SSE**. Tự tạo hội thoại nếu `conversation_id` null. |
| `POST` | `/api/chat/{id}/regen` | Trả lời lại lượt cuối (bỏ cặp cuối, chạy lại với `regen=True`). |
| `POST` | `/api/chat/stop` | Yêu cầu dừng stream của một hội thoại (cooperative, dừng giữa các event). |

Body:
```json
{
  "conversation_id": "abc",           // null = tạo mới
  "message": "Lệ phí cấp hộ chiếu?",
  "settings_override": {              // optional
    "reasoning_type": "ReAct",
    "llm": "", "language": "vi",
    "use_mindmap": true, "use_citation": "inline"
  },
  "selected_file_ids": []            // [] = search all
}
```
Header trả về có `X-Conversation-Id`. Body là `text/event-stream`.

### Conversations
| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/conversations` | Danh sách hội thoại |
| `POST` | `/api/conversations` | Tạo mới |
| `GET` | `/api/conversations/{id}` | Messages + suggestions + selected files |
| `PATCH` | `/api/conversations/{id}` | Đổi tên / is_public |
| `DELETE` | `/api/conversations/{id}` | Xoá |

### Suggestions
| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/suggestions/default` | Câu mẫu mặc định (tiếng Việt) |
| `POST` | `/api/conversations/{id}/suggestions` | Sinh follow-up theo lịch sử |

### Settings
| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/settings/schema` | Option khả dụng (engine/tool/llm/lang) để render form |
| `GET` | `/api/settings` | Setting hiện tại (defaults phủ bởi override đã lưu) |
| `PUT` | `/api/settings` | Lưu override của user (key phẳng, vd `reasoning.use`) |

### Indices / System
| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/indices` | Danh sách index |
| `GET` | `/api/indices/{id}/files` | File để chọn lọc phạm vi |
| `GET` | `/api/health` | App + index sẵn sàng |
| `GET` | `/api/config` | Cờ feature (chat_suggestion, lang mặc định) |

## 4. Mô hình dữ liệu hội thoại (tái dùng ktem)

`Conversation` (ktem/db/models.py): `id, name, user, is_public, data_source{}, date_*`.
`data_source` là JSON chứa:
- `messages`: list `[ [user, bot], ... ]`
- `selected`: file ids chọn theo index
- `chat_suggestions`: `[[q1],[q2],...]`
- `retrieval_messages`: HTML info panel mỗi lượt
- `plot_history`, `state`

API mở cùng `sql.db` qua `from ktem.db.engine import engine`.

## 5. Cấu trúc thư mục

```
app/api/
  main.py            FastAPI(), CORS, mount routers, bootstrap sys.path
  context.py         singleton BaseApp + default settings
  engine.py          create_pipeline + stream (port từ ChatPage.chat_fn)
  deps.py            user_id mặc định, db session
  schemas.py         Pydantic request/response
  adapters/
    stream.py        Document -> SSE event
  routers/
    chat.py  conversations.py  settings.py  suggestions.py  indices.py  system.py
```

## 6. Trạng thái & việc còn lại

**Đã xong (backend):**
- ✅ Adapter citation có cấu trúc (event `citations` JSON) — dùng `match_evidence_with_context()`
  + `collected_docs`, KHÔNG đụng backend.
- ✅ Hủy stream (`POST /api/chat/stop`, cooperative) + regen (`POST /api/chat/{id}/regen`).
- ✅ Settings persist (GET merge defaults+override, PUT lưu vào ktem `Settings` table).
- ✅ Conversations CRUD, suggestions, indices/files, health/config.

**Còn lại:**
1. Auth: hiện `KH_FEATURE_USER_MANAGEMENT=false` → user_id cố định `"default"`. Cắm JWT sau.
2. Upload/ingest file qua API (hiện chỉ đọc danh sách index; ingest vẫn qua `rag/ingest_corpus.py`).
3. Mindmap/plot: hiện đi trong `info` HTML; có thể tách event riêng nếu React cần render bằng
   markmap/react-plotly.
4. **Frontend React (Vite) trong `frontend/`** — làm cuối cùng.

## 7. Lưu ý vận hành

- `react.py:ainvoke` raise `NotImplementedError` → bắt buộc đi qua `stream()` (generator
  đồng bộ). Trong FastAPI chạy generator trong threadpool, đẩy ra `StreamingResponse`.
- Khởi tạo `BaseApp` **một lần** lúc startup, giữ singleton; không dựng lại mỗi request.
- Các bản vá LỖI #4 (`private=false`) & #5 (`lancedb.py`) vẫn áp dụng vì dùng chung index.
