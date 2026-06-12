import { useMemo, useState } from "react";
import {
  CirclePlus,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  Pencil,
  Search,
  Star,
  Trash2,
} from "lucide-react";
import type { ConversationSummary } from "../api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  groupConversations,
  loadStarred,
  relativeTime,
  saveStarred,
} from "@/lib/conversations";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  conversations: ConversationSummary[];
  currentId: string | null;
  collapsed: boolean;
  width: number;
  chatsActive: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onToggle: () => void;
  onSearch: () => void;
  onOpenChats: () => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}

export default function Sidebar({
  conversations,
  currentId,
  collapsed,
  width,
  chatsActive,
  onSelect,
  onNew,
  onToggle,
  onSearch,
  onOpenChats,
  onRename,
  onDelete,
}: Props) {
  // ── gắn sao (cục bộ) ──
  const [starred, setStarred] = useState<Set<string>>(() => loadStarred());
  const toggleStar = (id: string) => {
    setStarred((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      saveStarred(next);
      return next;
    });
  };

  // ── đổi tên / xoá ──
  const [renameTarget, setRenameTarget] = useState<ConversationSummary | null>(
    null,
  );
  const [draft, setDraft] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(
    null,
  );
  const openRename = (c: ConversationSummary) => {
    setRenameTarget(c);
    setDraft(c.name);
  };
  const commitRename = () => {
    if (renameTarget && draft.trim()) onRename(renameTarget.id, draft.trim());
    setRenameTarget(null);
  };

  // ── danh sách hiển thị: gom nhóm theo ngày + nhóm sao ──
  const groups = useMemo(
    () => groupConversations(conversations, starred),
    [conversations, starred],
  );
  const hasResults = groups.some((g) => g.items.length > 0);

  return (
    <aside
      style={{ width, marginLeft: collapsed ? -width : 0 }}
      className={cn(
        "flex shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[margin,border-color] duration-[340ms] ease-[cubic-bezier(.4,0,.2,1)]",
      )}
    >
      {/* ── Đỉnh: logo + wordmark + kính lúp + toggle (topbar 56px) ── */}
      <div className="flex h-14 items-center px-3">
        <div className="flex w-full items-center gap-2">
          <img
            src="/favicon.svg"
            alt="UIT"
            className="size-[30px] shrink-0 object-contain"
          />
          <span className="flex-1 truncate text-[22px] font-extrabold tracking-[-0.5px]">
            <span className="text-primary">DVC</span>
            <span className="text-foreground"> RAG</span>
          </span>
          <Button
            variant="ghost"
            onClick={onSearch}
            aria-label="Search chats"
            className="size-[34px] rounded-[9px] text-[#5b616b]"
          >
            <Search className="size-[18px]" />
          </Button>
          <Button
            variant="ghost"
            onClick={onToggle}
            aria-label="Collapse sidebar"
            className="size-[34px] rounded-[9px] text-[#5b616b]"
          >
            <PanelLeftClose className="size-[18px]" />
          </Button>
        </div>
      </div>

      {/* ── New chat (row có viền) + nav Chats (row phẳng) — design (2) §1 ── */}
      <div className="space-y-0.5 px-2.5 pt-3.5 pb-1">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-[11px] rounded-[10px] border border-input bg-background px-3 py-2.5 text-[15px] font-semibold text-foreground shadow-[0_1px_1px_rgba(16,22,30,.02)] transition-colors hover:border-primary/30 hover:bg-accent/50"
        >
          <CirclePlus className="size-[18px] shrink-0" />
          New chat
        </button>
        <button
          onClick={onOpenChats}
          className={cn(
            "flex w-full items-center gap-[11px] rounded-[10px] px-3 py-2.5 text-[15px] font-semibold transition-colors",
            chatsActive
              ? "bg-accent text-primary"
              : "text-[#3a3f47] hover:bg-muted",
          )}
        >
          <MessageSquare className="size-[18px] shrink-0" />
          Chats
        </button>
      </div>

      {/* ── Danh sách hội thoại ── */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {!hasResults && (
          <p className="px-3 py-4 text-[13px] text-muted-foreground">
            No chats yet. Send a message to start.
          </p>
        )}

        {groups.map((g) =>
          g.items.length === 0 ? null : (
            <div key={g.key} className="mb-1">
              <div className="flex items-center gap-1 px-3 py-1.5 text-[12.5px] font-semibold text-muted-foreground">
                {g.key === "starred" && <Star className="size-3 fill-current" />}
                {g.label}
              </div>
              {g.items.map((c) => (
                <ConvRow
                  key={c.id}
                  conv={c}
                  active={c.id === currentId && !chatsActive}
                  starred={starred.has(c.id)}
                  onSelect={() => onSelect(c.id)}
                  onToggleStar={() => toggleStar(c.id)}
                  onRename={() => openRename(c)}
                  onDelete={() => setDeleteTarget(c)}
                />
              ))}
            </div>
          ),
        )}
      </nav>

      <div className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
        DVC RAG · Public administrative procedures assistant
      </div>

      {/* ── Rename dialog ── */}
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(o) => !o && setRenameTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename chat</DialogTitle>
            <DialogDescription>Enter a new name for this chat.</DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitRename()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameTarget(null)}>
              Cancel
            </Button>
            <Button onClick={commitRename} disabled={!draft.trim()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete confirmation dialog ── */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete chat?</DialogTitle>
            <DialogDescription>
              This can't be undone. The chat "{deleteTarget?.name}" will be
              permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (deleteTarget) onDelete(deleteTarget.id);
                setDeleteTarget(null);
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}

// ── Một dòng hội thoại ──────────────────────────────────────────────────────
interface RowProps {
  conv: ConversationSummary;
  active: boolean;
  starred: boolean;
  onSelect: () => void;
  onToggleStar: () => void;
  onRename: () => void;
  onDelete: () => void;
}

function ConvRow({
  conv,
  active,
  starred,
  onSelect,
  onToggleStar,
  onRename,
  onDelete,
}: RowProps) {
  const ts = active ? relativeTime(conv.date_updated) : "";
  return (
    <div
      className={cn(
        "group mb-0.5 flex items-center gap-1 rounded-[10px] px-3 py-[9px] text-[14.5px]",
        active
          ? "bg-sidebar-accent font-semibold text-sidebar-accent-foreground"
          : "hover:bg-muted",
      )}
    >
      <button
        onClick={onSelect}
        className="flex min-w-0 flex-1 flex-col text-left"
        title={conv.name}
      >
        <span className="truncate">{conv.name || "(untitled)"}</span>
        {ts && (
          <span className="mt-0.5 text-[11.5px] font-normal text-muted-foreground">
            {ts}
          </span>
        )}
      </button>

      {/* Sao: hiện thường trực nếu đã gắn, ngược lại hiện khi hover */}
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={onToggleStar}
        aria-label={starred ? "Unstar" : "Star"}
        className={cn(
          "shrink-0",
          starred
            ? "opacity-100"
            : "opacity-0 focus-visible:opacity-100 group-hover:opacity-100",
        )}
      >
        <Star className={cn("size-3.5", starred && "fill-current")} />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Options"
            className="shrink-0 opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100"
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onToggleStar}>
            <Star className={cn(starred && "fill-current")} />
            {starred ? "Unstar" : "Star"}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onRename}>
            <Pencil />
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
