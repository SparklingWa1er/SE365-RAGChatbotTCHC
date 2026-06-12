import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Dev server: proxy /api -> FastAPI (app/api) để tránh CORS và không hardcode host.
// Chạy backend trước: .venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  // Host LAN nội bộ: `npm run build` rồi `npm run preview`.
  // preview KHÔNG dùng server.proxy → phải khai báo proxy riêng ở đây.
  // host: true → mở trên mọi interface để máy khác trong LAN truy cập.
  preview: {
    host: true,
    port: 4173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
