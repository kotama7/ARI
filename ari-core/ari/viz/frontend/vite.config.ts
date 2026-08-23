import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const frontendDir = import.meta.dirname;

export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: resolve(frontendDir, "../static/dist"),
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": resolve(frontendDir, "src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
      "/state": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8765",
        ws: true,
      },
    },
  },
});
