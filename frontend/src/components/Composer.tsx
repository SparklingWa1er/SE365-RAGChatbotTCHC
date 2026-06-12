import { useState } from "react";
import { ArrowUp, RotateCcw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { Suggestion, Suggestions } from "./ai-elements/suggestion";

interface Props {
  streaming: boolean;
  suggestions: string[][];
  canRegen: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onRegen: () => void;
  // "thread" = đáy khung chat (có nền + padding); "hero" = nhúng trong màn hình
  // new conversation (parent tự lo nền/độ rộng).
  variant?: "thread" | "hero";
}

export default function Composer({
  streaming,
  suggestions,
  canRegen,
  onSend,
  onStop,
  onRegen,
  variant = "thread",
}: Props) {
  const [text, setText] = useState("");
  const ready = text.trim().length > 0;

  const submit = () => {
    if (!ready || streaming) return;
    onSend(text);
    setText("");
  };

  const hero = variant === "hero";

  return (
    <div className={hero ? "" : "bg-card px-6 pt-2 pb-5"}>
      <div className={hero ? "" : "mx-auto max-w-[880px]"}>
        {/* gợi ý câu hỏi */}
        {!streaming && suggestions.length > 0 && (
          <Suggestions className="mb-2">
            {suggestions.slice(0, 5).map((s, i) => (
              <Suggestion key={i} suggestion={s[0]} onClick={onSend} />
            ))}
          </Suggestions>
        )}

        {/* Composer card — border + radius 24px + shadow, focus ring xanh (design handoff) */}
        <div className="rounded-[24px] border border-input bg-card p-4 shadow-[0_6px_28px_-14px_rgba(16,22,30,.16),0_1px_3px_rgba(16,22,30,.05)] transition focus-within:border-primary/40 focus-within:shadow-[0_10px_36px_-14px_rgba(22,104,201,.28),0_0_0_4px_rgba(22,104,201,.07)]">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Message DVC RAG"
            className="max-h-[200px] min-h-[28px] resize-none border-0 bg-transparent px-3 py-0 text-[17px] leading-[1.5] shadow-none focus-visible:ring-0"
          />

          <div className="mt-2 flex items-center justify-end gap-2">
            {canRegen && (
              <Button
                variant="ghost"
                onClick={onRegen}
                aria-label="Regenerate"
                title="Regenerate"
                className="size-10 rounded-full text-[#6a6f78]"
              >
                <RotateCcw className="size-[18px]" />
              </Button>
            )}

            {streaming ? (
              <Button
                onClick={onStop}
                aria-label="Stop"
                className="size-[42px] rounded-full bg-destructive/10 text-destructive hover:bg-destructive/20"
              >
                <Square className="size-4" />
              </Button>
            ) : (
              <Button
                onClick={submit}
                disabled={!ready}
                aria-label="Send"
                className={cn(
                  "size-[42px] rounded-full",
                  ready
                    ? "bg-primary text-primary-foreground shadow-[0_4px_12px_-3px_rgba(22,104,201,.5)] hover:bg-[#1259b3]"
                    : "bg-accent text-primary/40",
                )}
              >
                <ArrowUp className="size-5" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
