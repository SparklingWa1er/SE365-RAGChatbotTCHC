import { Fragment, useEffect, useRef } from "react";
import { MessageSquare, Search, X } from "lucide-react";

// Một kết quả khớp = một tin nhắn (user/bot) trong hội thoại hiện tại.
export interface SearchResult {
  key: string;
  title: string; // nhãn vai trò: "Bạn" | "Trợ lý"
  role: "user" | "bot";
  turnIndex: number;
  text: string; // đã strip HTML
  time?: string;
}

interface Props {
  open: boolean;
  query: string;
  setQuery: (q: string) => void;
  results: SearchResult[];
  onPick: (r: SearchResult) => void;
  onClose: () => void;
}

export default function SearchModal({
  open,
  query,
  setQuery,
  results,
  onPick,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => inputRef.current?.focus(), 40);
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", esc);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", esc);
    };
  }, [open, onClose]);

  if (!open) return null;
  const q = query.trim();

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-[rgba(15,18,22,.32)] px-5 pt-[13vh] pb-6 backdrop-blur-[3px] animate-in fade-in-0 duration-150"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="flex max-h-[74vh] w-full max-w-[812px] flex-col overflow-hidden rounded-[18px] bg-background shadow-[0_28px_80px_-22px_rgba(16,22,30,.45),0_6px_18px_rgba(16,22,30,.10)] animate-in fade-in-0 zoom-in-[0.99] slide-in-from-top-2 duration-200"
      >
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border px-[18px] py-[15px]">
          <Search className="size-5 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search this conversation"
            className="min-w-0 flex-1 border-0 bg-transparent text-[19px] text-foreground outline-none placeholder:text-[#b0b6bf]"
          />
          <div className="h-6 w-px shrink-0 bg-input" />
          <button
            onClick={onClose}
            title="Close"
            aria-label="Close search"
            className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] text-[#6a6f78] transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto p-2.5">
          {q === "" ? (
            <div className="px-4 pt-12 pb-14 text-center text-[15px] text-muted-foreground">
              Search messages in this conversation
            </div>
          ) : results.length === 0 ? (
            <div className="px-4 pt-12 pb-14 text-center text-[15px] text-muted-foreground">
              No results for “{q}”
            </div>
          ) : (
            results.map((r) => (
              <button
                key={r.key}
                onClick={() => onPick(r)}
                className="flex w-full items-start gap-3.5 rounded-[14px] px-3.5 py-3 text-left transition-colors hover:bg-muted"
              >
                <span className="mt-px flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-[#7c828b]">
                  <MessageSquare className="size-[19px]" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="flex items-baseline gap-3">
                    <span className="flex-1 truncate text-[15.5px] font-semibold text-foreground">
                      {r.title}
                    </span>
                    {r.time && (
                      <span className="shrink-0 text-[13px] text-muted-foreground">
                        {r.time}
                      </span>
                    )}
                  </span>
                  <span className="flex min-w-0 items-center gap-2 text-[14.5px] text-[#8b9099]">
                    {r.role === "user" && (
                      <span className="flex size-[18px] shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#1668c9] to-[#3a86e8] text-[9px] font-bold text-white">
                        Tôi
                      </span>
                    )}
                    <Snippet text={r.text} q={q} />
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// Cửa sổ đoạn trích quanh lần khớp đầu tiên + tô đậm các lần khớp.
function Snippet({ text, q }: { text: string; q: string }) {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  const tl = q.toLowerCase();
  const lower = flat.toLowerCase();
  const idx = lower.indexOf(tl);

  let lead = false;
  let trail = false;
  let body = flat;
  if (idx >= 0) {
    const start = Math.max(0, idx - 32);
    const end = Math.min(flat.length, idx + q.length + 110);
    lead = start > 0;
    trail = end < flat.length;
    body = flat.slice(start, end);
  }

  const bl = body.toLowerCase();
  const parts: [string, boolean][] = [];
  let i = 0;
  if (tl) {
    for (;;) {
      const j = bl.indexOf(tl, i);
      if (j < 0) {
        parts.push([body.slice(i), false]);
        break;
      }
      if (j > i) parts.push([body.slice(i, j), false]);
      parts.push([body.slice(j, j + q.length), true]);
      i = j + q.length;
    }
  } else {
    parts.push([body, false]);
  }

  return (
    <span className="min-w-0 flex-1 truncate">
      {lead ? "…" : ""}
      {parts.map(([s, hit], k) =>
        hit ? (
          <mark key={k} className="bg-transparent font-bold text-foreground">
            {s}
          </mark>
        ) : (
          <Fragment key={k}>{s}</Fragment>
        ),
      )}
      {trail ? "…" : ""}
    </span>
  );
}
