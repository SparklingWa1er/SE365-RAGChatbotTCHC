# Thay đổi pipeline RAG — Tháng 6/2026

Tài liệu này ghi lại các thay đổi đã thực hiện cho luồng hỏi–đáp (RAG) của chatbot
thủ tục hành chính, **lý do** đằng sau mỗi thay đổi, cách kiểm thử, và **đề xuất cải
thiện** kèm nguồn tham khảo.

> Phạm vi: sửa logic *trả lời / từ chối* trong `FullQAPipeline` và prompt tiếng Việt.
> KHÔNG đụng tới ingest/embedding nên **không cần re-index**.

---

## 1. Bối cảnh — triệu chứng quan sát được

Khi chạy thử 3 lượt liên tiếp (chào → "16 tuổi đi làm thêm" → "em tôi 13 tuổi thì sao?"):

| Lượt | Điểm rerank | Hành vi CŨ | Đúng/Sai |
|------|-------------|------------|----------|
| Chào | — | Chào lại | ✅ |
| 16 tuổi | tất cả `0.0` | **Bịa** câu trả lời từ kiến thức nền (giấy khai sinh, giấy khám sức khỏe…) | ❌ phải từ chối |
| 13 tuổi | `1.0`, `0.4` | **Từ chối** "không có thủ tục phù hợp" dù mindmap vẽ đầy đủ | ❌ phải trả lời |

→ Hai mâu thuẫn: (a) điểm rerank toàn 0 mà vẫn trả lời (bịa); (b) điểm rerank 1.0 mà
lại từ chối. Hệ thống "không ổn định".

---

## 2. Nguyên nhân gốc rễ

### 2.1. Nhánh "evidence rỗng" bỏ qua QA prompt → LLM bịa
Trong `app/libs/kotaemon/kotaemon/indices/qa/citation_qa.py::stream()`:

```python
if evidence:
    prompt, evidence = self.get_prompt(question, evidence, evidence_mode)
else:
    prompt = question      # ← QA prompt (mọi quy tắc "chỉ dùng ngữ cảnh") bị BỎ QUA
```

Khi `evidence` rỗng, LLM chỉ nhận **câu hỏi trần** + một `system_prompt` yếu → trả lời tự
do từ kiến thức nền. Nhánh này vốn dành cho **chào hỏi**, nhưng trường hợp "không có tài
liệu liên quan" cũng rơi vào đây → bịa.

### 2.2. Prompt cho LLM "tự phán đoán lạc đề" → từ chối oan
`DEFAULT_QA_DOMAIN_PROMPT` cũ có câu: *"nếu ngữ cảnh nói về thủ tục khác hẳn → nói không
có thủ tục phù hợp"*. LLM (bị **mồi** bởi lượt 16 tuổi vừa từ chối, do 5 lượt hội thoại
gần nhất được nhồi vào messages) áp dụng nhầm dù ngữ cảnh lần này thực sự khớp (điểm 1.0).

**Bài học:** quyết định trả lời/từ chối phải dựa trên **tín hiệu định lượng (điểm rerank)
do CODE xử lý**, không phó mặc cho LLM tự phán (vốn bất ổn và bị history mồi).

---

## 3. Các thay đổi đã thực hiện

### #3 — Lọc đoạn có điểm rerank = 0
**File:** `app/libs/ktem/ktem/reasoning/simple.py` (`FullQAPipeline.stream`)

Chấm điểm liên quan **đồng bộ** trước khi sinh câu trả lời, rồi bỏ các đoạn reranker chấm
`0` (không liên quan), để answer LLM chỉ thấy ngữ cảnh thực sự liên quan.

```python
docs = self.retrievers[0].generate_relevant_scores(message, docs)
docs = [d for d in docs if d.metadata.get("llm_trulens_score", 0.0) > 0]
```

