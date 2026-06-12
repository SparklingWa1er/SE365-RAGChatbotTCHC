import { Sparkles, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReasoningMode } from "../App";

interface Props {
  mode: ReasoningMode;
  onChange: (mode: ReasoningMode) => void;
  className?: string;
}

// reasoning_type khớp id engine ở backend (react.py get_info()["id"] = "ReAct",
// FullQAPipeline = "simple"). Truyền qua settings_override.reasoning_type.
const MODES: {
  id: ReasoningMode;
  icon: typeof Sparkles;
  title: string;
  desc: string;
}[] = [
  {
    id: "ReAct",
    icon: Sparkles,
    title: "Suy luận sâu",
    desc: "Agent tự tra cứu nhiều bước, kết hợp web",
  },
  {
    id: "simple",
    icon: Zap,
    title: "Trả lời nhanh",
    desc: "Tra cứu một lượt, gọn nhẹ",
  },
];

export default function ModeSelect({ mode, onChange, className }: Props) {
  return (
    <div className={cn("grid grid-cols-2 gap-3", className)}>
      {MODES.map(({ id, icon: Icon, title, desc }) => {
        const active = mode === id;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            aria-pressed={active}
            className={cn(
              "flex items-start gap-3 rounded-2xl border p-3.5 text-left transition",
              active
                ? "border-primary bg-primary/5 shadow-[0_4px_14px_-8px_rgba(22,104,201,.45)]"
                : "border-input bg-card hover:bg-muted/50",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl",
                active
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-[#6a6f78]",
              )}
            >
              <Icon className="size-[18px]" />
            </span>
            <span className="min-w-0">
              <span
                className={cn(
                  "block text-[15px] font-semibold leading-tight",
                  active ? "text-primary" : "text-foreground",
                )}
              >
                {title}
              </span>
              <span className="mt-0.5 block text-[12.5px] leading-snug text-muted-foreground">
                {desc}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
