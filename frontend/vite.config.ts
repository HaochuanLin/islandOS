import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The proxy target follows the API port chosen at start-up; 8766 stays the default.
// scripts/start_console.ps1 sets this variable when -ApiPort is not 8766.
const apiTarget = process.env.ISLANDOS_API_TARGET ?? "http://127.0.0.1:8766";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false
      }
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        main: "index.html",
        "application-views": "application-views.html"
      }
    }
  }
});