### Short-circuit — từ chối CỐ ĐỊNH khi tất cả đoạn = 0
**File:** `simple.py` (ngay sau bước lọc #3)

Nếu **đã truy xuất ra tài liệu** nhưng reranker chấm **tất cả = 0** → trả lời "ngoài phạm
vi" bằng một thông điệp cố định, **không gọi answer LLM**. Lý do: tránh đúng nhánh
"evidence rỗng" ở mục 2.1 (vốn khiến LLM bịa). Quyết định từ chối do **code** đưa ra.

```python
had_docs = bool(docs)
# ... rerank + filter ...
if had_docs and not docs:
    out_of_scope = ("Cơ sở dữ liệu của tôi chỉ gồm các thủ tục hành chính công và "
                    "hiện không tìm thấy thủ tục phù hợp với câu hỏi này. ...")
    yield Document(channel="chat", content=out_of_scope)
    return Document(content=out_of_scope)
```

> Lưu ý: chào hỏi/xã giao → `retrieve()` trả `[]` (`had_docs=False`) → KHÔNG vào nhánh
> này → vẫn để `system_prompt` chào tự nhiên. Hai trạng thái "rỗng" được tách bạch.

### #2 — Bỏ "giấy phép tự phán lạc đề" trong prompt
**File:** `rag/prompts.py` (`DEFAULT_QA_DOMAIN_PROMPT`)

Thay mệnh đề cho LLM tự phán bằng quy tắc dựa trên trạng thái ngữ cảnh:

> *"Các đoạn ngữ cảnh dưới đây ĐÃ được hệ thống chọn lọc là liên quan — bạn PHẢI dùng
> chúng để trả lời. TUYỆT ĐỐI không từ chối, không tự phán đoán câu hỏi là lạc đề…"*

### (A) — Thành thật về thủ tục "khớp một phần"
**File:** `rag/prompts.py` (`DEFAULT_QA_DOMAIN_PROMPT`)

Vẫn trình bày thủ tục gần nhất, nhưng **bắt LLM nêu rõ điểm chưa khớp** (tuổi, đối tượng,
phạm vi, cấp). Xử lý đúng ca "13 tuổi" vs thủ tục "chưa đủ 13 tuổi":

> *"Nếu thủ tục trong ngữ cảnh CHỈ KHỚP MỘT PHẦN với câu hỏi (lệch về độ tuổi, đối tượng
> áp dụng, phạm vi…), vẫn trình bày nhưng PHẢI nói rõ ngay từ đầu điểm chưa khớp…"*

---

## 4. Kết quả sau khi sửa (đã kiểm thử trên UI)

| Tình huống | Điểm rerank | Hành vi MỚI |
|------------|-------------|-------------|
| Chào hỏi | — | Chào lại (system_prompt) |
| **Có trong corpus** (vd hồ sơ quỹ đầu tư khởi nghiệp) | `1.0` | Trả lời đầy đủ, đúng trọng tâm, có trích nguồn + mindmap |
| **Không có trong corpus** (16 tuổi) | tất cả `0.0` | Từ chối cố định, **không bịa** |
| **Khớp một phần** (13 tuổi) | `0.8` | Trả lời + **nêu rõ điểm lệch tuổi/đối tượng** |

Ba hành vi giờ nhất quán: quyết định trả lời/từ chối do điểm rerank (code) quyết, LLM chỉ
còn việc diễn đạt.

---

## 5. Giới hạn còn lại

- Reranker hiện là **LLM call/đoạn** (prompt tiếng Anh, điểm 0–10 thô) → chậm (~5–8s) và
  còn biến thiên; nay chỉ ảnh hưởng *điểm số*, không trực tiếp gây bịa/từ chối.
- Reranker false-negative (chấm nhầm 0 cho đoạn thực sự liên quan) → từ chối oan. Đây là
  vấn đề tinh chỉnh reranker, tách biệt.
- Gốc của ca "13 tuổi": **corpus thiếu** thủ tục cho nhóm 13–17 đi làm; chỉ vá được bằng
  việc thành thật về phạm vi (A), không sửa bằng code.

---

## 6. Đề xuất cải thiện (kiến trúc/kỹ thuật mới)

> Lộ trình ROI giảm dần. Khuyến nghị bắt đầu: #1 → #2 → #3.

