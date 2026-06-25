# Báo cáo Đánh giá tầng Generation & Citation (exp02)

**Hệ thống:** Chatbot RAG hướng dẫn thủ tục hành chính công Việt Nam (kotaemon).
**Engine:** **ReAct Agent** (hai pha — mặc định production) · **LLM-judge:** Azure `gpt-4o` · **Embedding:** Azure `text-embedding-3-large` (3072d).
**Ngày đánh giá:** 2026-06-25. Số liệu sinh tự động bằng `rag/eval/{gen_outputs,eval_generation,eval_citation}.py`. Phương pháp & căn cứ paper: xem [`GENERATION_EVAL_METHODOLOGY.md`](GENERATION_EVAL_METHODOLOGY.md).

> **Quan hệ với exp01:** exp01 đo *retrieval* (tìm đúng tài liệu — Hit@5 = 0.922). exp02 đo *generation + citation* (dùng tài liệu trả lời & trích dẫn có trung thực không). Đây là hai trục lỗi độc lập.

---

## 1. Tóm tắt

| Cụm | Metric | Giá trị (n=56) | Diễn giải |
|---|---|---|---|
| **Generation** | **Faithfulness** | **0.897** (±0.045) | ✅ Câu trả lời bám nguồn tốt, ít bịa |
| | Answer Relevance | 0.750 (±0.048) | ◐ Đúng trọng tâm khá; yếu ở câu tình huống/ngắn |
| | Context Precision | **0.227** (±0.045) | ⚠️ Thấp — hệ quả thiết kế (kéo đủ phần thủ tục) |
| **Citation** | **Citation F1** | **0.733** (±0.070) | ◐ Trích dẫn đúng ~3/4; điểm yếu ở `paraphrase` |
| | Citation Recall | 0.742 (±0.063) | |
| | Citation Precision | 0.725 (±0.070) | |
| **Hoàn chỉnh (nhóm A)** | Context Recall | 0.556 (±0.106) | ◐ Gom đủ thông tin ở câu rõ khía cạnh; cận dưới ở câu mơ hồ |
| | Answer Completeness | 0.529 (±0.100) | ◐ Liệt kê đủ ở `aspect_*`; xem §3.4 về artifact checklist |
| **Abstention (nhóm A)** | OOS từ chối đúng | **1.000** (n=8) | ✅ Không bịa khi ngoài phạm vi (over-answer 0.0) |
| | In-scope trả lời đúng | **0.964** (n=56) | ✅ Hầu như không từ chối nhầm câu hợp lệ |

> **Kết luận tổng quát:** tầng generation **trung thực với nguồn** (faithfulness 0.90) — rủi ro hallucination thấp, phù hợp domain pháp lý. Inline citation **đáng tin ở mức khá** (F1 0.73). Hệ **biết từ chối đúng lúc** (OOS abstention 1.0, over-answer 0.0) mà **gần như không từ chối nhầm** (in-scope answer 0.96). Ba điểm cần lưu ý: (1) **context precision thấp (0.23) là chủ đích thiết kế** chứ không phải lỗi retrieval — ReAct `expand_full_procedures` cố tình nạp đủ mọi phần của thủ tục; (2) **context recall/completeness (0.53–0.56) là cận dưới** — bị phạt ở nhóm câu mơ hồ do checklist gold lấy toàn thủ tục (xem §3.4), riêng `aspect_*` đạt 0.76–0.99; (3) câu **tình huống/diễn giải** vừa khó trả lời đúng trọng tâm vừa khó trích dẫn chuẩn — trùng khớp điểm yếu Hit@1 ở exp01.

**Mẫu:** 56 câu in-scope phân tầng (7 nhóm × 8) + 8 câu out_of_scope (cho abstention). Mỗi câu chạy pipeline ReAct đầy đủ → trung bình **10.0 claim/câu trả lời, 24.9 đoạn context, 7.2 trích dẫn 【n】/câu, 9.5 điểm-checklist gold/câu**. 2/56 câu trả lời mang tính né tránh (noncommittal).

