// Tách HTML "info" của backend thành phần SUY LUẬN (Thought/Action/Observation +
// ghi chú quá trình) và các MINDMAP. Dùng chung cho dropdown suy luận trong chat.
//
// Cấu trúc info HTML (xem react.py): [các bước collapsible] + [ghi chú] +
// (cuối) [mindmap div.markmap>script] + [📌/📚 nhóm nguồn].
//   - Nhóm nguồn 📌/📚 đã hiển thị ở tab "Nguồn" → CẮT BỎ.
//   - Mindmap chứa <script> (DOMPurify xoá) → tách riêng để <Mindmap> vẽ.

export interface ExtractedReasoning {
  reasoningHtml: string; // các bước + ghi chú (an toàn cho SafeHtml)
  mindmaps: string[]; // markdown markmap để <Mindmap> render
}

export function extractReasoning(html: string): ExtractedReasoning {
  if (!html || !html.trim()) return { reasoningHtml: "", mindmaps: [] };

  const doc = new DOMParser().parseFromString(html, "text/html");

  // 1. Tách mindmap (div.markmap > script) rồi gỡ toàn bộ collapsible bọc nó.
  const markmapDivs = Array.from(doc.querySelectorAll("div.markmap"));
  const mindmaps = markmapDivs
    .map((d) => d.querySelector("script")?.textContent?.trim() || "")
    .filter(Boolean);
  markmapDivs.forEach((d) => (d.closest("details") ?? d).remove());

  // 2. Cắt từ tiêu đề nhóm nguồn (📌/📚) đầu tiên trở đi — đã ở tab Nguồn.
  const cut = Array.from(doc.body.children).find(
    (el) => el.tagName === "H4" && /📌|📚/.test(el.textContent || ""),
  );
  if (cut) {
    let node: ChildNode | null = cut;
    while (node) {
      const next: ChildNode | null = node.nextSibling;
      node.remove();
      node = next;
    }
  }

  return { reasoningHtml: doc.body.innerHTML.trim(), mindmaps };
}

// Có nội dung suy luận đáng hiển thị không (bỏ khoảng trắng / thẻ rỗng).
export function hasReasoning(html: string | undefined): boolean {
  if (!html) return false;
  const { reasoningHtml, mindmaps } = extractReasoning(html);
  return reasoningHtml.length > 0 || mindmaps.length > 0;
}
