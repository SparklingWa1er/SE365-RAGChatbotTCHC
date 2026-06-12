import { useCallback, useEffect, useRef } from "react";
import { Download } from "lucide-react";
import { Transformer } from "markmap-lib";
import { Markmap, deriveOptions } from "markmap-view";

// Vẽ mindmap từ markdown markmap (backend phát trong info HTML, dạng
// <div class="markmap"><script type="text/template">...</script></div>).
const transformer = new Transformer();

export default function Mindmap({ markdown }: { markdown: string }) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const { root, frontmatter } = transformer.transform(markdown);
    // frontmatter.markmap chứa option (colorFreezeLevel, initialExpandLevel...).
    const options = deriveOptions(
      (frontmatter as { markmap?: unknown } | undefined)?.markmap as never,
    );
    const mm = Markmap.create(svg, options, root);
    return () => mm.destroy();
  }, [markdown]);

  // Tải sơ đồ về dạng .svg (kèm width/height + namespace để mở độc lập được).
  const download = useCallback(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const { width, height } = svg.getBoundingClientRect();
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", String(Math.round(width) || 800));
    clone.setAttribute("height", String(Math.round(height) || 600));
    const data = new XMLSerializer().serializeToString(clone);
    const blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n', data], {
      type: "image/svg+xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "so-do-tu-duy.svg";
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, []);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={download}
        title="Tải sơ đồ tư duy (.svg)"
        aria-label="Tải sơ đồ tư duy"
        className="absolute right-1 top-1 z-10 rounded-md border border-border bg-card/80 p-1 text-muted-foreground backdrop-blur transition-colors hover:bg-muted hover:text-foreground"
      >
        <Download className="size-3.5" />
      </button>
      <svg ref={svgRef} className="h-72 w-full" />
    </div>
  );
}
