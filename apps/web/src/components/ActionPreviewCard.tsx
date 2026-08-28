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
    ["WHAT", <>{what} · <span className="text-on-tertiary-container">[SIMULATED]</span></>],
    ["WHY", why],
    ["IMPACT", impact],
    ["RISK", risk ?? "—"],
    ["GATE", gate ?? "—"],
    ["APPROVAL", approval ?? "not required"],
    ["REVERSIBILITY", reversibility],
  ];
  return (
    <div className="mt-12 rounded-xl border border-outline-variant bg-surface-container p-4 text-[12px] warm-shadow">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[110px_1fr] gap-8 py-2">
          <span className="font-mono uppercase text-on-surface-variant">{k}</span>
          <span className="text-on-surface">{v}</span>
        </div>
      ))}
      {message && <p className="mt-4 rounded-lg bg-surface-container-high p-3 font-mono text-[11px] text-on-surface-variant">preview: {message}</p>}
    </div>
  );
}
