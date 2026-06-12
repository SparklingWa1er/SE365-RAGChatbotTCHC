import { useState } from "react";
import { Plus, Search, X } from "lucide-react";
import type { ConversationSummary } from "../api/types";
import { deburr, relativeTime } from "@/lib/conversations";

interface Props {
  conversations: ConversationSummary[];
  onOpen: (id: string) => void;
  onNew: () => void;
}

// Trang Chats (§7): chỉ mục mọi hội thoại, lọc theo TÊN chủ đề.
export default function ChatsPage({ conversations, onOpen, onNew }: Props) {
  const [query, setQuery] = useState("");
  const q = deburr(query.trim());
  const list = q
    ? conversations.filter((c) => deburr(c.name || "").includes(q))
    : conversations;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[920px] px-8 pt-8 pb-16">
        {/* Tiêu đề + nút New chat */}
        <div className="mb-6 flex items-center justify-between gap-4">
          <h1 className="text-[30px] font-extrabold tracking-[-0.6px] text-foreground">
            Chats
          </h1>
          <button
            onClick={onNew}
            className="flex h-[42px] shrink-0 items-center gap-2 rounded-full bg-primary px-[18px] text-[14.5px] font-semibold whitespace-nowrap text-primary-foreground shadow-[0_4px_12px_-3px_rgba(22,104,201,.45)] transition-colors hover:bg-[#1259b3]"
          >
            <Plus className="size-[18px]" />
            New chat
          </button>
        </div>

        {/* Ô tìm theo tên chủ đề */}
        <div className="flex h-[54px] items-center gap-3 rounded-[14px] border border-input bg-background px-[18px] transition focus-within:border-primary/40 focus-within:shadow-[0_0_0_4px_rgba(22,104,201,.08)]">
          <Search className="size-5 shrink-0 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats by topic…"
            className="min-w-0 flex-1 border-0 bg-transparent text-base text-foreground outline-none placeholder:text-[#a7adb6]"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              title="Clear"
              aria-label="Clear"
              className="flex size-[30px] shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="size-[18px]" />
            </button>
          )}
        </div>

        {/* Danh sách */}
        <div className="mt-4 flex flex-col">
          {list.length === 0 ? (
            <div className="px-4 py-14 text-center text-[15px] text-muted-foreground">
              {conversations.length === 0
                ? "No chats yet."
                : `No chats match “${query.trim()}”.`}
            </div>
          ) : (
            list.map((c) => (
              <button
                key={c.id}
                onClick={() => onOpen(c.id)}
                className="flex w-full items-center justify-between gap-[18px] rounded-[10px] border-b border-border px-3.5 py-[17px] text-left transition-colors hover:bg-muted"
              >
                <span className="flex-1 truncate text-base font-medium text-foreground">
                  {c.name || "(untitled)"}
                </span>
                <span className="shrink-0 text-[13.5px] text-muted-foreground">
                  {relativeTime(c.date_updated)}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
