# Chatbot RAG hướng dẫn Thủ tục hành chính công Việt Nam

Chatbot hỏi–đáp về thủ tục hành chính công, dữ liệu lấy từ
[Cổng Dịch vụ công Quốc gia](https://dichvucong.gov.vn), xây trên nền
[kotaemon](https://github.com/Cinnamon/kotaemon).

| Thành phần | Công nghệ |
|---|---|
| Embedding | Azure `text-embedding-3-large` (3072d) |
| LLM | Azure OpenAI `gpt-4o` |
| RAG framework | kotaemon (Chroma + LanceDB, hybrid retrieval) |

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
│   ├── prompts.py         #    Prompt tiếng Việt (QA + viết lại truy vấn) — component chính
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
```

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

### Bước 5 — Chạy

```powershell
# Chatbot (chạy từ gốc repo)
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
