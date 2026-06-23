import { CollapsibleContent } from "@/components/ui/collapsible";
import {
  Reasoning,
  ReasoningTrigger,
  useReasoning,
} from "./ai-elements/reasoning";
import { Shimmer } from "./ai-elements/shimmer";
import SafeHtml from "./SafeHtml";

// Dropdown "quá trình suy luận" hiển thị TRONG chat (kiểu claude.ai):
//   - tự MỞ khi đang stream, tự THU GỌN ~1s sau khi xong (logic ở <Reasoning>),
//   - nhãn "Đang suy luận…" → "Đã suy luận trong N giây",
//   - nội dung là HTML các bước (Thought/Action/Observation) → SafeHtml.
//
// `html` là phần đã trích (reasoningHtml) — không gồm mindmap/nguồn. `streaming`
// = lượt này đang chạy (điều khiển auto open/close + đồng hồ).
export default function ReasoningBlock({
  html,
  streaming,
}: {
  html: string;
  streaming: boolean;
}) {
  // Chưa có bước nào và cũng không đang stream → không render gì.
  if (!streaming && !html.trim()) return null;

  return (
    <Reasoning className="mb-3" isStreaming={streaming}>
      <ReasoningTrigger getThinkingMessage={thinkingMessage} />
      <ReasoningContentHtml html={html} />
    </Reasoning>
  );
}



function thinkingMessage(isStreaming: boolean, duration?: number) {
  if (isStreaming || duration === 0) {
    return <Shimmer duration={1}>Đang suy luận…</Shimmer>;
  }
  if (duration == null) return <span>Quá trình suy luận</span>;
  return <span>Đã suy luận trong {duration} giây</span>;
}

// Như ReasoningContent nhưng render HTML (SafeHtml) thay vì markdown (Streamdown),
// vì backend phát các bước dưới dạng HTML <details> collapsible.
function ReasoningContentHtml({ html }: { html: string }) {
  const { isStreaming } = useReasoning();
  return (
    <CollapsibleContent className="mt-2 text-sm data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 outline-none data-[state=closed]:animate-out data-[state=open]:animate-in">
      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
        {html.trim() ? (
          <SafeHtml
            className="prose info-html max-w-none break-words text-xs leading-relaxed text-muted-foreground"
            html={html}
          />
        ) : isStreaming ? (
          <p className="text-xs text-muted-foreground">Đang khởi tạo…</p>
        ) : null}
      </div>
    </CollapsibleContent>
  );
}
