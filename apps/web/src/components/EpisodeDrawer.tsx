import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ActionDto, EpisodeDetail } from "../lib/api";
import { post } from "../lib/api";
import { formatINR, asPaise } from "../lib/format";
import { Chip } from "./Chips";

/** Action Preview Card — mandatory pattern (Design §15, Rules §4.4). */
export function ActionPreviewCard({
  action,
  episode,
}: {
  action: ActionDto;
  episode?: EpisodeDetail;
}) {
  const guard = (action.guardrail_snapshot ?? {}) as Record<string, unknown>;
  const ev = guard["ev"] as Record<string, number> | undefined;
  const rows: [string, React.ReactNode][] = [
    [
      "WHAT",
      <>
        {action.intervention.replace(/_/g, " ").toLowerCase()} ·{" "}
        <span className="text-amber-300">[SIMULATED]</span> channel {action.channel}
      </>,
    ],
    [
      "WHY",
      episode?.diagnoses?.length
        ? `${episode.diagnoses[0].canonical_code} · ${episode.diagnoses[0].rationale.slice(0, 80)}`
        : "root-cause policy",
    ],
    [
      "IMPACT",
      `${formatINR(asPaise(episode?.amount_paise ?? 0))} recovery · cost ${formatINR(asPaise(action.cost_paise))}${
        ev ? ` · EV ${formatINR(asPaise(ev["ev_paise"] ?? 0))}` : ""
      }`,
    ],
    ["RISK", ev ? `annoyance ${formatINR(asPaise(ev["annoyance_paise"] ?? 0))} · contact ${action.policy_version}` : "—"],
    [
      "GATE",
      `${String(guard["outcome_reason"] ?? action.status)} · mode ${action.mode} · quiet ${
        String(guard["quiet_hours_clear"])
      }`,
    ],
    [
      "APPROVAL",
      (episode?.amount_paise ?? 0) > 5_000_000 ? "required (>₹50,000)" : "not required (<₹50,000)",
    ],
    ["REVERSIBILITY", "message only — cannot move money; stop = suppression (instant)"],
  ];
  return (
    <div className="rounded-card border border-cmd-border bg-black/20 p-12 text-[12px]">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[110px_1fr] gap-8 py-2">
          <span className="font-mono uppercase text-ink-muted">{k}</span>
          <span className="text-slate-200">{v}</span>
        </div>
      ))}
    </div>
  );
}

