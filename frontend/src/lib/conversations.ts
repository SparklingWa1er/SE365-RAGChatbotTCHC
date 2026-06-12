// Tiện ích cho danh sách hội thoại ở sidebar: gắn sao (localStorage),
// gom nhóm theo ngày kiểu Claude (Hôm nay / Hôm qua / 7 ngày qua / …),
// và định dạng mốc thời gian tương đối tiếng Việt.

import type { ConversationSummary } from "../api/types";

// ── Gắn sao (lưu cục bộ trên trình duyệt — app dùng một người) ──────────────
const STAR_KEY = "dvc.starred";

export function loadStarred(): Set<string> {
  try {
    const raw = localStorage.getItem(STAR_KEY);
    return new Set<string>(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function saveStarred(ids: Set<string>): void {
  try {
    localStorage.setItem(STAR_KEY, JSON.stringify([...ids]));
  } catch {
    // hết quota / chế độ riêng tư — bỏ qua, không chặn UI
  }
}

// ── Gỡ thẻ HTML + gộp khoảng trắng (câu trả lời bot là HTML thô) ────────────
export function stripHtml(html: string): string {
  return (html || "")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

// ── Bỏ dấu để tìm kiếm không phân biệt dấu tiếng Việt ───────────────────────
export function deburr(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

// ── Mốc thời gian tương đối ("just now", "3 hr ago", "12/05/2026, 14:30") ──
export function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const ms = d.getTime();
  if (Number.isNaN(ms)) return "";
  const diff = Date.now() - ms;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.floor(hr / 24);
  if (day === 1) return "yesterday";
  if (day < 7) return `${day} days ago`;
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ── Gom nhóm theo ngày ──────────────────────────────────────────────────────
export interface ConvGroup {
  key: string;
  label: string;
  items: ConversationSummary[];
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/**
 * Trả về các nhóm theo thứ tự hiển thị. Hội thoại đã gắn sao được tách ra nhóm
 * "Đã gắn sao" ở đầu (không lặp lại trong nhóm ngày). Phần còn lại xếp theo:
 * Hôm nay → Hôm qua → 7 ngày qua → 30 ngày qua → theo tháng/năm.
 */
export function groupConversations(
  convs: ConversationSummary[],
  starred: Set<string>,
): ConvGroup[] {
  const todayStart = startOfDay(new Date());
  const DAY = 86_400_000;

  const starGroup: ConversationSummary[] = [];
  const buckets = new Map<string, ConvGroup>();
  // Giữ thứ tự chèn cố định cho 4 mốc cố định:
  const ensure = (key: string, label: string) => {
    let g = buckets.get(key);
    if (!g) {
      g = { key, label, items: [] };
      buckets.set(key, g);
    }
    return g;
  };

  for (const c of convs) {
    if (starred.has(c.id)) {
      starGroup.push(c);
      continue;
    }
    const t = c.date_updated ? new Date(c.date_updated).getTime() : NaN;
    if (Number.isNaN(t)) {
      ensure("older", "Older").items.push(c);
      continue;
    }
    const dayStart = startOfDay(new Date(t));
    const daysAgo = Math.round((todayStart - dayStart) / DAY);
    if (daysAgo <= 0) ensure("today", "Today").items.push(c);
    else if (daysAgo === 1) ensure("yesterday", "Yesterday").items.push(c);
    else if (daysAgo <= 7) ensure("week", "Previous 7 Days").items.push(c);
    else if (daysAgo <= 30) ensure("month", "Previous 30 Days").items.push(c);
    else {
      const d = new Date(t);
      const key = `m-${d.getFullYear()}-${d.getMonth()}`;
      const label = d.toLocaleDateString("en-US", {
        month: "long",
        year: "numeric",
      });
      ensure(key, label).items.push(c);
    }
  }

  const ORDER = ["today", "yesterday", "week", "month"];
  const fixed = ORDER.map((k) => buckets.get(k)).filter(Boolean) as ConvGroup[];
  const months = [...buckets.values()]
    .filter((g) => g.key.startsWith("m-"))
    .sort((a, b) => (a.key < b.key ? 1 : -1)); // mới → cũ
  const older = buckets.get("older");

  const out: ConvGroup[] = [];
  if (starGroup.length)
    out.push({ key: "starred", label: "Starred", items: starGroup });
  out.push(...fixed, ...months);
  if (older) out.push(older);
  return out;
}
