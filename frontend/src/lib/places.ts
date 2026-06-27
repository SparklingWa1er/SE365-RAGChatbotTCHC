// Đoán "cơ quan thực hiện" từ nội dung hội thoại để prefill ô tìm địa điểm.
// Heuristic nhẹ phía client — người dùng luôn sửa được ô này trong dialog.

import { stripHtml } from "./conversations";

// Ký tự không thể nằm trong tên cơ quan (dùng để chặn cụm bắt được). Loại trừ dấu
// trích dẫn 【】, ngoặc, gạch — tránh nuốt nhiễu kiểu "Công an 【1】".
const STOP = "[^.,;:\\n()【】\\[\\]–—-]";

// Các tiền tố cơ quan hành chính VN phổ biến → bắt cụm danh từ đứng sau.
const AGENCY_PATTERNS: RegExp[] = [
  /(Phòng Quản lý xuất nhập cảnh)/i,
  /(Cục Quản lý xuất nhập cảnh)/i,
  /(Sở Tư pháp)/i,
  /(Sở Kế hoạch và Đầu tư)/i,
  new RegExp(`(Sở [A-ZĐÀ-Ỹ]${STOP}{2,40})`),
  new RegExp(`(Phòng [A-ZĐÀ-Ỹ]${STOP}{2,40})`),
  new RegExp(`(Cục [A-ZĐÀ-Ỹ]${STOP}{2,40})`),
  new RegExp(`(Ủy ban nhân dân ${STOP}{2,40})`, "i"),
  new RegExp(`(UBND ${STOP}{2,40})`, "i"),
  new RegExp(`(Công an ${STOP}{2,40})`, "i"),
  /(Bảo hiểm xã hội)/i,
  new RegExp(`(Chi cục [A-ZĐÀ-Ỹ]${STOP}{2,40})`),
];

/** Trả cụm cơ quan đầu tiên tìm thấy trong text, đã cắt gọn. "" nếu không có. */
function matchAgency(raw: string): string {
  // Bỏ ký hiệu trích dẫn 【n】 / [n] trước khi dò để không lẫn vào tên cơ quan.
  const text = (raw || "").replace(/【[^】]*】/g, " ").replace(/\[\d+\]/g, " ");
  for (const re of AGENCY_PATTERNS) {
    const m = text.match(re);
    if (m) {
      // cắt đuôi từ thừa (giới từ/khoảng trắng) cho gọn
      return m[1]
        .trim()
        .replace(/\s+/g, " ")
        .replace(/\s+(tại|ở|của|thuộc|để|khi|và|hoặc)$/i, "");
    }
  }
  return "";
}

/**
 * Đoán cơ quan từ các lượt hội thoại (ưu tiên câu trả lời mới nhất → cũ, rồi câu hỏi).
 * Trả "" nếu không đoán được — dialog sẽ để user tự nhập.
 */
export function guessAgency(
  turns: { user: string; bot: string }[],
): string {
  for (let i = turns.length - 1; i >= 0; i--) {
    const fromBot = matchAgency(stripHtml(turns[i].bot || ""));
    if (fromBot) return fromBot;
    const fromUser = matchAgency(turns[i].user || "");
    if (fromUser) return fromUser;
  }
  return "";
}