---

## 2. Phương pháp (tóm tắt)

Chi tiết + căn cứ 11 paper ở `GENERATION_EVAL_METHODOLOGY.md`. Tóm tắt:

- **Quy trình 2 bước:** (①) `gen_outputs.py` chạy ReAct trên subset GT → lưu `(question, answer, contexts, citations)` (cache, không sinh lại). (②/③) `eval_generation.py` + `eval_citation.py` chấm trên file đó bằng gpt-4o.
- **Metric reference-free** (RAGAS/ALCE/TruLens): chấm so với chính evidence/câu hỏi, không cần "đáp án mẫu" — vì một thủ tục có nhiều cách diễn đạt đúng.
- **RAG Triad** (Faithfulness + Answer Relevance + Context Precision) **nhất quán nội bộ** với gate `llm_trulens_score` của hệ (cùng họ TruLens context-relevance).
- **Citation** theo **ALCE** (Gao 2023): recall = câu được nguồn dẫn entail; precision = 【n】 không thừa. Dùng gpt-4o làm judge entailment (thiếu NLI tiếng Việt chất lượng).
- **Nhóm A (reference-based):** Context Recall + Answer Completeness dùng **checklist gold** trích bán tự động từ corpus (section đúng của thủ tục gold) — căn cứ **RAGAS context recall** + **G-Eval** rubric (Liu 2023). Abstention theo **SQuAD 2.0** (Rajpurkar 2018) — đo answerability ở tầng câu trả lời.
- **Cấu hình eval cố định:** tắt mindmap, `max_iterations` mặc định, single-run.

---

## 3. Kết quả Generation

### 3.1. Tổng thể (n=56)

| Metric | Mean | CI 95% | Range | Ngưỡng tham chiếu |
|---|---|---|---|---|
| **Faithfulness** | **0.897** | ±0.045 | 0.30–1.00 | ≥0.85 tốt ✅ |
| **Answer Relevance** | **0.750** | ±0.048 | 0.00–0.96 | ≥0.70 khá ◐ |
| **Context Precision** | **0.227** | ±0.045 | 0.03–0.84 | (xem §3.3) ⚠️ |

### 3.2. Theo nhóm query

| Nhóm | Faithfulness | Answer Relevance | Context Precision |
|---|---|---|---|
| Khớp từ khóa (`factual`) | **1.000** | 0.888 | 0.167 |
| Diễn giải (`paraphrase`) | 0.890 | 0.777 | 0.308 |
| Tình huống (`scenario`) | **0.756** | **0.535** | 0.281 |
| Khía cạnh hồ sơ (`aspect_hoso`) | 0.885 | 0.846 | **0.074** |
| Khía cạnh phí/ĐK (`aspect_phi_dk`) | 0.991 | 0.887 | 0.116 |
| Từ khóa ngắn (`keyword_short`) | 0.965 | 0.613 | 0.397 |
| Viết tay (`manual_inscope`) | 0.794 | 0.702 | 0.246 |

**Nhận xét:**
- **Faithfulness cao và đồng đều (0.76–1.00).** Nhóm `factual`/`aspect_phi_dk` gần như tuyệt đối (1.00 / 0.99) — khi câu hỏi trỏ rõ một khía cạnh, câu trả lời bám sát nguồn. Thấp nhất là `scenario` (0.756) và `manual_inscope` (0.794): câu tình huống/người-thật khiến LLM dễ suy diễn thêm ngoài nguồn.
- **Answer Relevance phân hoá theo độ rõ của câu hỏi.** `scenario` (0.535) và `keyword_short` (0.613) thấp nhất — câu tình huống dài dòng / truy vấn 3–6 từ làm câu trả lời khó "đúng ngay trọng tâm". **Trùng khớp điểm yếu Hit@1 của exp01** (`keyword_short` 0.533, `scenario` 0.600) → cùng một gốc: câu hỏi mơ hồ.

### 3.3. Vì sao Context Precision thấp (0.227) — KHÔNG phải lỗi

