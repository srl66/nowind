import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { llmProxy } from "./vite-plugin-llm-proxy";

// Tauri 期望固定端口；浏览器里跑 `npm run dev` 也是同一个地址。
export default defineConfig({
  plugins: [vue(), llmProxy()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    open: true, // cmd 里 npm run dev 后自动拉起浏览器
    watch: { ignored: ["**/src-tauri/**"] },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: "chrome105",
    minify: "esbuild",
    sourcemap: false,
  },
});
