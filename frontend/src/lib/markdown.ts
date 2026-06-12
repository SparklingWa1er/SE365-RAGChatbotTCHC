import { marked } from "marked";

// Backend (simple.py / react.py) phát câu trả lời trên channel "chat" dạng MARKDOWN
// có chèn sẵn HTML inline cho trích dẫn (<a class="citation">【n】</a>). SafeHtml chỉ
// sanitize HTML chứ không parse markdown, nên cần dịch markdown -> HTML ở đây trước.
// marked GIỮ NGUYÊN HTML inline (anchor citation) nên trích dẫn vẫn hoạt động.
marked.setOptions({
  gfm: true,
  breaks: false, // \n đơn = soft break (markdown chuẩn); đoạn cách bằng \n\n
});

// Markdown chỉ nhận diện bảng khi có DÒNG TRỐNG phía trên. Chunk corpus thường dán
// tiêu đề/đoạn sát ngay trên bảng → chèn dòng trống trước khối bảng (mirror ktem
// Render._ensure_table_blank_line) để marked dựng được <table>.
function ensureTableBlankLine(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  for (const line of lines) {
    const prev = out[out.length - 1];
    if (
      line.trimStart().startsWith("|") &&
      prev !== undefined &&
      prev.trim() !== "" &&
      !prev.trimStart().startsWith("|")
    ) {
      out.push("");
    }
    out.push(line);
  }
  return out.join("\n");
}

export function mdToHtml(md: string): string {
  if (!md) return "";
  return marked.parse(ensureTableBlankLine(md), { async: false }) as string;
}
