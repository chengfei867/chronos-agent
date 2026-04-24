import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Chronos Viewer build config.
// - base: "/app/" because the FastAPI server mounts dist/ at /app (not /).
//   Must end with a trailing slash so asset URLs resolve under /app/assets/...
// - Dev proxy forwards /runs /healthz to the local `chronos web` server so
//   `npm run dev` works without CORS hacks when hacking on the UI.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Inline any asset <4KB — fewer files in dist/ means less to ship in git.
    assetsInlineLimit: 4096,
    // Source maps off for shipped bundles; the JS is 200KB-ish — easy to debug
    // from the readable output if it ever matters. Saves ~500KB in git.
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/runs": "http://127.0.0.1:8765",
      "/healthz": "http://127.0.0.1:8765",
    },
  },
});
