import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// En desarrollo, /api va al servidor LocalHarness (LOCALHARNESS_SERVER o el puerto por defecto 8095).
const server = process.env.LOCALHARNESS_SERVER ?? "http://127.0.0.1:8095";

export default defineConfig({
  plugins: [vue()],
  server: { port: 5174, proxy: { "/api": { target: server, changeOrigin: false } } },
  build: { outDir: "dist", emptyOutDir: true },
});
