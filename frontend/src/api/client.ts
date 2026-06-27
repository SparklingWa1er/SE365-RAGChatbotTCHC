// Client gọi /api: REST wrappers + streamChat() đọc SSE qua fetch + ReadableStream.
// (Không dùng EventSource vì /api/chat là POST có body.)

import type {
  ChatRequest,
  ConversationDetail,
  ConversationSummary,
  GeocodeResult,
  NearbyResult,
  SseEvent,
  StreamHandlers,
} from "./types";

const BASE = "/api"; // dev: Vite proxy -> http://127.0.0.1:8000

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── REST: conversations ────────────────────────────────────────────────────
export async function listConversations(): Promise<ConversationSummary[]> {
  const d = await json<{ conversations: ConversationSummary[] }>(
    await fetch(`${BASE}/conversations`),
  );
  return d.conversations;
}

export async function createConversation(
  name?: string,
): Promise<ConversationSummary> {
  return json(
    await fetch(`${BASE}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name ?? null }),
    }),
  );
}

export async function getConversation(
  id: string,
): Promise<ConversationDetail> {
  return json(await fetch(`${BASE}/conversations/${id}`));
}

export async function renameConversation(
  id: string,
  name: string,
): Promise<ConversationDetail> {
  return json(
    await fetch(`${BASE}/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${BASE}/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Xoá thất bại: ${res.status}`);
}

// ── REST: suggestions ──────────────────────────────────────────────────────
export async function defaultSuggestions(): Promise<string[][]> {
  const d = await json<{ suggestions: string[][] }>(
    await fetch(`${BASE}/suggestions/default`),
  );
  return d.suggestions;
}

// ── Places: địa điểm xử lý thủ tục gần người dùng ──────────────────────────
export async function nearbyPlaces(req: {
  agency: string;
  lat?: number;
  lng?: number;
  address?: string;
  hint?: string;
}): Promise<NearbyResult> {
  return json(
    await fetch(`${BASE}/places/nearby`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}

export async function geocodePlace(address: string): Promise<GeocodeResult> {
  return json(
    await fetch(`${BASE}/places/geocode`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address }),
    }),
  );
}

// ── Chat: stop ─────────────────────────────────────────────────────────────
export async function stopChat(conversationId: string): Promise<void> {
  await fetch(`${BASE}/chat/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId }),
  }).catch(() => {});
}

// ── Chat: stream SSE ───────────────────────────────────────────────────────
// Đọc body stream, tách khung theo "\n\n", parse các dòng "data: <json>".
// Gọi các handler tương ứng. signal để hủy (kèm stopChat ở phía gọi).
export async function streamChat(
  req: ChatRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Chat lỗi: ${res.status} ${res.statusText}`);
  }

  const convId = res.headers.get("X-Conversation-Id");
  if (convId) handlers.onConversationId?.(convId);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (ev: SseEvent) => {
    switch (ev.type) {
      case "answer":
        handlers.onAnswer?.(ev.text);
        break;
      case "answer.reset":
        handlers.onReset?.();
        break;
      case "info":
        handlers.onInfo?.(ev.html);
        break;
      case "plot":
        handlers.onPlot?.(ev.spec);
        break;
      case "citations":
        handlers.onCitations?.(ev.items);
        break;
      case "done":
        handlers.onDone?.(ev);
        break;
    }
  };

  // Một khung có thể chứa nhiều dòng; lấy phần sau "data:" của từng dòng rồi nối.
  const handleFrame = (frame: string) => {
    const dataLines = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart());
    if (dataLines.length === 0) return;
    const payload = dataLines.join("\n");
    try {
      dispatch(JSON.parse(payload) as SseEvent);
    } catch {
      // khung không phải JSON hợp lệ — bỏ qua
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        if (frame.trim()) handleFrame(frame);
      }
    }
    // flush khung cuối nếu stream kết thúc không kèm "\n\n"
    if (buffer.trim()) handleFrame(buffer);
  } catch (e) {
    if ((e as Error).name === "AbortError") return; // hủy chủ động — im lặng
    throw e;
  } finally {
    reader.releaseLock();
  }
}
