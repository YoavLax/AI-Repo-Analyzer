import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: `npm run dev` serves the SPA on :5173 and proxies /api to the FastAPI
// server (uvicorn on :8000). Prod: `npm run build` emits dist/, which the
// server serves itself (STATIC_DIR) — same origin, no proxy needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
