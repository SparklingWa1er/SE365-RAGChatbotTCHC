import { useCallback } from "react";

// Thanh kéo dọc phân tách cột — kéo để đổi chiều rộng. onResize nhận delta px theo trục X.
export default function ResizeHandle({
  onResize,
}: {
  onResize: (dx: number) => void;
}) {
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      let last = e.clientX;
      const move = (ev: PointerEvent) => {
        onResize(ev.clientX - last);
        last = ev.clientX;
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [onResize],
  );

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      className="z-10 w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-primary/40"
    />
  );
}
