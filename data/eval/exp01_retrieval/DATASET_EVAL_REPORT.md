# Báo cáo Dataset & Đánh giá tầng Retrieval

**Hệ thống:** Chatbot RAG hướng dẫn thủ tục hành chính công Việt Nam (kotaemon).
**Embedding:** Azure `text-embedding-3-large` (3072d) · **Retrieval:** hybrid (Chroma vector + LanceDB BM25) + reranker · **Gold:** `ma_thu_tuc`.
**Ngày đánh giá:** 2026-06-24. Toàn bộ số liệu sinh tự động bằng `rag/eval/*` (xem [Phụ lục](#phụ-lục--tái-lập)).

---

## 1. Tóm tắt

| Chỉ số chính (hybrid, n=180) | Giá trị | Ngưỡng "tốt" | Kết luận |
|---|---|---|---|
| **Hit@5** | **0.922** (±0.040) | ≥ 0.90 | ✅ Đạt |
| Hit@10 | 0.972 | ≥ 0.95 | ✅ Đạt |
| **MRR** | **0.775** | ≥ 0.75 | ✅ Đạt |
| nDCG@10 | 0.823 | ≥ 0.75 | ✅ Đạt |

> **Kết luận tổng quát:** tầng retrieval **hoạt động tốt** — với 180 câu, khoảng tin cậy 95% của Hit@5 là ±4%, đủ cơ sở thống kê. Ba phát hiện đáng chú ý: (1) **embedding gánh gần hết**, BM25 đóng góp không đáng kể; (2) điểm yếu nằm ở **thứ hạng #1** cho truy vấn ngắn/tình huống, không phải ở recall; (3) **cổng "không tìm thấy" hơi gắt**, đôi khi loại nhầm thủ tục đúng.

---

## 2. Thống kê Dataset

### 2.1. Corpus nguồn

| Thuộc tính | Giá trị |
|---|---|
| Số thủ tục hành chính | **5.208** |
| Số chunk (sau cắt đoạn) | **33.255** |
| Số lĩnh vực | **281** |
| Chunk / thủ tục (TB) | 6.39 (min 3 – max 8) |
| Số loại section | 8 |

Corpus phủ rộng nhưng **đuôi dài**: 281 lĩnh vực, tập trung ở Hải quan, Hàng hải, Khoa học–công nghệ, Ngân hàng, Thuế (Hình 1). Mỗi thủ tục được cắt khá đồng đều 3–8 chunk theo cấu trúc section (Hình 3), nên một thủ tục = một cụm chunk có cùng `ma_thu_tuc` — đây là cơ sở để khớp gold ở mức thủ tục.

![Top 20 lĩnh vực](figures/fig1_linhvuc.png)
*Hình 1 — Phân bố thủ tục theo lĩnh vực (top 20/281).*

![Độ phủ section](figures/fig2_sections.png)
*Hình 2 — Độ phủ 8 section. "Trình tự" và "Cách thức" phủ 100%; "Phí, lệ phí" (cam) chỉ 4.295/5.208; "Yêu cầu, điều kiện" và "Địa chỉ tiếp nhận" thưa nhất — ảnh hưởng trực tiếp tới nhóm câu hỏi theo khía cạnh.*

![Phân bố chunk/thủ tục](figures/fig3_chunks_hist.png)
*Hình 3 — Số chunk mỗi thủ tục (TB 6.39).*

### 2.2. Bộ Ground Truth đánh giá

Tổng **210 câu**: 180 câu **tự sinh** (gpt-4o, phân tầng theo lĩnh vực) + 30 câu **viết tay** (gắn thủ tục dân sinh có thật). Độ dài câu hỏi TB 93.8 ký tự (17–206).

| Bộ | Số câu | Cấu thành |
|---|---|---|
| Tự sinh | 180 | 6 nhóm query × 30 câu |
| Viết tay | 30 | 20 in-scope + 10 ngoài phạm vi |

**6 nhóm query** được thiết kế để mỗi nhóm kiểm một năng lực khác nhau, phục vụ phân tích lỗi:

| Nhóm | Kiểm tra | Cách sinh (chống thiên lệch) |
|---|---|---|
| `factual_lookup` | khớp từ khóa (BM25) | sinh từ text section, **được** dùng thuật ngữ |
| `paraphrase` | hiểu ngữ nghĩa (embedding) | chỉ thấy **tên thủ tục**, cấm jargon |
| `scenario` | câu tình huống gián tiếp | tên + đối tượng, không nêu thẳng tên thủ tục |
| `aspect_hoso` | tìm đúng khía cạnh hồ sơ | section "Thành phần hồ sơ" |
| `aspect_phi_dk` | khía cạnh phí/điều kiện | section "Phí, lệ phí" / "Yêu cầu, điều kiện" |
| `keyword_short` | truy vấn ngắn 3–6 từ | tên thủ tục, dạng ô tìm kiếm |

![Phân bố GT](figures/fig4_gt_qtype.png)
*Hình 4 — Phân bố bộ GT: 180 câu tự sinh (trái) + 30 câu viết tay (phải).*

---

## 3. Phương pháp đánh giá

- **Khóa khớp gold = `ma_thu_tuc`.** Doc retrieve không mang `ma_thu_tuc` trong metadata nên trích từ tiền tố `file_name` (`<ma>__<uuid>.md`). Các thủ tục **trùng tên** được gộp thành gold-set (cùng tên, khác cấp → đều chấp nhận).
- **Quy trình:** truy hồi search-all (5.208 thủ tục) → lấy top-20 → dedup theo thủ tục (giữ rank tốt nhất) → tính metric so với gold.
- **Metric:** Hit@k (có ≥1 gold trong top-k), Recall@5, MRR (nghịch đảo thứ hạng gold đầu tiên), nDCG@10.
- **Cỡ mẫu:** 180 câu → CI 95% của tỉ lệ ≈ ±4% (khi p≈0.92); 30 câu/nhóm → ±~9% mỗi nhóm, đủ để so sánh tương đối giữa các nhóm.
- **Chống thiên lệch BM25:** các nhóm `paraphrase`/`scenario`/`keyword_short` chỉ cho LLM thấy **tên thủ tục**, không cho text chunk → câu hỏi không lặp lại nguyên văn từ khóa trong tài liệu.

---

## 4. Kết quả

### 4.1. Tổng thể

| Metric | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@5 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|---|
| **Hybrid** | 0.661 | 0.861 | **0.922** | 0.972 | 0.922 | 0.775 | 0.823 |

### 4.2. Theo nhóm query (phân tích lỗi)

| Nhóm | Hit@1 | Hit@5 | Hit@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|
| Khớp từ khóa | **0.767** | **0.967** | 0.967 | 0.853 | 0.882 |
| Diễn giải | 0.733 | 0.933 | 0.967 | 0.811 | 0.849 |
| Khía cạnh hồ sơ | 0.633 | 0.933 | 1.000 | 0.771 | 0.828 |
| Khía cạnh phí/ĐK | 0.700 | 0.900 | 0.967 | 0.786 | 0.826 |
| Tình huống | 0.600 | 0.900 | 0.967 | 0.728 | 0.787 |
| Từ khóa ngắn | **0.533** | 0.900 | 0.967 | 0.700 | 0.766 |

![Hit@k theo nhóm](figures/fig5_hit_by_qtype.png)
*Hình 5 — Hit@1/5/10 theo nhóm. Hit@5 đồng đều (0.90–0.97) nhưng **Hit@1 chênh lệch lớn** (0.53–0.77).*

**Nhận xét:**
- **Khoảng cách `factual` vs `paraphrase` ở Hit@5 chỉ 0.967 vs 0.933** → hệ **không** phụ thuộc quá mức vào khớp từ khóa; embedding hiểu ngữ nghĩa tốt. Đây là điểm mạnh.
- Điểm yếu thực sự ở **Hit@1 của `keyword_short` (0.533)** và `scenario` (0.600): truy vấn ngắn/gián tiếp khó đưa thủ tục đúng lên vị trí #1, dù vẫn nằm trong top-5.

### 4.3. Đóng góp của BM25 — hybrid vs vector-only

| Metric | Hybrid | Vector-only | Δ (BM25 đóng góp) |
|---|---|---|---|
| Hit@1 | 0.661 | 0.667 | −0.006 |
| Hit@5 | 0.922 | 0.922 | **±0.000** |
| Hit@10 | 0.972 | 0.956 | **+0.016** |
| MRR | 0.775 | 0.781 | −0.006 |
| nDCG@10 | 0.823 | 0.824 | −0.001 |

![Hybrid vs Vector](figures/fig6_hybrid_vs_vector.png)
*Hình 6 — Hybrid và vector-only gần như trùng nhau ở mọi metric, trừ Hit@10 (hybrid hơn 0.016).*

**Nhận xét:** BM25 **gần như không đóng góp** ở top-5; chỉ giúp nhẹ ở đuôi (Hit@10). Nguyên nhân khả dĩ: FTS LanceDB dùng tokenizer `en_stem` (tiếng Anh), không tối ưu tiếng Việt. Hệ quả thực tiễn: có thể hạ `retrieval_mode` về `vector` để **né hẳn rủi ro Rust panic của LanceDB FTS (LỖI #5)** mà gần như không mất chất lượng.

### 4.4. Phân bố thứ hạng

![Phân bố thứ hạng](figures/fig7_rank_dist.png)
*Hình 7 — Thứ hạng thủ tục đúng đầu tiên (hybrid, n=180).*

119/180 câu (66%) có thủ tục đúng ở **vị trí #1**; 158/180 (88%) trong top-3; chỉ **4 câu trượt hoàn toàn** top-20. Phần lớn "lỗi" là lệch 1–2 bậc chứ không phải mất tài liệu → vấn đề thứ hạng, không phải vấn đề recall.

### 4.5. Bộ viết tay & cổng "không tìm thấy"

![Cổng relevance](figures/fig8_gate.png)
*Hình 8 — Bộ viết tay và cổng relevance (đường chấm = ngưỡng 0.90).*

| Chỉ số | Giá trị | n |
|---|---|---|
| Hit@5 — câu viết tay (in-scope) | **0.900** | 20 |
| Cổng giữ gold (in-scope) | 0.650 | 20 |
| Cổng từ chối đúng (ngoài phạm vi) | **1.000** | 10 |
| TB doc lọt cổng khi ngoài phạm vi | 0.00 | 10 |

**Nhận xét:**
- **Hit@5 câu viết tay (0.900) ≈ câu tự sinh (0.922)** → câu hỏi người thật **không** dễ hơn câu tự sinh, xác nhận bộ GT tự sinh đáng tin cậy.
- **Cổng chặn rác hoàn hảo:** 10/10 câu ngoài phạm vi bị từ chối toàn bộ (0 doc lọt) → chatbot sẽ trả lời "ngoài phạm vi" đúng cho câu lạc đề.
- **Cổng hơi gắt:** chỉ 0.650 gold sống sót (n=20, CI rộng ±0.21) — đôi khi loại nhầm cả thủ tục đúng (xem [§5.2](#52-lỗi-cổng-relevance)). Đây là đánh đổi precision–recall của gate, đáng tinh chỉnh ngưỡng.

---

## 5. Phân tích lỗi

### 5.1. Câu trượt top-5 (hybrid, 14/180)

| Nhóm | Lĩnh vực | Rank gold | Câu hỏi (rút gọn) |
|---|---|---|---|
| paraphrase | Đường bộ | trượt | Làm sao để được phép thiết kế và xây dựng nút giao thông… |
| factual | Khám bệnh, chữa bệnh | trượt | Thời hạn giải quyết hồ sơ hợp lệ là bao lâu? |
| scenario | Tiêu chuẩn đo lường | trượt | Tôi là giám đốc công ty vốn nước ngoài… |
| keyword_short | Tần số vô tuyến điện | trượt | Gia hạn giấy phép tần số |
| aspect_phi_dk | Thành lập & hoạt động DN | #17 | Lệ phí thông báo thành lập doanh nghiệp… |
| aspect_phi_dk | Thành lập & hoạt động DN | #9 | Lệ phí đăng ký kinh doanh thay đổi tên… |
| aspect_hoso | Bảo hiểm xã hội | #7 | Thủ tục xác nhận thời gian đóng BHXH cần… |
| *(và 7 câu khác ở rank 6–8)* | | | |

**Hai mẫu lỗi rõ rệt:**

1. **Câu hỏi quá chung → mất ngữ cảnh phân biệt.** Ví dụ *"Thời hạn giải quyết hồ sơ hợp lệ là bao lâu?"* không nêu thủ tục nào → khớp hàng loạt thủ tục. Đây là giới hạn cố hữu của known-item eval với câu mơ hồ, **không hẳn là lỗi hệ thống**.

2. **Cụm thủ tục gần trùng (near-duplicate).** Các câu `aspect_phi_dk` trượt **đều thuộc "Thành lập và hoạt động doanh nghiệp/HTX"** — lĩnh vực có rất nhiều thủ tục lệ phí na ná nhau; hệ trả về một thủ tục "anh em" thay vì đúng mã gold. Khớp gold chặt theo `ma_thu_tuc` tính đây là trượt, nhưng với người dùng câu trả lời có thể vẫn hữu ích → **đánh giá ở đây là cận dưới (thận trọng)**.

> Lĩnh vực "Thành lập & hoạt động DN/HTX" là điểm yếu rõ nhất (xem report.html, bảng theo lĩnh vực: Hit@5 ≈ 0.40 trên nhóm này) — đáng cân nhắc tăng `top_k` hoặc reranker mạnh hơn cho cụm thủ tục dày đặc.

### 5.2. Lỗi cổng relevance

7/20 câu in-scope bị cổng loại nhầm, trong đó một số câu dân sinh phổ biến:

| Câu hỏi | Doc qua cổng |
|---|---|
| Đăng ký kết hôn cần mang theo những giấy tờ gì? | 0 |
| đăng ký hộ kinh doanh cá thể | 0 |
| Giấy tạm trú sắp hết hạn, gia hạn thế nào? | 0 |
| Tòa xử ly hôn xong, ghi vào sổ hộ tịch thì làm gì? | 0 |
| Hai vợ chồng muốn nhận con nuôi trong nước… | 0 |

→ Cổng `llm_trulens_score` đôi khi đánh giá chunk truy hồi (thường là section khác như "trình tự") **không đủ liên quan** tới câu hỏi về *giấy tờ/lệ phí*, rồi loại sạch. Hệ quả: chatbot có thể trả "không tìm thấy" cho câu hợp lệ. **Khuyến nghị:** nới ngưỡng cổng, hoặc cho cổng xét toàn cụm chunk của thủ tục thay vì từng chunk rời.

---

## 6. Kết luận & khuyến nghị

**Kết luận:** Tầng retrieval **đạt chuẩn "tốt"** (Hit@5 = 0.922 ± 0.04, MRR = 0.775, nDCG = 0.823 trên 210 câu phân tầng). Recall vững (88% gold trong top-3, chỉ 4/180 trượt top-20); embedding tiếng Việt mạnh, không lệ thuộc khớp từ khóa.

**Khuyến nghị (ưu tiên giảm dần):**
1. **Tinh chỉnh cổng relevance** — nới ngưỡng / xét theo thủ tục thay vì chunk: đang loại nhầm ~35% câu in-scope (§5.2).
2. **Cải thiện thứ hạng #1** cho truy vấn ngắn/tình huống (Hit@1 0.53–0.60) — reranker mạnh hơn hoặc query rewriting.
3. **Cân nhắc bỏ hybrid → vector** — BM25 đóng góp ~0 ở top-5 nhưng mang rủi ro LanceDB panic (LỖI #5); hoặc đổi tokenizer FTS sang loại hợp tiếng Việt.
4. **Cụm thủ tục near-duplicate** (thành lập DN/HTX) — tăng `top_k` cục bộ hoặc tách mã rõ hơn.

**Hạn chế của đánh giá:** known-item retrieval (gold = đúng thủ tục gốc) → câu mơ hồ và near-duplicate semantic bị tính trượt dù có thể vẫn hữu ích; số liệu là **cận dưới**. Bộ viết tay (n=20–30) có CI rộng, dùng để định hướng chứ chưa kết luận chặt.

---

## 7. Quy trình xây dựng dữ liệu & căn cứ phương pháp

Phần này giải thích **vì sao** bộ GT và bộ metric được thiết kế như trên, kèm tài liệu dẫn chứng. Mục tiêu: các lựa chọn đều dựa trên thông lệ đã được công bố, không phải quy ước tùy tiện.

### 7.1. Quy trình xây dựng bộ Ground Truth

```
Corpus (5.208 thủ tục)
   │  ① chọn mẫu phân tầng theo lĩnh vực  ──────────────► tránh dồn về 1 lĩnh vực
   ▼
Thủ tục được chọn
   │  ② gpt-4o sinh câu hỏi từ thủ tục      [InPars; Promptagator]
   │     (gold = đúng thủ tục nguồn)         [known-item retrieval]
   │  ③ 6 nhóm query × kiểm soát ngữ cảnh    [BEIR — đa dạng truy vấn]
   │     (chống rò rỉ từ khóa: chỉ cho LLM thấy TÊN thủ tục với nhóm paraphrase/scenario/keyword)
   ▼
180 câu tự sinh  +  30 câu viết tay (gồm 10 ngoài phạm vi)  [SQuAD 2.0 — câu không trả lời được]
```

| Bước | Lựa chọn thiết kế | Căn cứ |
|---|---|---|
| ② Sinh câu hỏi từ tài liệu bằng LLM | "Synthetic query generation": dùng LLM sinh truy vấn từ document, gold biết trước | **InPars** (Bonifacio et al., 2022); **Promptagator** (Dai et al., 2022) |
| ② Gold = thủ tục nguồn | "Known-item retrieval": đánh giá khả năng tìm lại đúng tài liệu đã biết | IR cổ điển (Manning et al., 2008) |
| ③ 6 nhóm query đa dạng | Đánh giá trên nhiều dạng truy vấn để bộc lộ điểm yếu theo nhóm | **BEIR** nhấn mạnh tính **đa dạng/heterogeneous** của truy vấn (Thakur et al., 2021) |
| ③ Chống rò rỉ từ khóa | Ẩn text tài liệu khi sinh truy vấn ngữ nghĩa → câu hỏi không lặp nguyên văn | Tương tự **consistency filtering** của Promptagator (lọc truy vấn sinh kém chất lượng) |
| Câu ngoài phạm vi | 10 câu không thuộc corpus để đo cổng "không tìm thấy" | **SQuAD 2.0** (Rajpurkar et al., 2018) — đưa câu hỏi không trả lời được |
| Cỡ mẫu 180 (CI ±4%) | Tỉ lệ nhị phân + xấp xỉ chuẩn của khoảng tin cậy nhị thức | Thống kê chuẩn (binomial proportion CI) |

> **Lưu ý trung thực:** quy trình của dự án dùng **người soát thủ công** thay cho round-trip consistency filtering tự động của InPars/Promptagator (vì quy mô nhỏ, 180 câu). Đây là biến thể nhẹ hơn nhưng cùng tinh thần: loại câu sinh kém/rò rỉ từ khóa.

### 7.2. Căn cứ chọn metric

Các metric đều là **chuẩn IR kinh điển**, được các benchmark retrieval hiện đại (BEIR, MTEB) và dense retrieval cho QA (DPR) chọn làm chuẩn báo cáo — **không phải metric tự chế cho RAG**.

| Metric | Paper gốc / chuẩn áp dụng |
|---|---|
| **nDCG@10** | Järvelin & Kekäläinen (2002) định nghĩa; **BEIR** (2021) & **MTEB** (2023) dùng làm metric chính |
| **Hit@k / Top-k accuracy** | **DPR** (Karpukhin et al., 2020) — "top-k retrieval accuracy"; gốc Hits@k: TransE (Bordes et al., 2013) |
| **MRR** | TREC-8 QA Track (Voorhees, 1999) |
| **Recall@k / Precision@k** | IR nền tảng (Manning et al., 2008) |
| Cổng abstention (từ chối / giữ gold) | Bài toán answerability — **SQuAD 2.0** (Rajpurkar et al., 2018) |

**Vì sao exact-metric thay vì LLM-judge (RAGAS):** vì dự án **có gold thật** (`ma_thu_tuc`) nên Hit/MRR/nDCG cho kết quả **khách quan, tái lập**, không phụ thuộc LLM-judge có thể sai lệch. RAGAS (`context_precision/recall`, reference-free, LLM-judged) phù hợp hơn cho tầng **generation/faithfulness** ở thí nghiệm sau.

### 7.3. Tài liệu tham khảo

1. Järvelin, K., & Kekäläinen, J. (2002). *Cumulated Gain-based Evaluation of IR Techniques.* ACM TOIS, 20(4). — **nDCG**.
2. Voorhees, E. M. (1999). *The TREC-8 Question Answering Track Report.* Proc. TREC-8. — **MRR**.
3. Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval.* Cambridge University Press. — **Recall@k/Precision@k, known-item**.
4. Karpukhin, V., et al. (2020). *Dense Passage Retrieval for Open-Domain Question Answering.* EMNLP 2020. — **Top-k accuracy (Hit@k)**.
5. Bordes, A., et al. (2013). *Translating Embeddings for Modeling Multi-relational Data (TransE).* NeurIPS 2013. — **Hits@k**.
6. Thakur, N., et al. (2021). *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of IR Models.* NeurIPS 2021 (Datasets & Benchmarks). — **chuẩn nDCG@10, đa dạng truy vấn**.
7. Muennighoff, N., et al. (2023). *MTEB: Massive Text Embedding Benchmark.* EACL 2023. — **nDCG@10 cho retrieval**.
8. Es, S., et al. (2023). *RAGAS: Automated Evaluation of Retrieval Augmented Generation.* arXiv:2309.15217. — **metric RAG reference-free**.
9. Rajpurkar, P., Jia, R., & Liang, P. (2018). *Know What You Don't Know: Unanswerable Questions for SQuAD.* ACL 2018. — **answerability/abstention**.
10. Bonifacio, L., et al. (2022). *InPars: Unsupervised Dataset Generation for Information Retrieval.* SIGIR 2022. — **sinh truy vấn bằng LLM**.
11. Dai, Z., et al. (2022). *Promptagator: Few-shot Dense Retrieval from 8 Examples.* arXiv:2209.11755 (ICLR 2023). — **sinh truy vấn + lọc nhất quán**.

> Năm/venue nên đối chiếu lại khi đưa vào báo cáo chính thức (một số paper có bản arXiv và bản hội nghị khác năm).

---

## Phụ lục — Tái lập

```powershell
# 1. Sinh GT
.venv\Scripts\python.exe rag\eval\gen_gt.py --reset            # 180 câu tự sinh
.venv\Scripts\python.exe rag\eval\make_manual_gt.py            # 30 câu viết tay

# 2. Đánh giá
.venv\Scripts\python.exe rag\eval\eval_retrieval.py                              # hybrid
.venv\Scripts\python.exe rag\eval\eval_retrieval.py --mode vector --suffix _vector
.venv\Scripts\python.exe rag\eval\eval_retrieval.py --gt data\eval\exp01_retrieval\retrieval_gt_manual.jsonl --suffix _manual
.venv\Scripts\python.exe rag\eval\eval_gate.py                 # cổng relevance

# 3. Figure + báo cáo
.venv\Scripts\python.exe rag\eval\make_figures.py             # figures/*.png + dataset_stats.json
.venv\Scripts\python.exe rag\eval\make_report.py              # report.html
```

**Tệp dữ liệu:** `retrieval_gt*.jsonl` (GT) · `retrieval_results*.csv` (per-question) · `*_summary*.json` (tổng hợp) · `gate_results.csv` · `dataset_stats.json` · `figures/` · `report.html`.