| # | Việc | Công sức | Lợi ích |
|---|------|----------|---------|
| 1 | Bộ eval **RAGAS** ~30 câu vàng (đo baseline trước mọi thay đổi) | Thấp | Nền cho mọi thay đổi |
| 2 | Chunk theo section + **Contextual Retrieval** (Anthropic) | TB | Sửa tận gốc ca 13-tuổi & cắt ngang hồ sơ |
| 3 | Thay LLM-trulens → **cross-encoder VN** (bge-reranker-v2-m3 / ViRanker) | TB | Nhanh hơn ~10×, ổn định, đỡ tiền LLM |
| 4 | **Metadata filter** (lĩnh vực/cấp/đối tượng từ frontmatter có sẵn) | Thấp | Giảm nhiễu xuyên lĩnh vực |
| 5 | **bge-m3 hybrid** / Vietnamese_Embedding + BM25 tokenize tiếng Việt | TB | Tăng recall tiếng Việt (⚠️ phải re-index) |
| 6 | **CRAG / Self-RAG** cho quyết định từ chối thông minh | Cao | Thay ngưỡng cứng |
| 7 | **Agentic / multi-query (RAG-Fusion)** cho câu phức, so sánh | Cao | Câu đa điều kiện |

### Diễn giải các điểm yếu chính
- **Vứt cấu trúc đã parse:** ingest nạp nguyên `.md` rồi cắt cứng ~1024 token, KHÔNG dùng
  `chunks.jsonl` (section-based) và KHÔNG dùng metadata YAML để lọc. → Contextual Retrieval
  prepend "thủ tục X / mục Y / đối tượng Z" vào mỗi chunk trước khi embed (+5–15% precision).
- **Không tối ưu tiếng Việt:** BM25 dùng tokenizer `en_stem`; reranker dùng prompt tiếng
  Anh chấm nội dung tiếng Việt. → model embedding/reranker chuyên tiếng Việt.
- **Single-hop, không self-correction, không eval.**

---

## 7. Nguồn tham khảo

**Kỹ thuật chunking / retrieval:**
- Anthropic — *Contextual Retrieval*: https://www.anthropic.com/news/contextual-retrieval
- AWS — *Contextual retrieval with Bedrock*: https://aws.amazon.com/blogs/machine-learning/contextual-retrieval-in-anthropic-using-amazon-bedrock-knowledge-bases/
- anthropic-cookbook (notebook contextual-embeddings): https://github.com/anthropics/anthropic-cookbook
- autollama (impl Contextual Retrieval, so sánh chunk trực quan): https://github.com/autollama/autollama

**Model tiếng Việt (embedding & reranker):**
- AITeamVN/Vietnamese_Embedding: https://huggingface.co/AITeamVN/Vietnamese_Embedding
- BAAI/bge-m3 (dense + sparse + ColBERT hybrid): https://huggingface.co/BAAI/bge-m3
- Qwen3-Reranker / Embedding: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- ViRanker (cross-encoder reranking tiếng Việt, arXiv): https://arxiv.org/pdf/2509.09131
- VN-MTEB (benchmark embedding tiếng Việt, arXiv): https://arxiv.org/pdf/2507.21500
- Advancing Vietnamese Information Retrieval (arXiv): https://arxiv.org/pdf/2503.07470

**Kiến trúc RAG hiện đại:**
- RAGFlow — *From RAG to Context: 2025 year-end review*: https://ragflow.io/blog/rag-review-2025-from-rag-to-context
- *Engineering the RAG Stack* (review, arXiv): https://arxiv.org/pdf/2601.05264
- *From BM25 to Corrective RAG* (benchmark, arXiv): https://arxiv.org/html/2604.01733v1

**File đã sửa trong repo:**
- `app/libs/ktem/ktem/reasoning/simple.py` — lọc #3 + short-circuit từ chối cố định
- `rag/prompts.py` — bỏ tự-phán-lạc-đề (#2) + nêu rõ thủ tục khớp một phần (A)
