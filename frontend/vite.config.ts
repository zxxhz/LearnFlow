import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发期：5173 端口，/api 代理到本地后端
// 构建期：产物直接输出到 backend/app/static，由 FastAPI 托管（PRD §7.1）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8420",
    },
  },
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
  },
});
