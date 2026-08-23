import type { Config } from "tailwindcss";

/** Design tokens per 4. Design.md — no ad-hoc hex values in components (Rules §7.1). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#4F46E5", hover: "#4338CA" },
        "ai-accent": "#7C3AED",
        cmd: { bg: "#0B1220", surface: "#111A2E", raised: "#17223C", border: "#223052" },
        lightbg: "#F8FAFC",
        ink: { dark: "#F1F5F9", light: "#0F172A", muted: "#94A3B8" },
        success: "#10B981",
        warning: "#F59E0B",
        error: "#EF4444",
        "error-critical": "#DC2626",
        info: "#38BDF8",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        chip: "999px",
        btn: "8px",
        card: "12px",
        drawer: "16px",
      },
      spacing: {
        4: "4px",
        8: "8px",
        12: "12px",
        16: "16px",
        24: "24px",
        32: "32px",
        48: "48px",
      },
    },
  },
  plugins: [],
} satisfies Config;
