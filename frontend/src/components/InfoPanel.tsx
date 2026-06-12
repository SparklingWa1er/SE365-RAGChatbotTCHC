import { useMemo } from "react";
import Mindmap from "./Mindmap";
import SafeHtml from "./SafeHtml";

// Tab "Suy luận": tách mindmap (div.markmap > script) ra khỏi info HTML để vẽ
// bằng <Mindmap> (DOMPurify sẽ xoá <script> nên không thể render trực tiếp),
// phần HTML còn lại (Thought/Action) render qua SafeHtml. Hai nhóm nguồn
// 📌/📚 (luôn ở CUỐI info HTML) được CẮT BỎ vì đã chuyển sang tab "Nguồn".
export default function InfoPanel({ html }: { html: string }) {
  const { restHtml, mindmaps } = useMemo(() => {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const markmapDivs = Array.from(doc.querySelectorAll("div.markmap"));
    const mindmaps = markmapDivs
      .map((d) => d.querySelector("script")?.textContent?.trim() || "")
      .filter(Boolean);
    // Gỡ TOÀN BỘ collapsible bọc mindmap (summary "Mindmap [Expand] [Export]" của ktem —
    // các nút này chỉ chạy trong Gradio), không chỉ riêng div.markmap.
    markmapDivs.forEach((d) => (d.closest("details") ?? d).remove());

    // Cắt từ tiêu đề nhóm nguồn (📌/📚) đầu tiên trở đi — chúng đã hiển thị ở tab Nguồn.
    const heads = Array.from(doc.body.children);
    const cut = heads.find(
      (el) =>
        el.tagName === "H4" &&
        /📌|📚/.test(el.textContent || ""),
    );
    if (cut) {
      let node: ChildNode | null = cut;
      while (node) {
        const next: ChildNode | null = node.nextSibling;
        node.remove();
        node = next;
      }
    }
    return { restHtml: doc.body.innerHTML, mindmaps };
  }, [html]);

  return (
    <div className="flex flex-col gap-3">
      {mindmaps.map((md, i) => (
        <div key={i} className="overflow-hidden rounded-md border border-border">
          <div className="border-b border-border bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
            Sơ đồ tư duy
          </div>
          <Mindmap markdown={md} />
        </div>
      ))}
      {restHtml.trim() && (
        <SafeHtml
          className="prose info-html max-w-none break-words text-xs leading-relaxed"
          html={restHtml}
        />
      )}
    </div>
  );
}
