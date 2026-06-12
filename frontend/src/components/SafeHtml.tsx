import DOMPurify from "dompurify";
import { useMemo } from "react";

// Render HTML thô từ backend (answer/info) sau khi sanitize.
// Giữ lại class & target để link citation 【n】 và <details> hoạt động.
export default function SafeHtml({
  html,
  className,
}: {
  html: string;
  className?: string;
}) {
  const clean = useMemo(
    () =>
      DOMPurify.sanitize(html, {
        ADD_ATTR: ["target", "class", "data-id", "open"],
      }),
    [html],
  );
  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}
