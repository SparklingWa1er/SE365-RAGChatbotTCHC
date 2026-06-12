import { useEffect, useRef, useState } from "react";
import { CirclePlus, PanelLeft, Search } from "lucide-react";

interface Props {
  collapsed: boolean;
  showTitle: boolean; // chỉ hiện tiêu đề ở trang chat (home)
  title: string;
  canEdit: boolean; // chỉ đổi tên được khi hội thoại đã tồn tại
  onRename: (name: string) => void;
  onOpenSidebar: () => void;
  onSearch: () => void;
  onNewChat: () => void;
}

// Topbar khung giữa: (khi sidebar đóng) logo + pill 3 nút, rồi tiêu đề hội thoại
// căn trái — bấm để đổi tên. Chiếm chiều cao cố định → đẩy tin nhắn xuống dưới.
export default function ChatTopbar({
  collapsed,
  showTitle,
  title,
  canEdit,
  onRename,
  onOpenSidebar,
  onSearch,
  onNewChat,
}: Props) {
  // Không có gì để hiện (trang Chats + sidebar mở) → không chiếm chỗ.
  if (!collapsed && !showTitle) return null;

  return (
    <div className="flex h-14 shrink-0 items-center gap-3 px-4">
      {collapsed && (
        <div className="flex items-center gap-3 duration-300 animate-in fade-in slide-in-from-left-2">
          <img
            src="/favicon.svg"
            alt="UIT"
            className="size-[30px] shrink-0 object-contain"
          />
          <div className="flex items-center gap-0.5 rounded-full border border-input bg-card p-1 shadow-[0_1px_2px_rgba(16,22,30,.04)]">
            <ToolButton label="Open sidebar" onClick={onOpenSidebar}>
              <PanelLeft className="size-[18px]" />
            </ToolButton>
            <ToolButton label="Search chats" onClick={onSearch}>
              <Search className="size-[18px]" />
            </ToolButton>
            <ToolButton label="New chat" onClick={onNewChat}>
              <CirclePlus className="size-[18px]" />
            </ToolButton>
          </div>
        </div>
      )}

      {showTitle && (
        <EditableTitle title={title} canEdit={canEdit} onRename={onRename} />
      )}
    </div>
  );
}

function EditableTitle({
  title,
  canEdit,
  onRename,
}: {
  title: string;
  canEdit: boolean;
  onRename: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      ref.current?.focus();
      ref.current?.select();
    }
  }, [editing]);
  useEffect(() => {
    if (!editing) setDraft(title);
  }, [title, editing]);

  const display = title || "Cuộc trò chuyện mới";

  if (!canEdit) {
    return (
      <span className="min-w-0 truncate text-left text-[15px] font-semibold text-foreground">
        {display}
      </span>
    );
  }

  if (editing) {
    const commit = () => {
      const v = draft.trim();
      if (v && v !== title) onRename(v);
      setEditing(false);
    };
    return (
      <input
        ref={ref}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(title);
            setEditing(false);
          }
        }}
        onBlur={commit}
        className="min-w-0 max-w-[420px] flex-1 rounded-md bg-muted px-2 py-1 text-[15px] font-semibold text-foreground no-underline outline-none"
      />
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      title="Đổi tên hội thoại"
      className="min-w-0 max-w-full truncate rounded-md px-2 py-1 text-left text-[15px] font-semibold text-foreground no-underline transition-colors hover:bg-muted"
    >
      {display}
    </button>
  );
}

function ToolButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex size-9 items-center justify-center rounded-full text-[#5b616b] transition-colors hover:bg-muted hover:text-foreground"
    >
      {children}
    </button>
  );
}
