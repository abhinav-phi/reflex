import type { CandidateDto } from "../lib/api";
import { formatINR, asPaise } from "../lib/format";
import type { ReactNode } from "react";
import { useUi } from "../store";

/** EV drawer (Design §14): formula with live numbers, four hoverable terms. */
export function EVDrawer() {
  const { evAction, openEvDrawer } = useUi();
  if (!evAction) return null;
  const t = evAction.terms;
  return (
    <Overlay onClose={() => openEvDrawer(null)} width="480px">
      <div className="border-b border-cmd-border px-24 py-16">
        <div className="text-[11px] uppercase tracking-wide text-ai-accent">✦ AI-ranked action</div>
        <div className="mt-8 font-mono text-sm text-ink-dark">
          EV {formatINR(asPaise(t.ev))} = p {t.p.toFixed(2)} × {formatINR(asPaise(t.gain))} −{" "}
          {formatINR(asPaise(t.cost))} − {formatINR(asPaise(t.annoyance))}
        </div>
      </div>
      <dl className="space-y-8 px-24 py-16 text-[13px] text-ink-muted">
        <Term label="p_recover" help="propensity this intervention recovers the payment">
          {t.p.toFixed(4)}
        </Term>
        <Term label="expected gain" help="p_recover × episode amount">
          {formatINR(asPaise(t.gain))}
        </Term>
        <Term label="channel cost" help="[SIMULATED] channel economics; RP-TM test mode is ₹0 direct">
          {formatINR(asPaise(t.cost))}
        </Term>
        <Term label="annoyance penalty" help="p_optout × LTV-band value × contact fatigue">
          {formatINR(asPaise(t.annoyance))}
        </Term>
      </dl>
      <GuardrailSnapshot guard={evAction.guard} policy={evAction.policy} />
    </Overlay>
  );
}

export function GuardrailSnapshot({ guard, policy }: { guard: Record<string, unknown>; policy: string }) {
  return (
    <div className="mx-24 mb-24 rounded-card border border-cmd-border bg-black/20 p-12 font-mono text-[11px] leading-relaxed text-slate-300">
      <div>policy {String(policy)}</div>
      <div>
        caps {String(guard["caps"] ?? "—")} · contacts today {String(guard["contacts_today"] ?? "—")}
      </div>
      <div>budget spent {String(guard["budget_spent_today_paise"] ?? 0)}p · quiet-hours clear {String(guard["quiet_hours_clear"])}</div>
      <div>suppressed {String(guard["suppressed"])} · dnd {String(guard["dnd"])}</div>
      <div className={guard["outcome_reason"] === "PASS" ? "text-emerald-400" : "text-red-400"}>
        Shield {String(guard["outcome_reason"] ?? guard["reason"] ?? "—")}
      </div>
    </div>
  );
}

export function RunnerUps({ candidates }: { candidates: CandidateDto[] }) {
  return (
    <ul className="mt-8 space-y-4 text-[12px] text-ink-muted">
      {candidates.slice(0, 5).map((c) => (
        <li key={`${c.intervention}-${c.ev_paise}`} className="flex justify-between font-mono">
          <span>{c.intervention.replace(/_/g, " ").toLowerCase()}</span>
          <span className={c.ev_paise < 0 ? "text-red-400" : "text-emerald-400"}>
            EV {formatINR(asPaise(c.ev_paise))}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Term({ label, help, children }: { label: string; help: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between" title={help}>
      <dt className="cursor-help border-b border-dotted border-slate-600">{label}</dt>
      <dd className="font-mono text-ink-dark">{children}</dd>
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
