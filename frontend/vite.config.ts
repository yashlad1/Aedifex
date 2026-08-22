import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is proxied rather than called cross-origin, so the browser sees one origin and no CORS
// configuration has to exist on a service that has no authentication yet. AEDIFEX_API points at a
// locally running `uvicorn apps.api.main:app`.
const api = process.env["AEDIFEX_API"] ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Loopback only. This viewer reads a corpus whose licence terms differ per source and talks to
    // an API with no authorization; binding it to 0.0.0.0 would publish both on the local network.
    host: "127.0.0.1",
    proxy: {
      "/v1": { target: api, changeOrigin: false },
      "/health": { target: api, changeOrigin: false },
    },
  },
});
