import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Hard guard: a production build without the API origin produces a
  // same-origin bundle that silently 405s/polls nginx forever. Fail loud.
  // Check both .env files (loadEnv) and process.env (Vercel/Railway build
  // env vars are injected as process.env, which loadEnv does not guarantee
  // to merge).
  // GitHub Actions runs `npm run build` purely as a compile gate — that
  // bundle is never deployed (Vercel builds from git with the project env
  // var), so the guard would fail there for no reason.
  if (mode === "production" && process.env.GITHUB_ACTIONS !== "true") {
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
    build: {
      rollupOptions: {
        output: {
          // recharts + its d3 internals in their own chunks: keeps the main
          // bundle under Vite's size warning AND makes the chart chunks
          // cache-stable (recharts is only used by /results).
          manualChunks(id: string) {
            if (id.includes("node_modules/d3-")) return "charts-core";
            if (id.includes("node_modules/recharts")) return "charts";
            return undefined;
          },
        },
      },
    },
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
