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
    },
  },
});
