import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8899",
      "/webhooks": "http://localhost:8899",
      "/healthz": "http://localhost:8899",
    },
  },
});
