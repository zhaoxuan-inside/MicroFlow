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
      // i18n 栈统一指向 Kit 的单一实例：本 SPA 直接 import react-i18next，
      // 双实例会导致 useTranslation 订阅不到 initI18n 初始化的那个实例
      "i18next": path.resolve(__dirname, "../MicroFlow4Kit/node_modules/i18next"),
      "react-i18next": path.resolve(__dirname, "../MicroFlow4Kit/node_modules/react-i18next"),
      "i18next-browser-languagedetector": path.resolve(__dirname, "../MicroFlow4Kit/node_modules/i18next-browser-languagedetector"),
    },
  },
  server: {
    port: 4603,
    proxy: {
      "/api": { target: "http://127.0.0.1:3000", changeOrigin: true },
    },
  },
});
