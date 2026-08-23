import type { ActionDto, EpisodeDetail } from "../lib/api";
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
  return (
    <div className="px-24 pb-32 pt-16 text-sm">
      <div className="flex items-baseline justify-between">
        <div className="text-lg font-bold tabular-nums text-ink-dark">
          {formatINR(asPaise(ep.amount_paise))}
        </div>
        <Chip tone="blue">{ep.rail}</Chip>
      </div>
      <div className="mt-4 font-mono text-[11px] text-slate-500">
        {ep.id.slice(0, 8)} · customer {ep.customer_pseudonym} · opened{" "}
        {new Date(ep.opened_at).toLocaleTimeString()} · closes{" "}
        {new Date(ep.closes_at).toLocaleTimeString()}
      </div>

      <section className="mt-16">
        <h3 className="text-[11px] uppercase tracking-wide text-ink-muted">Diagnosis</h3>
        {ep.diagnoses.length === 0 && <p className="mt-8 text-ink-muted">in progress…</p>}
        {ep.diagnoses.map((d, i) => (
          <div key={i} className="mt-8 flex items-center gap-8 rounded-card border border-cmd-border p-12">
            {d.method === "rule" ? <Chip title="rules match">{d.canonical_code}</Chip> : <Chip tone="violet" title={`LLM conf ${d.confidence}`}>✦ LLM · {d.confidence.toFixed(2)}</Chip>}
            <span className="text-[12px] text-slate-300">{d.rationale}</span>
          </div>
        ))}
      </section>

      <section className="mt-16">
        <h3 className="text-[11px] uppercase tracking-wide text-ink-muted">
          Candidates — all persisted with EV breakdown
        </h3>
        <ul className="mt-8 space-y-4 font-mono text-[11px]">
          {ep.candidates.map((c) => (
            <li key={`${c.intervention}${c.ev_paise}`} className="flex justify-between rounded-card border border-cmd-border px-12 py-8">
              <span>{c.intervention}</span>
              <span>
                p {Number(c.p_recover).toFixed(3)} ·{" "}
                <span className={c.ev_paise < 0 ? "text-red-400" : "text-emerald-400"}>
                  EV {formatINR(asPaise(c.ev_paise))}
                </span>
              </span>
            </li>
          ))}
          {ep.candidates.length === 0 && <li className="text-ink-muted">—</li>}
        </ul>
      </section>

      <section className="mt-16">
        <h3 className="flex items-center justify-between text-[11px] uppercase tracking-wide text-ink-muted">
          Actions & timeline
          <button onClick={onOpenLedger} className="rounded-btn border border-cmd-border px-8 py-2 text-[10px] normal-case hover:text-ink-dark">
            🧾 ledger drawer
          </button>
        </h3>
        <ol className="mt-8 space-y-8">
          {ep.actions.map((a) => (
            <li key={a.id} className="rounded-card border border-cmd-border p-12">
              <button className="w-full text-left" onClick={() => onOpenEv(a)}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[12px]">{a.intervention}</span>
                  <StatusPill status={a.status} />
                </div>
                <div className="mt-4 flex flex-wrap gap-8 text-[11px] text-slate-400">
                  {a.channel && <span>{a.channel}</span>}
                  {a.mode && <span className={a.mode === "degraded" ? "text-amber-300" : ""}>{a.mode}</span>}
                  {a.scheduled_for && <span>for {new Date(a.scheduled_for).toLocaleTimeString()}</span>}
                </div>
                {a.message_final && (
                  <p className="mt-8 line-clamp-2 rounded-card bg-black/30 p-8 text-[11px] text-slate-300">
                    {a.message_final}
                  </p>
                )}
              </button>
            </li>
          ))}
          {ep.actions.length === 0 && <li className="text-ink-muted">no actions</li>}
        </ol>
      </section>

      <section className="mt-16">
        <h3 className="text-[11px] uppercase tracking-wide text-ink-muted">Outcomes</h3>
        {ep.outcomes.length === 0 && <p className="mt-8 text-ink-muted">observing…</p>}
        <ul className="mt-8 space-y-4 text-[12px]">
          {ep.outcomes.map((o, i) => (
            <li key={i} className="flex justify-between rounded-card border border-cmd-border px-12 py-8">
              <span className={o.outcome === "recovered" ? "text-emerald-400" : "text-slate-300"}>
                {o.outcome}{o.action_id ? " · attributed to action" : " · organic"}
              </span>
              {o.latency_secs != null && <span className="font-mono">{(o.latency_secs / 3600).toFixed(1)}h</span>}
            </li>
          ))}
        </ul>
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