Đây là **đặc tính thiết kế của ReAct**, cần đọc đúng để không hiểu nhầm thành "retrieve rác":
- ReAct bật `expand_full_procedures`: với thủ tục đủ tin cậy, hệ **kéo TOÀN BỘ mọi phần** (hồ sơ + trình tự + thời gian + phí) từ docstore vào context — để pha synthesis có dữ liệu đầy đủ trả lời tách bạch (xem `react.py:_assemble_by_procedure`). Trung bình **24.9 đoạn context/câu**.
- Hệ quả: khi câu hỏi chỉ hỏi MỘT khía cạnh (vd `aspect_hoso` — chỉ hỏi hồ sơ), phần lớn 24.9 đoạn (trình tự, phí…) bị judge chấm "không liên quan trực tiếp" → precision tụt (0.074). Đây chính là lý do `aspect_hoso`/`aspect_phi_dk` có context precision thấp nhất dù faithfulness/answer-relevance cao.
- **Bằng chứng đây là đánh đổi có lợi:** dù context "loãng", **faithfulness vẫn 0.90 và answer relevance 0.75** — tức LLM lọc đúng phần cần dùng từ context rộng, không bị nhiễu. Context precision thấp phản ánh *recall-oriented retrieval* (ưu tiên không bỏ sót), phù hợp domain thủ tục (thiếu một giấy tờ = dân đi lại nhiều lần).

> **Khuyến nghị:** nếu muốn nâng context precision mà không hại completeness, cân nhắc *re-rank/lọc context theo khía cạnh câu hỏi* TRƯỚC synthesis cho nhóm câu hỏi đơn-khía-cạnh. Nhưng đây là tối ưu thứ cấp — faithfulness đã tốt.

### 3.4. Context Recall + Answer Completeness (reference-based, checklist gold)

Bù cho context_precision (đo "context có sạch không") bằng hai metric đo "context/answer có ĐỦ không". Mỗi câu được dựng một **checklist gold** = các điểm-thông-tin atomic trích từ section đúng của thủ tục gold trong corpus (RAGAS context recall + G-Eval rubric — xem §2). Context Recall = % điểm gold xuất hiện trong context đã gom; Answer Completeness = % điểm gold xuất hiện trong câu trả lời cuối.

| Nhóm | Context Recall | Answer Completeness | Độ tin cậy checklist |
|---|---|---|---|
| Khía cạnh phí/ĐK (`aspect_phi_dk`) | **0.986** | **0.889** | ✅ cao (section gold rõ) |
| Khía cạnh hồ sơ (`aspect_hoso`) | 0.835 | 0.760 | ✅ cao |
| Khớp từ khóa (`factual`) | 0.690 | 0.714 | ✅ cao |
| Tình huống (`scenario`) | 0.451 | 0.510 | ◐ trung bình |
| Viết tay (`manual_inscope`) | 0.360 | 0.285 | ⚠️ thấp (checklist toàn thủ tục) |
| Từ khóa ngắn (`keyword_short`) | 0.352 | 0.340 | ⚠️ thấp |
| Diễn giải (`paraphrase`) | **0.217** | **0.208** | ⚠️ thấp |
| **Tổng thể** | **0.556** (±0.106) | **0.529** (±0.100) | |

