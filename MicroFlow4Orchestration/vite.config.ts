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
    port: 4601,
    proxy: {
      "/orch-api": {
        target: "http://127.0.0.1:8200",
        changeOrigin: true,
        // 控制面路由统一挂在 /api 前缀下；前端 BASE=/orch-api 不带 /api。
        rewrite: (p) => p.replace(/^\/orch-api/, "/api"),
      },
      "/api": { target: "http://127.0.0.1:3000", changeOrigin: true },
    },
  },
});
