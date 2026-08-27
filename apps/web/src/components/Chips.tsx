import type { ReactNode } from "react";

/** Status/diagnosis chips — updated to Reflex v2.0 tokens, props intact for callers. */
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
    slate: "bg-surface-variant text-on-surface-variant border-outline-variant",
    violet: "bg-primary-fixed text-on-primary-fixed-variant border-primary-fixed-dim",
    green: "bg-secondary-fixed/40 text-secondary border-secondary-fixed-dim",
    amber: "bg-tertiary-fixed text-on-tertiary-fixed border-tertiary-fixed-dim",
    red: "bg-error-container text-on-error-container border-error",
    blue: "bg-surface-container-high text-on-surface border-outline-variant",
  };
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[10px] font-mono font-medium uppercase tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** Mandatory honesty badges (Rules §7.3) — must stay visible. */
export function SimulatedBadge() {
  return (
    <span className="inline-flex items-center rounded border border-on-tertiary-container text-on-tertiary-container px-2 py-1 text-[10px] font-mono font-semibold tracking-widest uppercase">
      [SIMULATED]
    </span>
  );
}

export function TestModeBadge() {
  return (
    <span className="inline-flex items-center rounded border border-outline text-outline px-2 py-1 text-[10px] font-mono font-semibold tracking-widest uppercase">
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