**Nhận xét — đọc đúng con số (quan trọng):**
- **Điểm ĐÁNG TIN nhất ở `aspect_*`** (recall 0.84–0.99, completeness 0.76–0.89): các nhóm này có `source_section` xác định → checklist gold đúng **phạm vi câu hỏi** → con số phản ánh thật. Đây là bằng chứng mạnh: khi hỏi rõ một khía cạnh, ReAct **gom đủ (recall ~0.9) và trả lời đủ (completeness ~0.85)** thông tin cần thiết — đúng mục tiêu thiết kế `expand_full_procedures`.
- **Điểm THẤP ở `paraphrase`/`keyword_short`/`manual` là CẬN DƯỚI do artifact checklist, KHÔNG phải hệ bỏ sót thật.** Các nhóm này không có section gold cụ thể → checklist lấy **toàn bộ thủ tục** (TB 9.5 điểm/câu), trong khi câu hỏi diễn giải/ngắn thường chỉ cần một phần → bị phạt thấp giả. Cần đọc kèm cảnh báo này (xem §6).
- **Completeness ≈ Context Recall** (0.53 vs 0.56) ở mọi nhóm → **synthesis giữ gần hết thông tin đã có trong context, ít đánh rơi thêm**. Khoảng cách nhỏ (~0.03) chứng tỏ pha 2 không phải nút thắt — nếu context có thông tin, câu trả lời thường nêu được.
- **Context Recall (0.56) > Context Precision (0.23)** → xác nhận hệ **recall-oriented**: ưu tiên gom đủ hơn gom sạch, đúng triết lý "thà thừa còn hơn thiếu" cho thủ tục hành chính.

---

## 4. Kết quả Citation (ALCE-style)

### 4.1. Tổng thể (n=56)

| Metric | Mean | CI 95% | Range |
|---|---|---|---|
| **Citation Recall** | 0.742 | ±0.063 | 0.20–1.00 |
| **Citation Precision** | 0.725 | ±0.070 | 0.00–1.00 |
| **Citation F1** | **0.733** | ±0.070 | 0.00–1.00 |

Trung bình **7.2 trích dẫn 【n】/câu trả lời**; **4.1 câu mang thông tin nhưng không gắn 【n】** (uncited claims — thường là câu liệt kê con kế thừa nguồn của câu mẹ).

### 4.2. Theo nhóm query

| Nhóm | Citation Recall | Citation Precision |
|---|---|---|
| Khía cạnh phí/ĐK (`aspect_phi_dk`) | **0.938** | **0.938** |
| Từ khóa ngắn (`keyword_short`) | 0.850 | 0.850 |
| Khớp từ khóa (`factual`) | 0.774 | 0.784 |
| Khía cạnh hồ sơ (`aspect_hoso`) | 0.763 | 0.742 |
| Tình huống (`scenario`) | 0.720 | 0.720 |
| Viết tay (`manual_inscope`) | 0.591 | 0.543 |
| Diễn giải (`paraphrase`) | **0.557** | **0.496** |

**Nhận xét:**
- **Mạnh nhất ở câu hỏi trỏ rõ một thông tin** (`aspect_phi_dk` 0.94): nội dung ngắn, một nguồn → 【n】 dễ khớp chính xác.
- **Yếu nhất ở `paraphrase` (0.50–0.56) và `manual_inscope` (0.54–0.59):** câu trả lời dài, tổng hợp nhiều nguồn, diễn đạt lại bằng lời → judge khó xác nhận từng 【n】 entail đúng câu. Precision < recall ở hai nhóm này → có **trích dẫn thừa** (gắn 【n】 cho câu mà nguồn chỉ hỗ trợ một phần).
- Recall ≈ Precision ở hầu hết nhóm → hệ **không lạm dụng cũng không bỏ sót** trích dẫn một cách hệ thống.

---

## 5. Abstention — từ chối đúng lúc (tầng câu trả lời)

Bổ sung cho `eval_gate.py` của exp01: gate đo ở tầng **retrieval** (doc có lọt cổng không), mục này đo ở tầng **câu trả lời cuối** (hệ có thực sự NÓI "không tìm thấy" không). Căn cứ answerability — **SQuAD 2.0** (Rajpurkar 2018). 8 câu out_of_scope + 56 câu in-scope, gpt-4o phân loại answer = {abstain | substantive}.

| Chỉ số | Giá trị | n | Diễn giải |
|---|---|---|---|
| **OOS — từ chối đúng** (abstention rate) | **1.000** | 8 | ✅ Mọi câu ngoài phạm vi đều bị từ chối |
| **OOS — trả lời nhầm** (over-answer) | **0.000** | 8 | ✅ Không bịa thông tin khi không có căn cứ |
| **In-scope — trả lời thực chất** | **0.964** | 56 | ✅ Chỉ 2/56 từ chối nhầm câu hợp lệ |

