import type { ReactNode } from "react";

/** Action Preview Card — mandatory trust pattern (Design §15 / Rules §4.4).
 *  WHAT/WHY/IMPACT/RISK/GATE/APPROVAL/REVERSIBILITY always present. */
export function ActionPreviewCard({
  what,
  why,
  impact,
  risk,
  gate,
  approval,
  reversibility = "message only — cannot move money; stop = suppression (instant)",
  message,
}: {
  what: string;
  why: string;
  impact: string;
  risk?: string;
  gate?: string;
  approval?: string;
  reversibility?: string;
  message?: string | null;
}) {
  const rows: [string, ReactNode][] = [
    ["WHAT", <>{what} · <span className="text-amber-300">[SIMULATED]</span></>],
    ["WHY", why],
    ["IMPACT", impact],
    ["RISK", risk ?? "—"],
    ["GATE", gate ?? "—"],
    ["APPROVAL", approval ?? "not required"],
    ["REVERSIBILITY", reversibility],
  ];
  return (
    <div className="mt-12 rounded-card border border-cmd-border bg-black/20 p-12 text-[12px]">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[110px_1fr] gap-8 py-2">
          <span className="font-mono uppercase text-ink-muted">{k}</span>
          <span className="text-slate-200">{v}</span>
        </div>
      ))}
      {message && (
        <p className="mt-8 rounded-card bg-black/30 p-8 font-mono text-[11px] text-slate-300">
          preview: {message}
        </p>
      )}
    </div>
  );
}
