import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Globe, Quote } from "lucide-react";
import type { Citation } from "../api/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import SafeHtml from "./SafeHtml";
import { mdToHtml } from "../lib/markdown";

interface Props {
  citations: Citation[];
  width: number;
  // Citation 【n】 vừa bấm trong câu trả lời → mở + cuộn tới nguồn tương ứng.
  active?: { index: number; nonce: number } | null;
}

// Panel phải: danh sách nguồn. Nguồn ĐƯỢC TRÍCH DẪN hiện trực tiếp (thường ít, quan
// trọng); NGUỒN THAM KHẢO (không trích dẫn) gom vào một mục thu gọn được để panel
// không bị dài khi có nhiều nguồn. Quá trình suy luận + sơ đồ tư duy nằm trong từng
// lượt chat (xem ReasoningBlock / Mindmap).
export default function SourcesPanel({ citations, width, active }: Props) {
  const cited = citations.filter((c) => c.cited);
  const others = citations.filter((c) => !c.cited);

  // Map số 【n】 -> thẻ <details> của card chứa nó, để mở + cuộn khi bấm citation.
  const cardByIndex = useRef<Map<number, HTMLDetailsElement>>(new Map());
  const register = (indices: number[], el: HTMLDetailsElement | null) => {
    for (const n of indices) {
      if (el) cardByIndex.current.set(n, el);
      else cardByIndex.current.delete(n);
    }
  };

  useEffect(() => {
    if (!active) return;
    const el = cardByIndex.current.get(active.index);
    if (!el) return;
    el.open = true;
    el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    // Hiệu ứng nhấp nháy viền để chỉ rõ nguồn vừa được dẫn chiếu.
    el.classList.remove("cite-flash");
    void el.offsetWidth; // ép reflow để animation chạy lại
    el.classList.add("cite-flash");
  }, [active]);

  return (
    <aside className="flex shrink-0 flex-col bg-card" style={{ width }}>
      <div className="flex items-center gap-2 px-3 py-2.5 text-sm font-medium text-foreground">
        <Quote className="size-4" />
        Nguồn{citations.length > 0 ? ` (${citations.length})` : ""}
      </div>

      <ScrollArea className="min-h-0 flex-1 px-3 pb-3">
        {citations.length === 0 ? (
          <p className="px-1 py-4 text-xs text-muted-foreground">
            Nguồn trích dẫn sẽ hiện ở đây sau khi có câu trả lời. Bấm vào số 【n】
            trong câu trả lời để tới đúng nguồn.
          </p>
        ) : (
          <div className="flex min-w-0 flex-col gap-3">
            {cited.length > 0 && (
              <SourceGroup
                title="Được trích dẫn"
                items={cited}
                defaultOpen
                register={register}
              />
            )}
            {others.length > 0 && (
              <SourceGroup
                title="Nguồn tham khảo"
                hint="không trích dẫn trực tiếp"
                items={others}
                // Mặc định thu gọn để tránh danh sách quá dài khi nhiều nguồn.
                defaultOpen={others.length <= 3}
                collapsible
                register={register}
              />
            )}
          </div>
        )}
      </ScrollArea>
    </aside>
  );
}

function SourceGroup({
  title,
  hint,
  items,
  defaultOpen = true,
  collapsible = false,
  register,
}: {
  title: string;
  hint?: string;
  items: Citation[];
  defaultOpen?: boolean;
  collapsible?: boolean;
  register: (indices: number[], el: HTMLDetailsElement | null) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // Khi danh sách nguồn đổi (câu trả lời mới), trả lại trạng thái mặc định.
  useEffect(() => setOpen(defaultOpen), [defaultOpen, items]);

  const header = (
    <span className="flex w-full items-center gap-1">
      {collapsible && (
        <ChevronRight
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
      )}
      <span className="text-xs font-semibold text-foreground">{title}</span>
      <span className="font-normal text-[11px] text-muted-foreground">
        ({items.length}){hint ? ` · ${hint}` : ""}
      </span>
    </span>
  );

  return (
    <section className="flex flex-col gap-2">
      {collapsible ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center rounded-md px-1 py-1 text-left hover:bg-muted/40"
        >
          {header}
        </button>
      ) : (
        <h3 className="px-1">{header}</h3>
      )}

      {open && (
        <div className="flex flex-col gap-2">
          {items.map((c, i) => (
            <CitationCard key={i} c={c} register={register} />
          ))}
        </div>
      )}
    </section>
  );
}

function CitationCard({
  c,
  register,
}: {
  c: Citation;
  register: (indices: number[], el: HTMLDetailsElement | null) => void;
}) {
  return (
    <details
      ref={(el) => register(c.indices, el)}
      className="group min-w-0 scroll-mt-2 overflow-hidden rounded-lg border border-border"
    >
      {/* Tiêu đề (luôn hiện) — click để bung toàn văn nội dung gốc. */}
      <summary className="flex cursor-pointer list-none items-start gap-1.5 p-2 hover:bg-muted/40">
        <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
        <span className="min-w-0 flex-1">
          {/* Mỗi 【n】 là một flex-item trực tiếp để flex-wrap xuống dòng (tránh tràn
              ngang khi nguồn có nhiều số trích dẫn). */}
          <span className="mb-0.5 flex flex-wrap items-center gap-x-0.5 gap-y-0.5">
            {c.indices.map((n) => (
              <span
                key={n}
                className="text-[10px] font-semibold leading-tight text-primary"
              >
                【{n}】
              </span>
            ))}
            {c.is_web && (
              <span className="ml-0.5 inline-flex items-center gap-0.5 rounded bg-amber-100 px-1 text-[9px] font-medium text-amber-700">
                <Globe className="size-2.5" /> web
              </span>
            )}
          </span>
          <span className="block break-words text-xs font-medium leading-snug text-foreground">
            {c.title}
          </span>
          {/* Trích đoạn ngắn để xem nhanh mà không cần bung — giữ panel gọn. */}
          {c.snippet && (
            <span className="mt-0.5 line-clamp-2 block break-words text-[11px] leading-snug text-muted-foreground">
              {c.snippet}
            </span>
          )}
        </span>
      </summary>

      {/* Nội dung đầy đủ (có highlight <mark> + 【n】 inline) — chỉ hiện khi mở. */}
      <div className="border-t border-border px-2.5 py-2">
        <SafeHtml
          className="prose info-html max-w-none break-words text-[11px] leading-relaxed text-foreground"
          html={mdToHtml(c.content_html)}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
          {c.is_web && (
            <span className="inline-flex items-center gap-1 text-amber-600">
              <Globe className="size-3" /> web · chưa thẩm định
            </span>
          )}
          {c.score != null && <span>score {c.score.toFixed(2)}</span>}
          {c.url && (
            <a
              href={c.url}
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline"
            >
              mở liên kết ↗
            </a>
          )}
        </div>
      </div>
    </details>
  );
}
