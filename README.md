# Chatbot RAG hướng dẫn Thủ tục hành chính công Việt Nam

Chatbot hỏi–đáp về thủ tục hành chính công, dữ liệu lấy từ
[Cổng Dịch vụ công Quốc gia](https://dichvucong.gov.vn), xây trên nền
[kotaemon](https://github.com/Cinnamon/kotaemon).

| Thành phần | Công nghệ |
|---|---|
| Embedding | Azure `text-embedding-3-large` (3072d) |
| LLM | Azure OpenAI `gpt-4o` |
| RAG framework | kotaemon (Chroma + LanceDB, hybrid retrieval) |
| Reasoning | **ReAct Agent** (agentic, mặc định) — tự tra corpus, fallback web khi không có |
| Web fallback | Brave Search API (tuỳ chọn, cần `BRAVE_API_KEY`) |

> **Toàn bộ code nằm trong repo này** — kể cả thư viện kotaemon đã chỉnh (vendor
> trong `app/libs/`). Clone là có đủ code, **không** phải clone kotaemon rồi copy
> file cấu hình như trước. Chỉ cần cài deps + tải index + điền `.env`.

---

## Cấu trúc repo

```
.
├── pipeline/              # ❶ Thu thập & xử lý dữ liệu → corpus (độc lập kotaemon)
│   ├── crawler/           #    crawl.py: crawl dichvucong.gov.vn → data/raw/*.json
│   └── parser/            #    parse.py: JSON → data/corpus/md/*.md (+ chunks.jsonl)
│
├── rag/                   # ❷ Code RAG của dự án (wiring kotaemon)
│   ├── prompts.py         #    Prompt tiếng Việt (QA + viết lại truy vấn + ReAct agent)
│   ├── agent_tools.py     #    Tool agent dự án: BraveSearchTool (web fallback)
│   ├── flowsettings.py    #    Cấu hình kotaemon: Azure embed 3072d, lang=vi, data dir
│   ├── ingest_corpus.py   #    Nạp corpus → vector/doc store (qua pipeline kotaemon)
│   ├── fast_ingest.py     #    Nạp song song 10 worker (nhanh hơn, bỏ qua theflow)
│   └── query_test.py      #    Test RAG headless (không qua UI)
│
├── app/                   # ❸ kotaemon đã vendor (gồm các bản vá của dự án)
│   ├── app.py             #    Launcher Gradio
│   └── libs/{kotaemon,ktem}
│
├── scripts/               # ❹ Tiện ích chia sẻ index
│   ├── init_index.py      #    Tải + giải nén index từ HuggingFace (máy mới)
│   ├── pack_index.py      #    Đóng gói + upload index lên HF
│   └── gen_constraints.py
│
├── constraints.txt        # Pin phiên bản deps (kotaemon dùng API cũ)
├── .env.example           # Mẫu cấu hình Azure
└── data/                  # (gitignore) corpus + raw — tải từ HF / sinh bởi pipeline
```

Ngoài repo: index (~1.5 GB, vectorstore + docstore) nằm ở `C:\ktem_data` (đặt qua
`KH_APP_DATA_DIR` trong `.env`), tải sẵn từ HuggingFace — **không cần embed lại**.

---

## Yêu cầu

- **Windows** (Linux chưa kiểm tra — xem lưu ý cuối)
- **Python 3.10**
- **[uv](https://github.com/astral-sh/uv)**: `pip install uv`
- **Node.js ≥ 20** (kèm `npm`) — cho UI React ở `frontend/` (đã test trên Node 22 / npm 10)
- **git**
- **Tài khoản Azure OpenAI** với hai deployment: `gpt-4o` + `text-embedding-3-large`

---

## Setup (máy mới)

### Bước 1 — Clone & tạo môi trường

```powershell
git clone <url-repo> "du-an"
cd "du-an"

python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip uv
```

### Bước 2 — Cài dependencies (dùng uv, KHÔNG pip — pip kẹt resolver)

```powershell
.venv\Scripts\uv.exe pip install --python .venv\Scripts\python.exe `
  --constraint constraints.txt `
  -e "app/libs/kotaemon" -e "app/libs/ktem" `
  fastembed "onnxruntime<1.20" "unstructured>=0.15.8,<0.16" tabulate cachetools
```

### Bước 3 — Cấu hình `.env`

```powershell
copy .env.example .env
# → Mở .env, điền:
#     AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
#     AZURE_OPENAI_API_KEY=<key>
#     AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
#     AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=text-embedding-3-large
#   (KH_APP_DATA_DIR=C:\ktem_data đã có sẵn — KHÔNG đổi, xem lưu ý path ASCII)
#   Tuỳ chọn (cho web fallback của ReAct agent):
#     BRAVE_API_KEY=<key tại https://brave.com/search/api/>  # để trống = tắt web fallback
```

> **Reasoning mặc định là ReAct Agent** (agentic): tự tra corpus nội bộ trước, chỉ tìm
> web (Brave) khi corpus không có tài liệu liên quan. Đổi engine trong UI:
> **Settings → Reasoning → Reasoning options**. Chi tiết xem `CLAUDE.md`.

### Bước 4 — Tải index đã embed từ HuggingFace

Không cần crawl/embed lại — tải index xây sẵn (~728 MB nén):

```powershell
.venv\Scripts\python.exe scripts\init_index.py --hf-repo MinhTriet/dvc-rag-embeddings
```

Script tải `ktem_index.tar.gz`, giải nén vào `C:\ktem_data`, rồi kiểm tra hợp lệ.
Kiểm tra index bất kỳ lúc nào: `.venv\Scripts\python.exe scripts\init_index.py --verify`

> **Không dùng HF?** Tải `ktem_index.tar.gz` thủ công rồi:
> ```powershell
> .venv\Scripts\python.exe scripts\init_index.py --from C:\path\to\ktem_index.tar.gz
> ```

### Bước 5 — Cài dependencies cho UI React

```powershell
cd frontend
npm install        # tải node_modules (chỉ lần đầu / khi đổi package.json)
cd ..
```

> UI React (Vite + React 19 + Tailwind 4) gọi backend qua tầng FastAPI `app/api/`.
> Hợp đồng API + SSE: xem `frontend/README.md` (và Swagger `:8000/docs` khi chạy backend).

### Bước 6 — Chạy demo (UI React = demo chính)

Demo chính là **UI React**, cần chạy **2 tiến trình song song** (mỗi cái một terminal,
đều chạy từ gốc repo):

```powershell
# Terminal 1 — Backend API (FastAPI), từ gốc repo
.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
#   Swagger để kiểm tra endpoint: http://127.0.0.1:8000/docs

# Terminal 2 — Frontend (Vite dev server)
cd frontend
npm run dev                                    # → http://127.0.0.1:5173
```

Mở **http://127.0.0.1:5173** để dùng chatbot. Vite tự proxy `/api` → `http://127.0.0.1:8000`
(không lo CORS). **Phải chạy backend trước** rồi mới tới frontend.

**Bản host LAN** (cho máy khác trong mạng truy cập) — build tĩnh rồi serve:

```powershell
# Terminal 1 — vẫn cần backend chạy
.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000

# Terminal 2 — build + preview (host:true, port 4173, có proxy /api riêng)
cd frontend
npm run build
npm run preview                                # → http://<IP-máy>:4173
```

> Sau khi **ingest lại** corpus, phải **restart uvicorn** để nạp lại vector store vào RAM.

### (Phụ) UI Gradio + test headless

Gradio chỉ là UI phụ để debug nhanh; demo chính dùng React ở trên.

```powershell
# UI Gradio (1 tiến trình, không cần API/FE)
.venv\Scripts\python.exe app\app.py            # → http://localhost:7860

# Test RAG không qua UI
.venv\Scripts\python.exe rag\query_test.py "Hồ sơ đăng ký khai sinh gồm những gì?"
```

> Các entry script tự thêm gốc repo vào `sys.path`, không cần set `PYTHONPATH`.

---

## Xây index từ đầu (tuỳ chọn — crawl + embed)

```powershell
# 1. Crawl  → data/raw/*.json (~5208 thủ tục)
.venv\Scripts\python.exe pipeline\crawler\crawl.py

# 2. Parse  → data/corpus/md/*.md
.venv\Scripts\python.exe pipeline\parser\parse.py

# 3. Ingest → C:\ktem_data  (≈2.5h kiểu thường, hoặc dùng fast_ingest 10 worker)
$env:PYTHONUNBUFFERED=1
.venv\Scripts\python.exe rag\ingest_corpus.py
#   hoặc nhanh hơn:
.venv\Scripts\python.exe rag\fast_ingest.py --workers 10

# 4. Đóng gói + chia sẻ
.venv\Scripts\python.exe scripts\pack_index.py --hf-repo MinhTriet/dvc-rag-embeddings --hf-token hf_xxx
```

---

## Lưu ý quan trọng

**⚠️ Path phải ASCII (Windows):** `.env` đặt `KH_APP_DATA_DIR=C:\ktem_data`. Nếu để
index trong thư mục có tên tiếng Việt, `hnswlib` không tạo được file `.bin` — toàn bộ
vector mất sau ingest mà **không báo lỗi**. Giữ nguyên `C:\ktem_data`.

**⚠️ Không force-kill tiến trình ingest:** nếu treo sau khi kill, xóa theflow cache:
```powershell
Remove-Item -Recurse -Force "$env:TEMP\claude\theflow_$env:USERNAME"
```

**Bản vá kotaemon nằm trong `app/libs/`** (đã commit): `private=false` lưu trong index;
vá FTS LanceDB (`lancedb.py`) chống Rust panic; prompt tiếng Việt tách ra `rag/prompts.py`.
Vì vendor sẵn nên clone máy mới **không tái phát** các lỗi này.

**Linux / HF Spaces:** HNSW binary chưa kiểm tra cross-platform. Deploy Linux cần
đặt `KH_APP_DATA_DIR=/ktem_data` và kiểm tra `.bin` đọc được không.
