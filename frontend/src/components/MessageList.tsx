import { useEffect, useMemo } from "react";
import { Landmark } from "lucide-react";
import type { Turn } from "../App";
import { mdToHtml } from "../lib/markdown";
import { extractReasoning } from "../lib/reasoning";
import Mindmap from "./Mindmap";
import ReasoningBlock from "./ReasoningBlock";
import SafeHtml from "./SafeHtml";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "./ai-elements/conversation";
import { Message, MessageContent } from "./ai-elements/message";
import { Shimmer } from "./ai-elements/shimmer";

interface Props {
  turns: Turn[];
  pendingUser: string | null; // câu hỏi lượt đang stream
  streamBot: string; // HTML bot tích luỹ của lượt đang stream
  streamInfo: string; // HTML suy luận tích luỹ của lượt đang stream
  streaming: boolean;
  scrollTarget: string | null; // "<turnIndex>-user" | "<turnIndex>-bot" (từ Search Modal)
  onScrolled: () => void;
}

// Conversation (use-stick-to-bottom) tự auto-scroll + nút cuộn xuống đáy.
export default function MessageList({
  turns,
  pendingUser,
  streamBot,
  streamInfo,
  streaming,
  scrollTarget,
  onScrolled,
}: Props) {
  const empty = turns.length === 0 && pendingUser === null;

  // Khi chọn 1 kết quả tìm kiếm → cuộn tin nhắn đó lên đầu khung.
  // Đợi 1 nhịp để stick-to-bottom auto-scroll xong rồi mới cuộn chính xác.
  useEffect(() => {
    if (!scrollTarget) return;
    let raf = 0;
    const t = setTimeout(() => {
      raf = requestAnimationFrame(() => {
        const el = document.getElementById(`msg-${scrollTarget}`);
        if (el) el.scrollIntoView({ block: "start", behavior: "smooth" });
        onScrolled();
      });
    }, 80);
    return () => {
      clearTimeout(t);
      cancelAnimationFrame(raf);
    };
  }, [scrollTarget, turns, onScrolled]);

  return (
    <Conversation className="flex-1">
      <ConversationContent className="mx-auto w-full max-w-3xl scroll-pt-4">
        {empty ? (
          <ConversationEmptyState
            icon={<Landmark className="size-10" />}
            title="Trợ lý thủ tục hành chính công"
            description="Hỏi tôi về thủ tục hành chính công Việt Nam — lệ phí, hồ sơ, trình tự, thời gian giải quyết…"
          />
        ) : (
          <>
            {turns.map((t, i) => (
              <Exchange
                key={i}
                index={i}
                user={t.user}
                bot={t.bot}
                info={t.info ?? ""}
              />
            ))}
            {pendingUser !== null && (
              <Exchange
                index={turns.length}
                user={pendingUser}
                bot={streamBot}
                info={streamInfo}
                streaming={streaming}
              />
            )}
          </>
        )}
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  );
}

function Exchange({
  index,
  user,
  bot,
  info,
  streaming,
}: {
  index: number;
  user: string;
  bot: string;
  info: string;
  streaming?: boolean;
}) {
  // Câu trả lời bot là markdown (có HTML citation inline) — dịch sang HTML rồi mới sanitize.
  const botHtml = useMemo(() => mdToHtml(bot), [bot]);
  // Tách phần suy luận (Thought/Action) khỏi mindmap để đặt đúng vị trí:
  // dropdown suy luận TRÊN bong bóng, sơ đồ tư duy DƯỚI câu trả lời.
  const { reasoningHtml, mindmaps } = useMemo(
    () => extractReasoning(info),
    [info],
  );
  const isStreaming = !!streaming;
  const waiting = isStreaming && !bot; // đang suy luận, chưa có câu trả lời

  return (
    <>
      <Message from="user" id={`msg-${index}-user`} className="scroll-mt-4">
        <MessageContent>
          <span className="whitespace-pre-wrap">{user}</span>
        </MessageContent>
      </Message>
      <Message from="assistant" id={`msg-${index}-bot`} className="scroll-mt-4">
        <MessageContent>
          <ReasoningBlock html={reasoningHtml} streaming={isStreaming} />
          {bot ? (
            <SafeHtml className="prose prose-sm max-w-none" html={botHtml} />
          ) : (
            // Chưa có câu trả lời: nếu dropdown suy luận đang chạy thì nó đã báo
            // tiến trình ("Đang suy luận…"), khỏi cần shimmer thứ hai. Chỉ hiện
            // "Đang trả lời…" khi chưa có bước suy luận nào (vd engine không phát info).
            waiting && !reasoningHtml && <Shimmer>Đang trả lời…</Shimmer>
          )}
          {mindmaps.map((md, i) => (
            <div
              key={i}
              className="mt-3 overflow-hidden rounded-md border border-border"
            >
              <div className="border-b border-border bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                Sơ đồ tư duy
              </div>
              <Mindmap markdown={md} />
            </div>
          ))}
        </MessageContent>
      </Message>
    </>
  );
}
