# Chatbot RAG hướng dẫn Thủ tục hành chính công Việt Nam

Chatbot hỏi–đáp về thủ tục hành chính công, dữ liệu lấy từ
[Cổng Dịch vụ công Quốc gia](https://dichvucong.gov.vn), xây trên nền
[kotaemon](https://github.com/Cinnamon/kotaemon).

| Thành phần | Công nghệ |
|---|---|
| Embedding | Azure `text-embedding-3-large` (3072d) |
| LLM | Azure OpenAI `gpt-4o` |
| RAG framework | kotaemon (Chroma + LanceDB, hybrid retrieval) |

---

## Yêu cầu

- **Windows** (Linux chưa được kiểm tra — xem lưu ý cuối)
- **Python 3.10**
- **[uv](https://github.com/astral-sh/uv)**: `pip install uv`
- **git**
- **Tài khoản Azure OpenAI** với hai deployment: `gpt-4o` + `text-embedding-3-large`

---

## Clone & Setup (máy mới)

### Bước 1 — Clone code repo

```powershell
git clone <url-code-repo> "du-an"
cd "du-an"
```

### Bước 2 — Clone kotaemon và cài dependencies

`kotaemon-app/` không được commit vào git (third-party code). Cần clone riêng:

```powershell
git clone --depth 1 https://github.com/Cinnamon/kotaemon.git kotaemon-app
cd kotaemon-app

# Tạo venv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip uv

# Cài deps (dùng uv, KHÔNG pip — pip kẹt resolver)
.venv\Scripts\uv.exe pip install --python .venv\Scripts\python.exe `
  --constraint ..\kotaemon-setup\constraints.txt `
  -e "libs/kotaemon" -e "libs/ktem" `
  fastembed "onnxruntime<1.20" "unstructured>=0.15.8,<0.16" tabulate cachetools

cd ..
```

### Bước 3 — Copy file cấu hình từ kotaemon-setup

```powershell
cd kotaemon-app

copy ..\kotaemon-setup\.env.example .env
# → Mở .env, điền:
#     AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
#     AZURE_OPENAI_API_KEY=<key>
#     AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
#     AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=text-embedding-3-large
#   (KH_APP_DATA_DIR=C:\ktem_data đã có sẵn trong .env.example — KHÔNG đổi)

copy ..\kotaemon-setup\flowsettings.py .
copy ..\kotaemon-setup\ingest_corpus.py .
copy ..\kotaemon-setup\query_test.py .

cd ..
```

### Bước 4 — Tải index đã embed từ HuggingFace

Không cần crawl hay embed lại — tải index ~1.5 GB đã xây sẵn:

```powershell
cd kotaemon-app
.venv\Scripts\python.exe ..\kotaemon-setup\init_index.py --hf-repo MinhTriet/dvc-rag-index
```

Script sẽ download `ktem_index.tar.gz` về, giải nén vào `C:\ktem_data`, và kiểm tra tính hợp lệ.

> **Không có HF?** Download thủ công `ktem_index.tar.gz` rồi chạy:
> ```powershell
> .venv\Scripts\python.exe ..\kotaemon-setup\init_index.py --from C:\path\to\ktem_index.tar.gz
> ```

### Bước 5 — Chạy chatbot

```powershell
cd kotaemon-app
.venv\Scripts\python.exe app.py        # → http://localhost:7860
```

Kiểm tra RAG không qua UI:

```powershell
.venv\Scripts\python.exe query_test.py "Hồ sơ xin phép trường mầm non cần giấy tờ gì?"
```

---

## Cấu trúc sau khi setup xong

```
du-an/
├── crawler/           Script crawl dichvucong.gov.vn
├── parser/            parse.py: JSON → Markdown corpus
├── kotaemon-setup/    Cấu hình tùy biến (commit vào git)
│   ├── flowsettings.py
│   ├── ingest_corpus.py
│   ├── query_test.py
│   ├── pack_index.py  Đóng gói index để chia sẻ
│   ├── init_index.py  Khởi tạo index trên máy mới  ← bước 4
│   └── .env.example
├── data/
│   └── corpus/md/     5208 file .md (tải từ HF hoặc chạy parser)
├── kotaemon-app/      Clone từ Cinnamon/kotaemon  ← gitignore
│   ├── .env           Azure keys  ← gitignore
│   ├── flowsettings.py
│   ├── app.py
│   └── .venv/
└── C:\ktem_data\      Index (vectorstore + docstore)  ← ngoài repo
    └── user_data/
        ├── vectorstore/   Chroma (HNSW .bin files + chroma.sqlite3)
        ├── docstore/      LanceDB
        ├── files/index_1/ Bản sao .md
        └── sql.db
```

---

## Nếu muốn xây index từ đầu (crawl + embed)

```powershell
# 1. Crawl (chạy trong crawler/)
pip install -r requirements.txt
python crawl.py              # ~5208 thủ tục → data/raw/*.json

# 2. Parse (chạy trong parser/)
python parse.py              # → data/corpus/md/*.md

# 3. Ingest (chạy trong kotaemon-app/)
$env:PYTHONUNBUFFERED=1
.venv\Scripts\python.exe ingest_corpus.py    # ~2.5 giờ với Azure embedding

# 4. Đóng gói để chia sẻ
.venv\Scripts\python.exe ..\kotaemon-setup\pack_index.py --hf-repo MinhTriet/dvc-rag-index --hf-token hf_xxx
```

---

## Lưu ý quan trọng

**⚠️ Path phải là ASCII (Windows):** `kotaemon-app/.env` có `KH_APP_DATA_DIR=C:\ktem_data`.
Nếu đặt index vào thư mục có tên tiếng Việt, `hnswlib` sẽ không tạo được file `.bin` —
toàn bộ vector mất sau khi ingest mà không có lỗi báo. Giữ nguyên `C:\ktem_data`.

**⚠️ Không force-kill quá trình ingest:** Nếu bị treo sau khi kill, xóa theflow cache:
```powershell
Remove-Item -Recurse -Force "$env:TEMP\claude\theflow_$env:USERNAME"
```

**Linux / HF Spaces:** HNSW binary chưa được kiểm tra cross-platform. Nếu cần deploy Linux, đặt `KH_APP_DATA_DIR=/ktem_data` và test xem `.bin` files có đọc được không.
