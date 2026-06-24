import type { ReasoningMode, Turn } from "../App";
import type { Citation } from "../api/types";
import Composer from "./Composer";
import MessageList from "./MessageList";
import ModeSelect from "./ModeSelect";

interface Props {
  turns: Turn[];
  pendingUser: string | null;
  streamBot: string;
  streamInfo: string;
  streamCitations: Citation[];
  streaming: boolean;
  suggestions: string[][];
  canRegen: boolean;
  scrollTarget: string | null;
  mode: ReasoningMode;
  onModeChange: (mode: ReasoningMode) => void;
  onScrolled: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
  onRegen: () => void;
  onCitationClick: (citations: Citation[], n: number) => void;
}

export default function ChatView({
  turns,
  pendingUser,
  streamBot,
  streamInfo,
  streamCitations,
  streaming,
  suggestions,
  canRegen,
  scrollTarget,
  mode,
  onModeChange,
  onScrolled,
  onSend,
  onStop,
  onRegen,
  onCitationClick,
}: Props) {
  // Màn hình "new conversation": chưa có lượt nào và không đang stream.
  const isEmpty = turns.length === 0 && !pendingUser && !streaming;

  if (isEmpty) {
    return (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-1 flex-col items-center justify-center px-6 pb-6">
          <div className="w-full max-w-[820px]">
            {/* Block 1: logo + tiêu đề (cùng một dòng) */}
            <div className="mb-7 flex items-center justify-center gap-3">
              <img
                src="/favicon.svg"
                alt="DVC RAG"
                className="size-[46px] shrink-0 object-contain"
              />
              <h1 className="text-[34px] font-extrabold tracking-[-1px] text-foreground">
                Bắt đầu hỏi đáp
              </h1>
            </div>

            {/* Block 2: bộ 2 block chọn chế độ (đổi engine thật) */}
            <ModeSelect mode={mode} onChange={onModeChange} className="mb-5" />

            {/* Block 3: gợi ý dính vào text field (Composer hero) */}
            <Composer
              variant="hero"
              streaming={streaming}
              suggestions={suggestions}
              canRegen={canRegen}
              onSend={onSend}
              onStop={onStop}
              onRegen={onRegen}
            />
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <MessageList
        turns={turns}
        pendingUser={pendingUser}
        streamBot={streamBot}
        streamInfo={streamInfo}
        streamCitations={streamCitations}
        streaming={streaming}
        scrollTarget={scrollTarget}
        onScrolled={onScrolled}
        onCitationClick={onCitationClick}
      />

      <Composer
        streaming={streaming}
        suggestions={suggestions}
        canRegen={canRegen}
        onSend={onSend}
        onStop={onStop}
        onRegen={onRegen}
      />
    </main>
  );
}
