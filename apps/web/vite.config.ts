import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Hard guard: a production build without the API origin produces a
  // same-origin bundle that silently 405s/polls nginx forever. Fail loud.
  if (mode === "production") {
    const env = loadEnv(mode, process.cwd(), "");
    if (!env.VITE_REFLEX_API) {
      throw new Error(
        "Refusing to build: VITE_REFLEX_API is not set (e.g. https://reflex-api.example.com). Set it in .env or the platform's build env.",
      );
    }
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": "http://localhost:8899",
        "/webhooks": "http://localhost:8899",
        "/healthz": "http://localhost:8899",
      },
    },
  };
});
