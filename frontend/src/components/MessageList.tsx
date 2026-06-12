import { useEffect, useMemo } from "react";
import { Landmark } from "lucide-react";
import type { Turn } from "../App";
import { mdToHtml } from "../lib/markdown";
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
  streaming: boolean;
  scrollTarget: string | null; // "<turnIndex>-user" | "<turnIndex>-bot" (từ Search Modal)
  onScrolled: () => void;
}

// Conversation (use-stick-to-bottom) tự auto-scroll + nút cuộn xuống đáy.
export default function MessageList({
  turns,
  pendingUser,
  streamBot,
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
              <Exchange key={i} index={i} user={t.user} bot={t.bot} />
            ))}
            {pendingUser !== null && (
              <Exchange
                index={turns.length}
                user={pendingUser}
                bot={streamBot}
                streaming={streaming && !streamBot}
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
  streaming,
}: {
  index: number;
  user: string;
  bot: string;
  streaming?: boolean;
}) {
  // Câu trả lời bot là markdown (có HTML citation inline) — dịch sang HTML rồi mới sanitize.
  const botHtml = useMemo(() => mdToHtml(bot), [bot]);
  return (
    <>
      <Message from="user" id={`msg-${index}-user`} className="scroll-mt-4">
        <MessageContent>
          <span className="whitespace-pre-wrap">{user}</span>
        </MessageContent>
      </Message>
      <Message from="assistant" id={`msg-${index}-bot`} className="scroll-mt-4">
        <MessageContent>
          {streaming ? (
            <Shimmer>Đang trả lời…</Shimmer>
          ) : (
            <SafeHtml className="prose prose-sm max-w-none" html={botHtml} />
          )}
        </MessageContent>
      </Message>
    </>
  );
}
