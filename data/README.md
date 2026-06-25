---
license: other
language:
- vi
task_categories:
- question-answering
- text-retrieval
tags:
- vietnam
- administrative-procedures
- rag
- dichvucong
pretty_name: Thủ tục hành chính công Việt Nam (dichvucong.gov.vn)
---

# Thủ tục hành chính công Việt Nam — dữ liệu crawl

Toàn bộ **5208 thủ tục hành chính** crawl từ [Cổng Dịch vụ công Quốc gia](https://dichvucong.gov.vn),
dùng làm knowledge base cho chatbot RAG.

## Nội dung (`data.tar.gz`)

```
data/
  raw/<uuid>.json        # 5208 chi tiết thủ tục (JSON gốc, có cấu trúc)
  corpus/md/*.md         # 5208 file Markdown đã parse (+ metadata frontmatter)
  corpus/chunks.jsonl    # chunk theo section + metadata
  corpus/metadata.jsonl  # metadata mỗi thủ tục
  index.jsonl            # danh sách thủ tục (id, mã, tên, lĩnh vực...)
```

## Cách dùng

```bash
huggingface-cli download MinhTriet/thu-tuc-hanh-chinh-dvc-data data.tar.gz \
  --repo-type dataset --local-dir .
tar -xzf data.tar.gz      # giải nén ra thư mục data/
```

Mỗi `raw/*.json` chứa: trình tự thực hiện, thành phần hồ sơ (`executionCases[].profileComponents`),
cách thức, điều kiện, căn cứ pháp lý, kết quả, cơ quan thực hiện.

> Dữ liệu thuộc Cổng Dịch vụ công Quốc gia, dùng cho mục đích học tập/nghiên cứu.
