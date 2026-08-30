import type { ReactNode } from "react";

/** EV drawer helpers (Design §14): Overlay sheet + guardrail proof snapshot.
 *  The old full EVDrawer/Term/RunnerUps components were never imported —
 *  Dashboard renders its own EvBridge using these two live exports. */

export function GuardrailSnapshot({ guard, policy }: { guard: Record<string, unknown>; policy: string }) {
  return (
    <div className="mx-6 mb-6 rounded-card border border-outline-variant bg-surface-container p-12 font-mono text-[11px] leading-relaxed text-on-surface">
      <div>policy {String(policy)}</div>
      <div>
        caps {String(guard["caps"] ?? "—")} · contacts today {String(guard["contacts_today"] ?? "—")}
      </div>
      <div>budget spent {String(guard["budget_spent_today_paise"] ?? 0)}p · quiet-hours clear {String(guard["quiet_hours_clear"])}</div>
      <div>suppressed {String(guard["suppressed"])} · dnd {String(guard["dnd"])}</div>
      <div className={guard["outcome_reason"] === "PASS" ? "text-success" : "text-error"}>
        Shield {String(guard["outcome_reason"] ?? guard["reason"] ?? "—")}
      </div>
    </div>
  );
}

export function Overlay({ onClose, title, width = "560px", children }: { onClose: () => void; title?: string; width?: string; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="h-full w-full overflow-y-auto rounded-l-[16px] border-l border-outline-variant bg-surface-container-lowest warm-shadow-lg"
        style={{ width: `min(100vw, ${width})` }}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-outline-variant bg-surface-container-lowest px-4 py-4 sm:px-24 sm:py-6">
            <h2 className="text-base font-semibold text-on-surface">{title}</h2>
            <button onClick={onClose} className="rounded-full border border-outline-variant px-3 py-1.5 text-xs text-on-surface-variant hover:text-on-surface">close ✕</button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