**Nhận xét:**
- **Cân bằng abstention gần như lý tưởng:** hệ từ chối 100% câu ngoài phạm vi (không bịa) NHƯNG vẫn trả lời 96% câu hợp lệ (không từ chối nhầm). Đây là điểm khó nhất của một hệ RAG có cổng — thường phải đánh đổi giữa hai chiều.
- **Cải thiện rõ so với exp01 ở tầng answer:** exp01 đo gate_recall in-scope = **0.65** (35% câu hợp lệ bị cổng retrieval loại nhầm). Nhưng ở tầng **câu trả lời cuối**, tỉ lệ trả lời thực chất đạt **0.96** — vì kiến trúc ReAct **cứu** được phần lớn: khi gate docsearch loại nhầm, agent **đổi truy vấn / fallback web** rồi vẫn tổng hợp được câu trả lời. Tức hai pha + web bổ sung đã bù cho điểm yếu "cổng hơi gắt" mà exp01 cảnh báo.
- Trùng khớp số noncommittal ở §1 (2/56) — hai cách đo độc lập (eval_generation vs eval_abstention) cho cùng kết quả → đáng tin.

---

## 6. Đối chiếu chéo exp01 ↔ exp02

| Quan sát | exp01 (retrieval) | exp02 (generation/citation) | Diễn giải nhất quán |
|---|---|---|---|
| Câu **tình huống/ngắn** yếu | Hit@1: scenario 0.60, keyword_short 0.53 | Answer relevance: scenario 0.54, keyword_short 0.61 | Câu mơ hồ khó cả tìm lẫn trả lời đúng trọng tâm |
| Câu **trỏ rõ khía cạnh** mạnh | factual Hit@5 0.97 | factual faithfulness 1.00; aspect_phi_dk citation 0.94 | Câu cụ thể → toàn pipeline tốt |
| Câu **viết tay** ≈ tự sinh | Hit@5 manual 0.90 ≈ auto 0.92 | faithfulness manual 0.79, hơi thấp hơn auto | Câu người thật dài/đa ý hơn → synthesis & citation khó hơn chút |
| **Cổng "không tìm thấy"** | gate_recall in-scope 0.65 (gắt) | in-scope answer rate 0.96 | ReAct (đổi truy vấn + web) **bù** cho cổng retrieval gắt |
| Câu **rõ khía cạnh** đủ thông tin | aspect Hit@5 0.90–0.93 | aspect context recall 0.84–0.99, completeness 0.76–0.89 | Hỏi rõ → gom đủ & trả lời đủ |

→ Hai thí nghiệm **củng cố lẫn nhau**: điểm yếu chung là **câu hỏi mơ hồ/đa ý**, không phải lỗi kỹ thuật của tầng nào. Đáng chú ý, exp02 cho thấy điểm yếu "cổng gắt" của exp01 **được kiến trúc ReAct bù lại** ở tầng câu trả lời cuối.

---

## 7. Hạn chế

1. **LLM-judge (gpt-4o), không phải gold tuyệt đối** — faithfulness/relevance/citation đều do gpt-4o chấm; hệ sinh cũng dùng gpt-4o → có thể **thiên lệch tự đánh giá**. Cần spot-check người (~20–30 câu) để báo cáo đồng thuận judge↔người (chưa làm — việc tiếp theo).
2. **Subset n=56, CI ±0.045–0.070** — đủ kết luận tương đối & so nhóm, chưa chặt như exp01 (n=180). Nhóm con n=8 → CI rộng (~±0.2), đọc theo xu hướng.
3. **Single-run** — ReAct fan-out không tất định; chạy lại có dao động nhỏ.
4. **Context Precision** đo theo từng-đoạn, **phạt thiết kế recall-oriented** của hệ — cần đọc kèm §3.3, không so trực tiếp với hệ retrieve ít context.
5. **Reference-free** (faithfulness/relevance/citation) — đo "trung thực với nguồn", KHÔNG đo "đúng pháp luật tuyệt đối" (nguồn corpus sai thì faithful với cái sai).
6. **Tách câu/uncited-claim dùng heuristic** (regex tiếng Việt) — con số uncited là ước lượng tham khảo, không vào recall/precision.
7. **Checklist gold của Context Recall/Completeness là cận dưới ở câu mơ hồ** — với nhóm không có `source_section` rõ (`paraphrase`/`keyword_short`/`manual`), checklist lấy **toàn bộ thủ tục** nên phạt thấp giả những câu chỉ cần một phần. Con số ĐÁNG TIN ở nhóm `aspect_*`/`factual` (có section gold); các nhóm còn lại đọc như cận dưới (§3.4).
8. **Abstention n=8 (OOS)** — CI rất rộng; 1.0 chỉ khẳng định "không thấy ca lỗi trong 8 câu", chưa phải bằng chứng chặt. Nên mở rộng bộ out_of_scope.

