# Ảnh chụp màn hình cho báo cáo tuần

Mỗi báo cáo tuần (`week1..4.tex`) có sẵn các **khung placeholder**. Khi chưa có ảnh, khung
hiện mô tả "cần chụp gì". Chỉ cần **chụp màn hình → lưu vào thư mục này ĐÚNG tên dưới đây
(định dạng PNG) → biên dịch lại** là ảnh tự hiện ra (không phải sửa file `.tex`).

> Lưu ý: dùng đúng tên + đuôi `.png`. Biên dịch lại: `cd report/weekly && latexmk -pdf week1.tex`

## Danh sách tên file cần chụp

| File | Nội dung cần chụp |
|------|-------------------|
| `week1-crawl.png`         | Terminal chạy crawler: tiến trình tải, số thủ tục, resume/retry |
| `week1-corpus.png`        | Một file Markdown corpus: metadata + các mục (hồ sơ, lệ phí, căn cứ) |
| `week1-ingest.png`        | Log nhúng song song + kiểm tra toàn vẹn kho; hoặc thư mục index |
| `week2-simple-answer.png` | Giao diện trả lời chế độ "simple": câu hỏi + câu trả lời + nguồn |
| `week2-citation.png`      | Panel nguồn có tô sáng + số trích dẫn 【n】 trong câu trả lời |
| `week3-ui.png`            | Toàn cảnh UI React: chat + sidebar + panel nguồn + ô gợi ý |
| `week3-reasoning.png`     | Bảng các bước suy luận (Thought/Action/Observation) theo thời gian thực |
| `week3-citation.png`      | Trả lời có 【n】 + nhãn nguồn web + mindmap + gợi ý câu hỏi |
| `week4-settings.png`      | Trang Settings: chọn nhà cung cấp/mô hình LLM |
| `week4-multimodel.png`    | Cùng câu hỏi chạy trên 2 nhà cung cấp (Azure / vLLM) |

## Gợi ý chụp đẹp
- Crop sát nội dung, tránh thanh taskbar/khoảng trống thừa.
- Ảnh ngang (landscape) hợp khung hơn; độ phân giải cao để in rõ.
- Có thể đổi tỉ lệ chèn trong `weekly.sty` (`width=0.86\textwidth`) nếu muốn to/nhỏ hơn.
