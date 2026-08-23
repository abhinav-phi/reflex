import type { ReactNode } from "react";

/** Status/diagnosis chips per Design §12 — icon+text, never color-only. */
export function Chip({
  tone = "slate",
  children,
  title,
}: {
  tone?: "slate" | "violet" | "green" | "amber" | "red" | "blue";
  children: ReactNode;
  title?: string;
}) {
  const tones: Record<string, string> = {
    slate: "bg-slate-700/40 text-slate-200 border-slate-500/50",
    violet: "bg-violet-600/20 text-violet-200 border-violet-500/60",
    green: "bg-emerald-600/20 text-emerald-200 border-emerald-500/60",
    amber: "bg-amber-600/20 text-amber-100 border-amber-500/60",
    red: "bg-red-600/20 text-red-200 border-red-500/60",
    blue: "bg-sky-600/20 text-sky-100 border-sky-500/60",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-chip border px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** Mandatory honesty badge (Rules §7.3, Design §12). */
export function SimulatedBadge() {
  return (
    <span className="inline-flex items-center rounded-chip border border-amber-400/70 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-300">
      [SIMULATED]
    </span>
  );
}

export function TestModeBadge() {
  return (
    <span className="inline-flex items-center rounded-chip border border-indigo-400/70 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-indigo-300">
      [TEST MODE]
    </span>
  );
}

const STATUS_TONE: Record<string, "slate" | "violet" | "green" | "amber" | "red" | "blue"> = {
  recovered: "green",
  waiting_diagnosis: "slate",
  diagnosed: "slate",
  scheduled: "blue",
  acted: "blue",
  observing: "blue",
  waiting_approval: "amber",
  stopped_low_ev: "slate",
  stopped_cap: "amber",
  expired: "slate",
  stopped_customer: "red",
  stopped_approval_declined: "red",
  escalated: "amber",
  halted: "red",
};

export function StatusChip({ status }: { status: string }) {
  return (
    <Chip tone={STATUS_TONE[status] ?? "slate"} title={status}>
      {status.replace(/_/g, " ")}
    </Chip>
  );
}

export function DiagnosisChip({ d }: { d?: { canonical_code: string; confidence: number; method: string } | null }) {
  if (!d) return <Chip tone="slate">undiagnosed</Chip>;
  if (d.canonical_code === "UNKNOWN_AMBIGUOUS")
    return (
      <Chip tone="slate" title="conservative default applied">
        ⚠ UNKNOWN_AMBIGUOUS
      </Chip>
    );
  if (d.method === "rule") return <Chip title="rules match">{d.canonical_code}</Chip>;
  return (
    <Chip tone="violet" title={`LLM confidence ${d.confidence}`}>
      ✦ LLM · {d.confidence.toFixed(2)}
    </Chip>
  );
}