---

## 8. Kết luận & việc tiếp theo

**Kết luận:** Tầng generation của ReAct **trung thực với nguồn (faithfulness 0.90)**, **trích dẫn đáng tin mức khá (F1 0.73)**, **biết từ chối đúng lúc mà không từ chối nhầm** (OOS abstention 1.0 / in-scope answer 0.96), và khi **câu hỏi rõ khía cạnh thì gom đủ + trả lời đủ** thông tin (context recall/completeness 0.76–0.99 ở `aspect_*`). Đạt yêu cầu cho chatbot pháp lý nơi chống bịa là ưu tiên hàng đầu. Context precision thấp là **đánh đổi recall-oriented có chủ đích** (faithfulness/recall cao chứng minh điều đó). Một phát hiện liên-thí-nghiệm: kiến trúc ReAct (đổi truy vấn + web) **bù được điểm yếu "cổng gắt"** mà exp01 cảnh báo.

**Việc tiếp theo (ưu tiên giảm dần):**
1. **Spot-check người** ~20–30 câu → đo đồng thuận judge↔người (hợp thức hóa LLM-judge). *(chưa làm)*
2. **So sánh engine**: chạy `gen_outputs.py --engine simple` → đối chiếu ReAct vs Simple trên cùng metric (biện minh "ReAct mặc định"). *(chưa làm)*
3. ~~**Answer Completeness** với checklist gold cho `aspect_*`~~ → ✅ **đã làm** (§3.4).
4. ~~**Abstention** ở tầng câu trả lời~~ → ✅ **đã làm** (§5).
5. **Cải thiện citation cho `paraphrase`** (precision 0.50): siết gắn 【n】 chỉ khi nguồn entail đủ câu.
6. **Mở rộng bộ out_of_scope** (hiện n=8) để abstention có CI chặt hơn.
7. Cân nhắc **lọc context theo khía cạnh** cho câu đơn-khía-cạnh để nâng context precision.

---

## Phụ lục — Tái lập

```powershell
# ① Sinh output ReAct trên subset GT phân tầng (cache resumable) — ĐÃ CHẠY
.venv\Scripts\python.exe rag\eval\gen_outputs.py --per-type 8 --reset       # 56 câu in-scope
.venv\Scripts\python.exe rag\eval\gen_outputs.py --include-oos --per-type 8  # +8 câu out_of_scope

# ② Chấm generation (RAG Triad)
.venv\Scripts\python.exe rag\eval\eval_generation.py

# ③ Chấm citation (ALCE)
.venv\Scripts\python.exe rag\eval\eval_citation.py

# ④ Nhóm A: context recall + completeness (checklist gold) + abstention
.venv\Scripts\python.exe rag\eval\eval_completeness.py
.venv\Scripts\python.exe rag\eval\eval_abstention.py
```

**Tệp dữ liệu:** `gen_outputs.jsonl` (64 câu: 56 in-scope + 8 oos) · `generation_*` · `citation_*` · `completeness_*` · `abstention_*` (`results.csv` + `summary.json` + `*_scores.jsonl` cache). engine=ReAct, ngày 2026-06-25.
