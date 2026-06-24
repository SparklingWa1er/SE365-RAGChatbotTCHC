import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "./api/client";
import type { Citation, ConversationSummary } from "./api/types";
import { stripHtml } from "./lib/conversations";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import ChatsPage from "./components/ChatsPage";
import ChatTopbar from "./components/ChatTopbar";
import SourcesPanel from "./components/SourcesPanel";
import ResizeHandle from "./components/ResizeHandle";
import SearchModal, { type SearchResult } from "./components/SearchModal";

const clamp = (v: number, min: number, max: number) =>
  Math.min(max, Math.max(min, v));

type Page = "home" | "chats";

// Chế độ suy luận = id engine backend (reasoning_type): ReAct (agentic) | simple (RAG tuyến tính).
export type ReasoningMode = "ReAct" | "simple";

// Một lượt hiển thị trong khung chat.
export interface Turn {
  user: string;
  bot: string; // HTML (có thể chứa <a class="citation">)
  info?: string; // HTML quá trình suy luận (Thought/Action/Observation + mindmap)
  citations?: Citation[]; // nguồn của lượt này (khôi phục panel khi mở lại)
}

export default function App() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(288); // kéo được (w-72)
  const [sourcesWidth, setSourcesWidth] = useState(320); // kéo được (w-80)
  const [page, setPage] = useState<Page>("home"); // "home" = chat | "chats" = trang lịch sử
  const [mode, setMode] = useState<ReasoningMode>("ReAct"); // engine chọn ở màn hình new conversation
  const [turns, setTurns] = useState<Turn[]>([]);
  const [suggestions, setSuggestions] = useState<string[][]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [infoHtml, setInfoHtml] = useState("");
  // Citation 【n】 vừa được bấm trong câu trả lời → SourcesPanel mở + cuộn tới nguồn đó.
  // nonce để cùng một số bấm lại vẫn kích hoạt lại hiệu ứng.
  const [activeCite, setActiveCite] = useState<{ index: number; nonce: number } | null>(
    null,
  );

  // Trạng thái stream lượt hiện tại.
  const [streaming, setStreaming] = useState(false);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [streamBot, setStreamBot] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  // Bản mới nhất của bot text/info — đọc trong finally mà không lồng setState
  // (lồng setState trong updater bị StrictMode gọi 2 lần → nhân đôi lượt).
  const streamBotRef = useRef("");
  const streamInfoRef = useRef("");
  const streamCitationsRef = useRef<Citation[]>([]);

  // ── Search Modal (tìm trong HỘI THOẠI HIỆN TẠI) ──
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // Tin nhắn cần cuộn lên đầu sau khi chọn kết quả: "<turnIndex>-user|bot".
  const [scrollTarget, setScrollTarget] = useState<string | null>(null);

  // ── tải danh sách hội thoại + gợi ý mặc định lúc mở app ──
  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshConversations();
    api.defaultSuggestions().then(setSuggestions).catch(() => {});
  }, [refreshConversations]);

  // ── chọn / tải một hội thoại ──
  const openConversation = useCallback(async (id: string) => {
    setPage("home");
    setCurrentId(id);
    setCitations([]);
    setInfoHtml("");
    try {
      const d = await api.getConversation(id);
      setTurns(
        d.messages.map(([user, bot], i) => ({
          user,
          bot,
          info: d.reasoning?.[i] ?? "",
          citations: d.citations?.[i] ?? [],
        })),
      );
      // Khôi phục panel "Nguồn" bằng nguồn của lượt cuối (câu trả lời gần nhất).
      const lastCitations = d.citations?.length
        ? d.citations[d.citations.length - 1]
        : [];
      setCitations(lastCitations ?? []);
      setSuggestions(d.chat_suggestions?.length ? d.chat_suggestions : []);
    } catch (e) {
      console.error(e);
      setTurns([]);
    }
  }, []);

  const newConversation = useCallback(() => {
    // Không tạo ngay trên server — để lượt chat đầu tiên tự tạo (conversation_id=null).
    setPage("home");
    setCurrentId(null);
    setTurns([]);
    setCitations([]);
    setInfoHtml("");
    api.defaultSuggestions().then(setSuggestions).catch(() => {});
  }, []);

  // ── gửi một tin nhắn (stream) ──
  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || streaming) return;

      setStreaming(true);
      setPendingUser(text);
      setStreamBot("");
      streamBotRef.current = "";
      streamInfoRef.current = "";
      streamCitationsRef.current = [];
      setCitations([]);
      setInfoHtml("");
      setSuggestions([]);

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let convId = currentId;

      try {
        await api.streamChat(
          {
            conversation_id: currentId,
            message: text,
            settings_override: { reasoning_type: mode },
          },
          {
            onConversationId: (id) => {
              convId = id;
              if (!currentId) setCurrentId(id);
            },
            onReset: () => {
              streamBotRef.current = "";
              setStreamBot("");
            },
            onAnswer: (html) => {
              streamBotRef.current = html;
              setStreamBot(html);
            },
            onInfo: (html) => {
              streamInfoRef.current = html;
              setInfoHtml(html);
            },
            onCitations: (items) => {
              streamCitationsRef.current = items;
              setCitations(items);
            },
            onDone: (e) => {
              setSuggestions(e.suggestions ?? []);
              // Tên hội thoại vừa được tự đặt (lượt đầu) → cập nhật danh sách ngay.
              if (e.name) refreshConversations();
            },
          },
          ctrl.signal,
        );
      } catch (e) {
        console.error(e);
        if (!streamBotRef.current) {
          streamBotRef.current = `<p class="text-destructive">Lỗi khi gọi máy chủ: ${
            (e as Error).message
          }</p>`;
        }
      } finally {
        // chốt lượt vào danh sách từ ref (không lồng setState → không nhân đôi)
        const finalBot = streamBotRef.current;
        const finalInfo = streamInfoRef.current;
        const finalCitations = streamCitationsRef.current;
        setTurns((prev) => [
          ...prev,
          { user: text, bot: finalBot, info: finalInfo, citations: finalCitations },
        ]);
        setStreamBot("");
        streamBotRef.current = "";
        streamInfoRef.current = "";
        streamCitationsRef.current = [];
        setPendingUser(null);
        setStreaming(false);
        abortRef.current = null;
        if (!currentId && convId) setCurrentId(convId);
        refreshConversations();
      }
    },
    [currentId, streaming, mode, refreshConversations],
  );

  // ── dừng stream ──
  const stop = useCallback(async () => {
    if (currentId) await api.stopChat(currentId);
    abortRef.current?.abort();
  }, [currentId]);

  // ── regen: gửi lại câu hỏi cuối ──
  const regen = useCallback(() => {
    if (streaming || turns.length === 0) return;
    const last = turns[turns.length - 1];
    setTurns((prev) => prev.slice(0, -1));
    send(last.user);
  }, [streaming, turns, send]);

  // ── mở Search Modal (chỉ tìm trong hội thoại đang mở) ──
  const openSearch = useCallback(() => {
    setSearchQuery("");
    setSearchOpen(true);
  }, []);

  const openChats = useCallback(() => setPage("chats"), []);

  // mỗi tin nhắn (user/bot) trong hội thoại hiện tại khớp chuỗi → một kết quả
  const results = useMemo<SearchResult[]>(() => {
    const t = searchQuery.trim().toLowerCase();
    if (!t) return [];
    const out: SearchResult[] = [];
    turns.forEach(({ user, bot }, i) => {
      const u = (user || "").trim();
      if (u && u.toLowerCase().includes(t))
        out.push({ key: `${i}-user`, title: "Bạn", role: "user", turnIndex: i, text: u });
      const b = stripHtml(bot || "");
      if (b && b.toLowerCase().includes(t))
        out.push({ key: `${i}-bot`, title: "Trợ lý", role: "bot", turnIndex: i, text: b });
    });
    return out;
  }, [turns, searchQuery]);

  // chọn 1 kết quả → đóng modal + cuộn tin nhắn đó lên đầu (cùng hội thoại)
  const pickResult = useCallback((r: SearchResult) => {
    setSearchOpen(false);
    setScrollTarget(`${r.turnIndex}-${r.role}`);
  }, []);

  // Bấm 【n】 trong một câu trả lời → nạp đúng nguồn của lượt đó vào panel + làm nổi 【n】.
  const handleCitationClick = useCallback((cits: Citation[], n: number) => {
    if (cits && cits.length) setCitations(cits);
    setActiveCite({ index: n, nonce: Date.now() });
  }, []);

  // tiêu đề hội thoại đang chọn + đổi tên ngay trên topbar
  const currentTitle = useMemo(
    () => conversations.find((c) => c.id === currentId)?.name ?? "",
    [conversations, currentId],
  );
  const renameCurrent = useCallback(
    async (name: string) => {
      if (!currentId) return;
      await api.renameConversation(currentId, name);
      refreshConversations();
    },
    [currentId, refreshConversations],
  );

  return (
    <div className="flex h-full w-full overflow-hidden bg-background text-foreground">
      <Sidebar
        conversations={conversations}
        currentId={currentId}
        collapsed={!sidebarOpen}
        width={sidebarWidth}
        chatsActive={page === "chats"}
        onSelect={openConversation}
        onNew={newConversation}
        onToggle={() => setSidebarOpen(false)}
        onSearch={openSearch}
        onOpenChats={openChats}
        onRename={async (id, name) => {
          await api.renameConversation(id, name);
          refreshConversations();
        }}
        onDelete={async (id) => {
          await api.deleteConversation(id);
          if (id === currentId) newConversation();
          refreshConversations();
        }}
      />

      {sidebarOpen && (
        <ResizeHandle
          onResize={(dx) =>
            setSidebarWidth((w) => clamp(w + dx, 220, 480))
          }
        />
      )}

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Topbar: tiêu đề hội thoại (đổi tên được) + tools khi sidebar đóng */}
        <ChatTopbar
          collapsed={!sidebarOpen}
          showTitle={page === "home"}
          title={currentTitle}
          canEdit={currentId !== null}
          onRename={renameCurrent}
          onOpenSidebar={() => setSidebarOpen(true)}
          onSearch={openSearch}
          onNewChat={newConversation}
        />

        {page === "chats" ? (
          <ChatsPage
            conversations={conversations}
            onOpen={openConversation}
            onNew={newConversation}
          />
        ) : (
          <ChatView
            turns={turns}
            pendingUser={pendingUser}
            streamBot={streamBot}
            streamInfo={infoHtml}
            streamCitations={citations}
            streaming={streaming}
            suggestions={suggestions}
            canRegen={turns.length > 0 && !streaming}
            scrollTarget={scrollTarget}
            mode={mode}
            onModeChange={setMode}
            onScrolled={() => setScrollTarget(null)}
            onSend={send}
            onStop={stop}
            onRegen={regen}
            onCitationClick={handleCitationClick}
          />
        )}
      </div>

      <ResizeHandle
        onResize={(dx) => setSourcesWidth((w) => clamp(w - dx, 260, 600))}
      />

      <SourcesPanel citations={citations} width={sourcesWidth} active={activeCite} />

      <SearchModal
        open={searchOpen}
        query={searchQuery}
        setQuery={setSearchQuery}
        results={results}
        onPick={pickResult}
        onClose={() => setSearchOpen(false)}
      />
    </div>
  );
}
