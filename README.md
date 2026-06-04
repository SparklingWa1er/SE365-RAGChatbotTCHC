# Chatbot RAG hướng dẫn Thủ tục hành chính công Việt Nam

Chatbot hỏi–đáp về thủ tục hành chính công, dữ liệu lấy từ
[Cổng Dịch vụ công Quốc gia](https://dichvucong.gov.vn), xây trên nền
[kotaemon](https://github.com/Cinnamon/kotaemon).

| Thành phần | Công nghệ |
|---|---|
| Embedding | Azure `text-embedding-3-large` (3072d) |
| LLM | Azure OpenAI `gpt-4o` |
| RAG framework | kotaemon (Chroma vector store, LanceDB doc store, hybrid retrieval) |

> **Dữ liệu & embeddings tải từ HuggingFace** — không cần crawl hay embed tại máy.

---

## Yêu cầu

- **Python 3.10+**
- **[uv](https://github.com/astral-sh/uv)** — cài bằng `pip install uv` (KHÔNG dùng pip cho kotaemon)
- **git** + tài khoản **HuggingFace** (tải data miễn phí)
- **Tài khoản Azure OpenAI** có deployment `gpt-4o` + `text-embedding-3-large`

---

## Bước 0 — Tải dữ liệu từ HuggingFace

Dữ liệu đã sẵn sàng trên HuggingFace. Tải về:

```bash
# Tải corpus
huggingface-cli download MinhTriet/thu-tuc-hanh-chinh-dvc-data \
  --repo-type dataset --local-dir ./data
cd data && tar -xzf data.tar.gz && rm data.tar.gz && cd ..

# Tải embeddings
huggingface-cli download MinhTriet/dvc-rag-embeddings \
  --repo-type dataset --local-dir ./embeddings-sample
cd embeddings-sample && tar -xzf embedding-first-300.tar.gz
cp -r ktem_app_data/ ../kotaemon-app/  # sao chép vào để dùng ngay
cd ..
```

Kết quả:
- `data/raw/*.json` — 5208 chi tiết thủ tục (JSON gốc)
- `data/corpus/md/*.md` — 5208 Markdown corpus
- `kotaemon-app/ktem_app_data/` — vector store đã embed

---

## Bước 1 — Cài đặt kotaemon

Clone kotaemon + tạo venv + cài deps:

```bash
# 1.1 Clone kotaemon
git clone --depth 1 https://github.com/Cinnamon/kotaemon.git kotaemon-app
cd kotaemon-app

# 1.2 Tạo virtualenv + cài uv
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip uv

# 1.3 Cài deps
.venv/Scripts/uv.exe pip install --python .venv/Scripts/python.exe \
  --constraint ../kotaemon-setup/constraints.txt \
  -e "libs/kotaemon" -e "libs/ktem" \
  fastembed "onnxruntime<v1.20" "unstructured>=0.15.8,<0.16" tabulate cachetools
```

### 1.2 Áp dụng cấu hình tùy biến

Sao chép từ `kotaemon-setup/` vào `kotaemon-app/`:

```bash
cp ../kotaemon-setup/.env.example .env
# Sửa key trong .env: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT

cp ../kotaemon-setup/flowsettings.py .
cp ../kotaemon-setup/ingest_corpus.py .
cp ../kotaemon-setup/query_test.py .
cp ../kotaemon-setup/ui.py libs/ktem/ktem/index/file/ui.py
```

---

## Bước 2 — Chạy chatbot

```bash
cd kotaemon-app
.venv/Scripts/python.exe app.py            # mở http://localhost:7860
```

Vào tab **Chat**, hỏi tiếng Việt. Kiểm thử nhanh:
```bash
.venv/Scripts/python.exe query_test.py "Hồ sơ xin phép trường mầm non cần giấy tờ gì?"
```

---

## Cấu trúc sau khi setup xong

```
data/
  raw/                     5208 JSON gốc
  corpus/
    md/                    5208 file Markdown
    chunks.jsonl
    metadata.jsonl
  index.jsonl

kotaemon-app/
  .env                     Azure API key
  flowsettings.py
  libs/ktem/
    ktem/index/file/ui.py
  ktem_app_data/
    user_data/
      vectorstore/         Chroma vector store
      docstore/            LanceDB doc store
      sql.db
    huggingface/           Model cache
  .venv/                   Python environment
  ingest_corpus.py         từ kotaemon-setup
  query_test.py            từ kotaemon-setup
  app.py                   Chatbot web
```

---

## Dữ liệu & Embeddings

- **Data**: [`MinhTriet/thu-tuc-hanh-chinh-dvc-data`](https://huggingface.co/datasets/MinhTriet/thu-tuc-hanh-chinh-dvc-data) — 5208 thủ tục
- **Embeddings**: [`MinhTriet/dvc-rag-embeddings`](https://huggingface.co/datasets/MinhTriet/dvc-rag-embeddings) — 300 mẫu (Azure `text-embedding-3-large`, 3072d)
