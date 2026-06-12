import { Brain, ChevronRight, Globe, Quote } from "lucide-react";
import type { Citation } from "../api/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import InfoPanel from "./InfoPanel";
import SafeHtml from "./SafeHtml";
import { mdToHtml } from "../lib/markdown";

interface Props {
  citations: Citation[];
  infoHtml: string;
  width: number;
}

export default function SourcesPanel({ citations, infoHtml, width }: Props) {
  const cited = citations.filter((c) => c.cited);
  const others = citations.filter((c) => !c.cited);
  return (
    <aside
      className="flex shrink-0 flex-col bg-card"
      style={{ width }}
    >
      <Tabs defaultValue="sources" className="flex min-h-0 flex-1 flex-col gap-0">
        <TabsList className="m-2">
          <TabsTrigger value="sources">
            <Quote data-icon="inline-start" />
            Nguồn{citations.length > 0 ? ` (${citations.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="reasoning">
            <Brain data-icon="inline-start" />
            Suy luận
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sources" className="min-h-0 flex-1">
          <ScrollArea className="h-full px-3 pb-3">
            {citations.length === 0 ? (
              <p className="px-1 py-4 text-xs text-muted-foreground">
                Nguồn trích dẫn sẽ hiện ở đây sau khi có câu trả lời.
              </p>
            ) : (
              <div className="flex min-w-0 flex-col gap-4">
                {cited.length > 0 && (
                  <SourceGroup title="Nguồn được trích dẫn" items={cited} />
                )}
                {others.length > 0 && (
                  <SourceGroup
                    title="Nguồn tham khảo"
                    hint="không trích dẫn trực tiếp"
                    items={others}
                  />
                )}
              </div>
            )}
          </ScrollArea>
        </TabsContent>

        <TabsContent value="reasoning" className="min-h-0 flex-1">
          <ScrollArea className="h-full px-3 pb-3">
            {infoHtml ? (
              <InfoPanel html={infoHtml} />
            ) : (
              <p className="px-1 py-4 text-xs text-muted-foreground">
                Các bước Thought / Action / Observation sẽ hiện ở đây.
              </p>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </aside>
  );
}

function SourceGroup({
  title,
  hint,
  items,
}: {
  title: string;
  hint?: string;
  items: Citation[];
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="px-1 text-xs font-semibold text-foreground">
        {title}
        <span className="ml-1 font-normal text-muted-foreground">
          ({items.length}){hint ? ` · ${hint}` : ""}
        </span>
      </h3>
      <div className="flex flex-col gap-2">
        {items.map((c, i) => (
          <CitationCard key={i} c={c} />
        ))}
      </div>
    </section>
  );
}

function CitationCard({ c }: { c: Citation }) {
  return (
    <details className="group min-w-0 overflow-hidden rounded-lg border border-border">
      {/* Tiêu đề (luôn hiện) — click để bung toàn văn nội dung gốc. */}
      <summary className="flex cursor-pointer list-none items-start gap-1.5 p-2.5 hover:bg-muted/40">
        <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
        <span className="min-w-0 flex-1">
          {c.indices.length > 0 && (
            <span className="mb-0.5 flex flex-wrap gap-x-0.5 text-[10px] font-semibold leading-tight text-primary">
              {c.indices.map((n) => (
                <span key={n}>【{n}】</span>
              ))}
            </span>
          )}
          <span className="block break-words text-xs font-medium text-foreground">
            {c.title}
          </span>
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
