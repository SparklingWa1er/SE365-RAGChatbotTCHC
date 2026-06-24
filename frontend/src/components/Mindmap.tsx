import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Maximize2, Minus, Plus, Scan, X } from "lucide-react";
import { Transformer } from "markmap-lib";
import { Markmap, deriveOptions } from "markmap-view";

// Vẽ mindmap từ markdown markmap (backend phát trong info HTML, dạng
// <div class="markmap"><script type="text/template">...</script></div>).
const transformer = new Transformer();

// Tuỳ chọn hiển thị mặc định cho đẹp + dễ đọc, gộp thêm option từ frontmatter
// (colorFreezeLevel, initialExpandLevel, maxWidth... do backend phát).
function buildOptions(frontmatter: unknown) {
  const fromFm = deriveOptions(
    (frontmatter as { markmap?: unknown } | undefined)?.markmap as never,
  );
  return {
    ...fromFm,
    duration: 350, // animation mượt khi bung/thu node
    spacingVertical: 10,
    spacingHorizontal: 90,
    paddingX: 16,
    fitRatio: 0.92, // chừa lề khi auto-fit
  };
}

// Tạo markmap trên một <svg>; trả về instance để điều khiển (fit/zoom) + cleanup.
function renderMarkmap(svg: SVGSVGElement, markdown: string): Markmap {
  const { root, frontmatter } = transformer.transform(markdown);
  const mm = Markmap.create(svg, buildOptions(frontmatter), root);
  // fit sau một nhịp để SVG đã có kích thước thực.
  requestAnimationFrame(() => mm.fit());
  return mm;
}

// Thanh công cụ dùng chung (zoom / fit / + nút phụ tuỳ chế độ).
function Toolbar({
  onZoomIn,
  onZoomOut,
  onFit,
  extra,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  extra?: React.ReactNode;
}) {
  const btn =
    "rounded-md border border-border bg-card/80 p-1 text-muted-foreground backdrop-blur transition-colors hover:bg-muted hover:text-foreground";
  return (
    <div className="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
      <button type="button" onClick={onZoomOut} title="Thu nhỏ" aria-label="Thu nhỏ" className={btn}>
        <Minus className="size-3.5" />
      </button>
      <button type="button" onClick={onZoomIn} title="Phóng to" aria-label="Phóng to" className={btn}>
        <Plus className="size-3.5" />
      </button>
      <button type="button" onClick={onFit} title="Vừa khung" aria-label="Vừa khung" className={btn}>
        <Scan className="size-3.5" />
      </button>
      {extra}
    </div>
  );
}

export default function Mindmap({ markdown }: { markdown: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const mmRef = useRef<Markmap | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  // Chỉ dựng markmap (d3) khi sơ đồ vào tầm nhìn — mở hội thoại nhiều lượt không
  // phải render mọi sơ đồ cùng lúc (tăng tốc chuyển hội thoại).
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || visible) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !visible) return;
    const mm = renderMarkmap(svg, markdown);
    mmRef.current = mm;
    return () => {
      mm.destroy();
      mmRef.current = null;
    };
  }, [markdown, visible]);

  const zoomIn = useCallback(() => mmRef.current?.rescale(1.25), []);
  const zoomOut = useCallback(() => mmRef.current?.rescale(0.8), []);
  const fit = useCallback(() => mmRef.current?.fit(), []);

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

  const iconBtn =
    "rounded-md border border-border bg-card/80 p-1 text-muted-foreground backdrop-blur transition-colors hover:bg-muted hover:text-foreground";

  return (
    <>
      <div
        ref={wrapRef}
        className="relative bg-[radial-gradient(circle_at_1px_1px,var(--color-border)_1px,transparent_0)] bg-size-[18px_18px]"
      >
        <Toolbar
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onFit={fit}
          extra={
            <>
              <button
                type="button"
                onClick={() => setFullscreen(true)}
                title="Toàn màn hình"
                aria-label="Toàn màn hình"
                className={iconBtn}
              >
                <Maximize2 className="size-3.5" />
              </button>
              <button
                type="button"
                onClick={download}
                title="Tải sơ đồ tư duy (.svg)"
                aria-label="Tải sơ đồ tư duy"
                className={iconBtn}
              >
                <Download className="size-3.5" />
              </button>
            </>
          }
        />
        <svg ref={svgRef} className="h-96 w-full" />
      </div>

      {fullscreen && (
        <FullscreenMindmap markdown={markdown} onClose={() => setFullscreen(false)} />
      )}
    </>
  );
}

// Lớp phủ toàn màn hình: instance markmap riêng, khung lớn để xem chi tiết.
function FullscreenMindmap({
  markdown,
  onClose,
}: {
  markdown: string;
  onClose: () => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const mmRef = useRef<Markmap | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const mm = renderMarkmap(svg, markdown);
    mmRef.current = mm;
    return () => {
      mm.destroy();
      mmRef.current = null;
    };
  }, [markdown]);

  // Đóng bằng phím Esc.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const iconBtn =
    "rounded-md border border-border bg-card/80 p-1.5 text-muted-foreground backdrop-blur transition-colors hover:bg-muted hover:text-foreground";

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background/95 backdrop-blur-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-sm font-medium text-foreground">Sơ đồ tư duy</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Đóng"
          className={iconBtn}
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="relative min-h-0 flex-1 bg-[radial-gradient(circle_at_1px_1px,var(--color-border)_1px,transparent_0)] bg-size-[22px_22px]">
        <Toolbar
          onZoomIn={() => mmRef.current?.rescale(1.25)}
          onZoomOut={() => mmRef.current?.rescale(0.8)}
          onFit={() => mmRef.current?.fit()}
        />
        <svg ref={svgRef} className="h-full w-full" />
      </div>
    </div>
  );
}