/** Full episode drawer: diagnosis → candidates → actions → outcome (AppFlow §4). */
export function EpisodeDrawerContent({
  ep,
  onOpenEv,
  onOpenLedger,
}: {
  ep: EpisodeDetail;
  onOpenEv: (a: ActionDto) => void;
  onOpenLedger: () => void;
}) {
  const qc = useQueryClient();
  const [escMsg, setEscMsg] = useState<string | null>(null);
  const escalate = useMutation({
    mutationFn: () => post(`/api/episodes/${ep.id}/escalate`, {}),
    onSuccess: () => {
      setEscMsg("escalated → moved to the human approval queue");
      void qc.invalidateQueries({ queryKey: ["episode", ep.id] });
      void qc.invalidateQueries({ queryKey: ["episodes"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e) => setEscMsg(e instanceof Error ? e.message : "escalation failed"),
  });

  return (
    <div className="px-6 md:px-24 pb-8 md:pb-32 pt-6 md:pt-16 text-sm">
      <div className="flex items-baseline justify-between">
        <div className="text-lg font-bold tabular-nums text-on-surface">{formatINR(asPaise(ep.amount_paise))}</div>
        <Chip tone="blue">{ep.rail}</Chip>
      </div>
      <div className="mt-4 font-mono text-[11px] text-on-surface-variant">{ep.id.slice(0, 8)} · customer {ep.customer_pseudonym} · opened {new Date(ep.opened_at).toLocaleTimeString()} · closes {new Date(ep.closes_at).toLocaleTimeString()}</div>

      <section className="mt-8 md:mt-16">
        <h3 className="font-mono text-[11px] uppercase tracking-wide text-on-surface-variant">Diagnosis</h3>
        {ep.diagnoses.length === 0 && <p className="mt-4 text-on-surface-variant">in progress…</p>}
        {ep.diagnoses.map((d, i) => (
          <div key={i} className="mt-4 flex items-center gap-3 md:gap-8 rounded-xl border border-outline-variant bg-surface-container p-4 md:p-3">
            {d.method === "rule" ? <Chip title="rules match">{d.canonical_code}</Chip> : <Chip tone="lime" title={`LLM conf ${d.confidence}`}>✦ LLM · {d.confidence.toFixed(2)}</Chip>}
            <span className="text-[12px] text-on-surface">{d.rationale}</span>
          </div>
        ))}
      </section>

      <section className="mt-8 md:mt-16">
        <h3 className="font-mono text-[11px] uppercase tracking-wide text-on-surface-variant">Candidates — all persisted with EV breakdown</h3>
        <ul className="mt-4 space-y-3 md:space-y-4 font-mono text-[11px]">
          {ep.candidates.map((c) => (
            <li key={`${c.intervention}${c.ev_paise}`} className="flex justify-between rounded-xl border border-outline-variant bg-surface-container px-4 md:px-3 py-3 md:py-2">
              <span>{c.intervention}</span>
              <span>p {Number(c.p_recover).toFixed(3)} · <span className={c.ev_paise < 0 ? "text-error" : "text-secondary"}>EV {formatINR(asPaise(c.ev_paise))}</span></span>
            </li>
          ))}
          {ep.candidates.length === 0 && <li className="text-on-surface-variant">—</li>}
        </ul>
      </section>

      <section className="mt-8 md:mt-16">
        <h3 className="flex items-center justify-between font-mono text-[11px] uppercase tracking-wide text-on-surface-variant">Actions & timeline<button onClick={onOpenLedger} className="rounded-full border border-outline-variant px-3 py-1.5 text-[10px] normal-case hover:text-on-surface">🧾 ledger drawer</button></h3>
        <ol className="mt-4 space-y-4 md:space-y-8">
          {ep.actions.map((a) => (
            <li key={a.id} className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 md:p-3 warm-shadow">
              <button className="w-full text-left" onClick={() => onOpenEv(a)}>
                <div className="flex items-center justify-between"><span className="font-mono text-[12px]">{a.intervention}</span><StatusPill status={a.status} /></div>
                <div className="mt-2 flex flex-wrap gap-2 md:gap-8 text-[11px] text-on-surface-variant">
                  {a.channel && <span>{a.channel}</span>}
                  {a.mode && <span className={a.mode === "degraded" ? "text-tertiary-container" : ""}>{a.mode}</span>}
                  {a.scheduled_for && <span>for {new Date(a.scheduled_for).toLocaleTimeString()}</span>}
                </div>
                {a.message_final && <p className="mt-3 line-clamp-2 rounded-lg bg-surface-container-high p-3 text-[11px] text-on-surface-variant">{a.message_final}</p>}
              </button>
            </li>
          ))}
          {ep.actions.length === 0 && <li className="text-on-surface-variant">no actions</li>}
        </ol>
      </section>

      <section className="mt-8 md:mt-16">
        <h3 className="font-mono text-[11px] uppercase tracking-wide text-on-surface-variant">Outcomes</h3>
        {ep.outcomes.length === 0 && <p className="mt-4 text-on-surface-variant">observing…</p>}
        <ul className="mt-4 space-y-3 md:space-y-4 text-[12px]">
          {ep.outcomes.map((o, i) => (
            <li key={i} className="flex justify-between rounded-xl border border-outline-variant bg-surface-container-lowest px-4 md:px-3 py-3 md:py-2 warm-shadow">
              <span className={o.outcome === "recovered" ? "text-secondary" : "text-on-surface-variant"}>{o.outcome}{o.action_id ? " · attributed to action" : " · organic"}</span>
              {o.latency_secs != null && <span className="font-mono">{(o.latency_secs / 3600).toFixed(1)}h</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-8 md:mt-16">
        <h3 className="font-mono text-[11px] uppercase tracking-wide text-on-surface-variant">Human handoff</h3>
        <button
          onClick={() => escalate.mutate()}
          disabled={escalate.isPending}
          className="mt-4 w-full rounded-full border border-secondary px-4 py-3 text-xs font-semibold text-secondary hover:bg-secondary-container/20 disabled:opacity-50"
        >
          {escalate.isPending ? "escalating…" : "Escalate manually → human approval queue"}
        </button>
        {escMsg && <p className="mt-3 font-mono text-[11px] text-on-surface-variant">{escMsg}</p>}
      </section>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status.includes("blocked") || status.includes("halt") || status.includes("failed")
      ? "red"
      : status.includes("succeeded")
        ? "green"
        : status.includes("approval")
          ? "amber"
          : "slate";
  return <Chip tone={tone as "red" | "green" | "amber" | "slate"}>{status}</Chip>;
}
