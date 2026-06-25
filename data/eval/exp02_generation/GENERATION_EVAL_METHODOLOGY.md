# Phương pháp đánh giá tầng Generation & Citation (exp02)

**Hệ thống:** Chatbot RAG hướng dẫn thủ tục hành chính công Việt Nam (kotaemon).
**Engine đánh giá:** **ReAct Agent** (hai pha — engine mặc định production) · **LLM-judge:** Azure `gpt-4o` · **Embedding:** Azure `text-embedding-3-large` (3072d).
**Trạng thái:** *Tài liệu THIẾT KẾ — viết TRƯỚC khi chạy.* Định nghĩa metric, căn cứ học thuật, tài nguyên & kế hoạch. Số liệu sẽ được điền sau khi chạy `rag/eval/*` (xem [Phụ lục](#phụ-lục--kế-hoạch-tái-lập)).

> **Quan hệ với exp01:** exp01 đo *"hệ có **tìm đúng tài liệu** không"* (tầng retrieval, có gold cứng `ma_thu_tuc` → exact-metric IR). exp02 đo *"hệ có **dùng tài liệu đó trả lời & trích dẫn trung thực** không"* (tầng generation/citation, reference-free → LLM/NLI-judge). Hai tầng tách bạch đúng như RAGAS/ARES khuyến nghị: retrieval và generation là hai trục lỗi độc lập.

---

## 1. Tóm tắt mục tiêu

exp01 đã xác nhận tầng retrieval đạt chuẩn (Hit@5 = 0.922). Nhưng output người dùng thực sự nhận là **câu trả lời tiếng Việt có inline citation `【n】`** do pha 2 của ReAct sinh — phần này **chưa từng được đo**. exp02 lấp khoảng trống đó với hai cụm câu hỏi đánh giá:

| Cụm | Câu hỏi đánh giá | Metric chính |
|---|---|---|
| **Generation** | Câu trả lời có bịa ngoài nguồn không? Có đúng câu hỏi không? Có đủ ý không? | Faithfulness, Answer Relevance, Context Precision/Recall, Completeness |
| **Citation** | `【n】` có trỏ đúng nguồn chứa thông tin không? Có thừa/thiếu không? | Citation Recall, Citation Precision, Citation F1 |

**Nguyên tắc xuyên suốt:** ưu tiên metric có **căn cứ paper đã công bố**, ưu tiên **nhất quán nội bộ** với metric hệ đang dùng (gate `llm_trulens_score` = Context Relevance của TruLens RAG Triad), và **minh bạch hạn chế** của LLM-judge.

---

## 2. Vì sao đo các metric NÀY (căn cứ học thuật)

### 2.1. Cụm Generation

| Metric | Đo gì | Cách tính (tóm tắt) | Căn cứ paper |
|---|---|---|---|
| **Faithfulness / Groundedness** | Câu trả lời có claim nào **không suy ra được** từ evidence (hallucination) | Tách câu trả lời thành các *claim* nguyên tử → kiểm từng claim có được context hỗ trợ (entailment) → tỉ lệ claim được hỗ trợ | **RAGAS** (Es 2023); **TruLens RAG Triad**; **FactScore** (Min 2023) |
| **Answer Relevance** | Câu trả lời có **đúng trọng tâm câu hỏi** không (không lan man/thiếu) | LLM sinh ngược N câu hỏi từ câu trả lời → cosine similarity với câu hỏi gốc (embedding) | **RAGAS** (Es 2023); **ARES** (Saad-Falcon 2024) |
| **Context Precision** | Evidence đưa vào synthesis có **đúng/sạch** không | LLM chấm từng đoạn context có liên quan câu hỏi không | **RAGAS** (Es 2023); **ARES** (Saad-Falcon 2024) |
| **Context Recall** | Context có **chứa đủ** thông tin của thủ tục gold không | So evidence với checklist gold (kéo từ corpus theo `gold_ma_thu_tuc`) | **RAGAS** (Es 2023); IR nền tảng (Manning 2008) |
| **Answer Completeness** *(tùy chọn, cần gold)* | Có liệt kê **đủ hồ sơ / trình tự / phí** — đặc thù thủ tục HC | LLM-judge theo rubric so với checklist gold | **G-Eval** (Liu 2023); **LLM-as-Judge** (Zheng 2023) |

**Lập luận cốt lõi — "RAG Triad":** ba metric Faithfulness + Answer Relevance + Context Relevance hợp thành bộ ba kinh điển đánh giá RAG (RAGAS, ARES, TruLens). Mỗi metric chặn một loại lỗi: Context Relevance bắt lỗi *retrieve sai*, Faithfulness bắt lỗi *bịa khi đã có context đúng*, Answer Relevance bắt lỗi *trả lời lạc đề*. Đo cả ba mới phủ hết trục lỗi của một hệ RAG.

> ⭐ **Nhất quán nội bộ:** gate "không tìm thấy" của hệ (`retriever.generate_relevant_scores` → `llm_trulens_score`, dùng ở cả Simple lẫn ReAct) **chính là Context Relevance của TruLens**. Mở rộng sang Faithfulness/Answer Relevance cùng họ RAG Triad là bước đi tự nhiên, không phải metric chắp vá — đây là lý do biện minh mạnh nhất cho lựa chọn bộ metric này trong ngữ cảnh dự án.

### 2.2. Cụm Citation

| Metric | Đo gì | Cách tính (tóm tắt) | Căn cứ paper |
|---|---|---|---|
| **Citation Recall** | Mỗi câu **cần dẫn nguồn** có thực sự được `【n】` hỗ trợ không | Với mỗi câu: hợp các nguồn được trích có **entail** câu đó không → tỉ lệ câu được hỗ trợ đầy đủ | **ALCE** (Gao 2023); **AIS** (Rashkin 2023) |
| **Citation Precision** | `【n】` có **dư/sai** không (trích nguồn không liên quan) | Tỉ lệ trích dẫn mà nguồn đó thực sự hỗ trợ câu (loại citation thừa) | **ALCE** (Gao 2023) |
| **Citation F1** | Cân bằng recall & precision | Harmonic mean của hai metric trên | **ALCE** (Gao 2023); **Self-RAG** (Asai 2024) |

**Lập luận cốt lõi — attribution:** inline citation `【n】` là điểm bán hàng chính của hệ (giúp người dân kiểm chứng thông tin pháp lý). ALCE (Gao 2023) định nghĩa chính xác **citation precision/recall** và là benchmark chuẩn cho "LLM sinh văn bản có trích dẫn"; AIS (Rashkin 2023) cung cấp khung khái niệm "attributable to identified sources". Cả hai dùng **suy luận NLI (entailment)** làm thước đo — phù hợp hơn n-gram overlap (ROUGE/BLEU không bắt được "nguồn có hỗ trợ câu không").

### 2.3. Vì sao LLM-judge thay vì NLI tiếng Anh (lựa chọn thực tế)

ALCE gốc dùng mô hình NLI tiếng Anh (TRUE/T5-11B). **Với tiếng Việt, NLI off-the-shelf yếu** → exp02 thay bằng **gpt-4o làm judge entailment** (prompt nhị phân: "câu này có suy ra được từ đoạn nguồn không?"). Việc dùng LLM-judge được biện minh bởi:
- **Judging LLM-as-a-Judge** (Zheng 2023): LLM-judge đồng thuận với người ~80%, đủ tin cậy cho đánh giá NLG.
- **G-Eval** (Liu 2023): LLM-judge có chain-of-thought + rubric vượt các metric tự động truyền thống về tương quan với người.
- **TRUE** (Honovich 2022): hợp thức hóa việc dùng entailment (thay vì overlap) làm thước đo factual consistency/attribution.

### 2.4. Vì sao reference-free (không cần gold answer cho hầu hết metric)

Khác exp01 (có gold cứng `ma_thu_tuc`), tầng generation **khó có một "câu trả lời đúng duy nhất"** — một thủ tục có thể diễn đạt nhiều cách. Vì vậy bộ metric chọn theo hướng **reference-free** (RAGAS, ARES, ALCE đều reference-free): chấm câu trả lời **so với chính evidence/câu hỏi**, không so với một bản mẫu cứng. Chỉ **Completeness** cần reference (checklist) — và checklist này kéo bán tự động từ corpus có cấu trúc, không soạn tay từ đầu.

---

## 3. Tài nguyên & dữ liệu

### 3.1. Tận dụng lại từ exp01 (không làm lại)

| Tài nguyên | Vai trò trong exp02 |
|---|---|
| **210 câu GT** (`retrieval_gt.jsonl` 180 + `retrieval_gt_manual.jsonl` 30) | Dùng `question` làm input; `q_type` để phân nhóm; `gold_ma_thu_tuc` cho Context Recall/Completeness; 10 câu `out_of_scope` đo abstention |
| **Corpus có cấu trúc** (`metadata.jsonl`, `chunks.jsonl`) + hàm `gen_gt.py:load_corpus()` | Kéo checklist *hồ sơ/trình tự/phí* theo `gold_ma_thu_tuc` → reference cho Completeness (bán tự động) |
| **LLM-judge** = `AzureChatOpenAI(**flowsettings.KH_LLMS["azure"]["spec"])` | Đã chạy thật ở `gen_gt.py` → dùng làm judge cho mọi metric |
| **Bootstrap headless** (`App()` + `default_settings.flatten()` + lấy `FileIndex`) | Pattern khởi tạo từ `eval_retrieval.py` — tái dùng cho `gen_outputs.py` |
| **Format output** (`expNN_*/*.csv` + `*_summary.json`, `make_figures.py`, `make_report.py`) | exp02 đổ vào `exp02_generation/` cùng format |

### 3.2. Phải tạo mới

| Tài nguyên | Mô tả | Công sức |
|---|---|---|
| **`gen_outputs.jsonl`** | Chạy pipeline ReAct trên subset GT → lưu `(question, answer, contexts, citations, q_type, gold_ma_thu_tuc)` | 🟢 Thấp (port `query_test.py` + bootstrap exp01) |
| **Prompt judge** | Tách-claim, faithfulness, sinh-ngược-câu-hỏi, context-precision, citation-entailment | 🟡 Vừa |
| **Checklist gold** (~50 câu) | Bán tự động từ corpus sections | 🟡 Vừa |
| **Nhãn người** (~20–30 câu) | Kiểm độ đồng thuận judge↔người | 🟡 Vừa |

---

## 4. Thiết kế thí nghiệm

### 4.1. Cỡ mẫu & lấy mẫu phân tầng

- **Subset ~50–60 câu**, lấy **đều theo 6 nhóm `q_type`** (~8 câu/nhóm) + vài câu `out_of_scope`. Lấy mẫu phân tầng giữ tính **đa dạng truy vấn** (BEIR — Thakur 2021), tránh dồn về một dạng câu.
- **Vì sao không chạy đủ 210:** ReAct hai pha tốn ~8–20 lời gọi gpt-4o/câu (decompose + vòng agent + gate + synthesis), cộng ~11 call/câu để chấm → tổng ~4.000–6.500 call cho full. Subset 50 câu giảm chi phí ~4 lần.
- **Tính hợp lệ của subset:** với tỉ lệ nhị phân p≈0.85, CI 95% ≈ ±10% ở n=50 (so với ±5% ở n=210). Đây là đánh đổi chấp nhận được cho đồ án và **nhất quán với exp01** — vốn đã dùng n=20 cho bộ viết tay và ghi rõ "CI rộng, dùng để định hướng". Báo cáo exp02 sẽ **luôn kèm CI**, không nêu điểm trần trụi.

### 4.2. Cấu hình eval cố định (đảm bảo tái lập)

ReAct fan-out gọi LLM **không tất định** (số câu con, số vòng thay đổi) → cùng câu hỏi chạy hai lần có thể ra câu trả lời hơi khác. Để giảm dao động:
- Cố định `max_iterations`; **tắt mindmap** khi sinh output (tiết kiệm 1 call/câu, không ảnh hưởng metric).
- `gen_outputs.py` **cache resumable** (bỏ qua câu đã có — như `gen_gt.py`).
- Ghi rõ đây là **eval single-run** (một lần chạy), không phải trung bình nhiều lần — dao động LLM là hạn chế cố hữu.

### 4.3. So sánh engine (tùy chọn — giai đoạn 2)

`gen_outputs.py --engine {ReAct|simple}` → chạy cùng subset cho hai engine → chấm cùng bộ metric → bảng so sánh **ReAct vs Simple** trên faithfulness/citation/completeness. Phục vụ biện minh "vì sao ReAct là mặc định" (gần như miễn phí về công sức vì cùng script + metric).

---

## 5. Quy trình chấm & tối ưu chi phí

```
GT subset (~50 câu, phân tầng)
   │  ① gen_outputs.py: chạy ReAct → (q, answer, contexts, citations)   [TỐN NHẤT, cache 1 lần]
   ▼
gen_outputs.jsonl
   │  ② eval_generation.py: faithfulness / answer_relevance / context P-R   [RAGAS-style]
   │  ③ eval_citation.py:   citation recall / precision / F1               [ALCE-style]
   │  ④ eval_completeness.py: so checklist gold (subset nhỏ hơn)           [G-Eval-style]
   ▼
*_summary.json + *.csv + figures + report.html   (cùng format exp01)
```

**Đòn giảm call:**
- **Cache output** (bước ①): tuyệt đối không chạy lại pipeline khi đổi/thêm metric.
- **Batch phán đoán**: chấm toàn bộ context của một câu trong một prompt; gộp nhiều câu-citation vào một prompt structured-output (JSON list verdict).
- **Tách quy mô**: faithfulness/relevance/citation chạy ~50 câu; completeness (cần gold) quy mô nhỏ hơn.
- **Concurrency** có kiểm soát rate-limit Azure (giảm wall-clock, không giảm số call).

---

## 6. Hạn chế đã biết (ghi trước, minh bạch)

1. **LLM-judge không phải gold tuyệt đối:** faithfulness/answer-relevance/citation đều do gpt-4o chấm → có bias (position/verbosity — Zheng 2023). Giảm thiểu bằng **spot-check ~20–30 câu bằng người** để báo cáo độ đồng thuận judge↔người (giống cách exp01 dùng bộ viết tay kiểm chứng bộ tự sinh).
2. **Thiếu NLI tiếng Việt chất lượng** → dùng gpt-4o thay → judge và hệ sinh dùng chung họ model (gpt-4o), có thể có **thiên lệch tự đánh giá**; nêu rõ trong báo cáo.
3. **ReAct single-run** → kết quả dao động nhỏ giữa các lần chạy (bản chất fan-out + LLM).
4. **Subset n≈50** → CI ±10%; đủ kết luận tương đối, chưa đủ kết luận chặt như exp01 (n=180).
5. **Reference-free** cho hầu hết metric → đo "trung thực với nguồn", **không** đo "đúng pháp luật tuyệt đối" (nguồn corpus sai thì hệ vẫn faithful với nguồn sai). Đây là giới hạn cố hữu của faithfulness, không phải lỗi đo.

---

## 7. Tài liệu tham khảo

1. Es, S., et al. (2023). *RAGAS: Automated Evaluation of Retrieval Augmented Generation.* arXiv:2309.15217 (EACL 2024 demo). — **Faithfulness, Answer Relevance, Context Relevance (reference-free).**
2. Saad-Falcon, J., et al. (2024). *ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems.* NAACL 2024. — **context relevance / answer faithfulness / answer relevance + prediction-powered inference.**
3. Gao, T., Yen, H., Yu, J., & Chen, D. (2023). *Enabling Large Language Models to Generate Text with Citations (ALCE).* EMNLP 2023. — **Citation precision / recall qua NLI.**
4. Rashkin, H., et al. (2023). *Measuring Attribution in Natural Language Generation Models (AIS).* Computational Linguistics / TACL. — **khung attribution "attributable to identified sources".**
5. Min, S., et al. (2023). *FactScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation.* EMNLP 2023. — **tách claim nguyên tử để chấm factual precision.**
6. Liu, Y., et al. (2023). *G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment.* EMNLP 2023. — **LLM-judge có CoT + rubric cho metric không gold cứng.**
7. Zheng, L., et al. (2023). *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023 (Datasets & Benchmarks). — **tính hợp lệ & bias của LLM-judge.**
8. Honovich, O., et al. (2022). *TRUE: Re-evaluating Factual Consistency Evaluation.* NAACL 2022. — **NLI làm thước đo factual consistency/attribution.**
9. Asai, A., et al. (2024). *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.* ICLR 2024. — **citation precision/recall theo ALCE cho hệ RAG.**
10. Thakur, N., et al. (2021). *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of IR Models.* NeurIPS 2021 (Datasets & Benchmarks). — **đa dạng truy vấn (cơ sở lấy mẫu phân tầng theo q_type).**
11. Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval.* Cambridge University Press. — **Recall/Precision nền tảng.**

> Năm/venue nên đối chiếu lại khi đưa vào báo cáo chính thức (một số paper có bản arXiv và bản hội nghị khác năm). TruLens RAG Triad là công cụ/tài liệu kỹ thuật (TruEra/TruLens), không phải paper hội nghị — trích dưới dạng tài liệu công cụ.

---

## Phụ lục — Kế hoạch tái lập

```powershell
# 1. Sinh output pipeline (ReAct) trên subset GT phân tầng — TỐN NHẤT, cache resumable
.venv\Scripts\python.exe rag\eval\gen_outputs.py --engine ReAct --per-type 8     # ~50 câu
.venv\Scripts\python.exe rag\eval\gen_outputs.py --engine simple --per-type 8    # (tùy chọn) so sánh

# 2. Chấm
.venv\Scripts\python.exe rag\eval\eval_generation.py     # faithfulness / answer_relevance / context P-R
.venv\Scripts\python.exe rag\eval\eval_citation.py       # citation recall / precision / F1
.venv\Scripts\python.exe rag\eval\eval_completeness.py   # (tùy chọn) so checklist gold

# 3. Figure + báo cáo (tái dùng/điều chỉnh từ exp01)
.venv\Scripts\python.exe rag\eval\make_figures.py
.venv\Scripts\python.exe rag\eval\make_report.py
```

**Tệp dữ liệu (dự kiến):** `gen_outputs*.jsonl` (output pipeline) · `generation_results.csv` + `generation_summary.json` · `citation_results.csv` + `citation_summary.json` · `completeness_*.{csv,json}` · `figures/` · `report.html`.

**Thứ tự ưu tiên triển khai:** (1) `gen_outputs.py` → (2) `eval_generation.py` (faithfulness + answer relevance trước) → (3) `eval_citation.py` → (4) `eval_completeness.py` (nếu kịp gold) → (5) spot-check người.
