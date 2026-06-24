// Kiểu dữ liệu khớp hợp đồng API (xem frontend/README.md + docs/api-architecture.md).

export interface ConversationSummary {
  id: string;
  name: string;
  date_updated?: string | null;
}

export interface ConversationDetail {
  id: string;
  name: string;
  is_public: boolean;
  messages: [string, string][]; // [[user, bot], ...]
  chat_suggestions: string[][]; // [["câu 1"], ["câu 2"], ...]
  selected: Record<string, unknown>;
  reasoning?: string[]; // HTML suy luận theo từng lượt (khớp 1-1 với messages)
  citations?: Citation[][]; // nguồn theo từng lượt (khớp 1-1 với messages)
}

export interface Citation {
  indices: number[]; // số 【n】 trỏ về nguồn này
  title: string; // tên thủ tục, hoặc nhãn 🌐 ... · web
  snippet: string; // đoạn được trích (đã ghép các span)
  score: number | null; // llm_trulens_score
  is_web: boolean; // true = nguồn web (Brave), chưa thẩm định
  url: string | null; // link nếu là nguồn web
  cited: boolean; // true = được trích (có 【n】); false = tham khảo
  content_html: string; // toàn văn nội dung gốc (HTML, có <mark> + 【n】 inline)
}

export interface SettingsOverride {
  reasoning_type?: string; // "ReAct" | "simple" | "decompose" | "ReWOO"
  llm?: string;
  language?: string; // "vi" | "en"
  use_mindmap?: boolean;
  use_citation?: string; // "inline" | "off"
}

export interface ChatRequest {
  conversation_id?: string | null;
  message: string;
  settings_override?: SettingsOverride;
  selected_file_ids?: string[];
}

// ── SSE events (mỗi khung là `data: <json>\n\n`) ───────────────────────────
export type SseEvent =
  | { type: "answer.reset" }
  | { type: "answer"; text: string }
  | { type: "info"; html: string }
  | { type: "plot"; spec: unknown }
  | { type: "citations"; items: Citation[] }
  | {
      type: "done";
      conversation_id: string;
      suggestions: string[][];
      cancelled?: boolean;
      name?: string; // tên hội thoại (đã tự đặt ở lượt đầu) — cập nhật topbar ngay
    };

// Handler do UI cung cấp; mọi event answer/info đều là TRẠNG THÁI ĐẦY ĐỦ (ghi đè).
export interface StreamHandlers {
  onAnswer?: (fullHtml: string) => void;
  onReset?: () => void;
  onInfo?: (fullHtml: string) => void;
  onPlot?: (spec: unknown) => void;
  onCitations?: (items: Citation[]) => void;
  onDone?: (e: {
    conversation_id: string;
    suggestions: string[][];
    cancelled?: boolean;
    name?: string;
  }) => void;
  onConversationId?: (id: string) => void; // từ header X-Conversation-Id
}
