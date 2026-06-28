/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버: 프론트는 항상 /api/... 로 호출하고, 아래 프록시가 FastAPI(8000)로 넘긴다.
// /api prefix 는 rewrite 로 제거 → FastAPI 는 /me, /recommend 등 그대로 받는다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: false,
  },
});
