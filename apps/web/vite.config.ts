import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Hard guard: a production build without the API origin produces a
  // same-origin bundle that silently 405s/polls nginx forever. Fail loud.
  // Check both .env files (loadEnv) and process.env (Vercel/Railway build
  // env vars are injected as process.env, which loadEnv does not guarantee
  // to merge).
  if (mode === "production") {
    const env = loadEnv(mode, process.cwd(), "");
    const apiBase = env.VITE_REFLEX_API ?? env.VITE_API_URL ?? process.env.VITE_REFLEX_API ?? process.env.VITE_API_URL;
    if (!apiBase) {
      throw new Error(
        "Refusing to build: VITE_REFLEX_API is not set (e.g. https://reflex-api.example.com). On Vercel set it in Project Settings → Environment Variables (build), then Redeploy.",
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
