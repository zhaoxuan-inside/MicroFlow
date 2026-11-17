import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@microflow4kit/ui": path.resolve(__dirname, "../MicroFlow4Kit/packages/ui/src/index.ts"),
      "@microflow4kit/api": path.resolve(__dirname, "../MicroFlow4Kit/packages/api/src/index.ts"),
      "@microflow4kit/admin": path.resolve(__dirname, "../MicroFlow4Kit/packages/admin/src/index.tsx"),
    },
  },
  server: {
    port: 4602,
    proxy: {
      "/api": { target: "http://127.0.0.1:3000", changeOrigin: true },
      // 告警等控制面能力：/orch-api → FastAPI 控制面（与编排平台同一后端）
      "/orch-api": {
        target: "http://127.0.0.1:8200",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/orch-api/, "/api"),
      },
    },
  },
});
