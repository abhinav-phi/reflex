import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ActionDto, CandidateDto, EpisodeDetail, EpisodeListItem, LiveMetrics } from "../lib/api";
import { api } from "../lib/api";
import { formatINR, asPaise } from "../lib/format";
import { useUi } from "../store";
import { useStream } from "../hooks/useStream";
import { ControlBar } from "../components/ControlBar";
import { DiagnosisChip, SimulatedBadge, StatusChip } from "../components/Chips";
import { GuardrailSnapshot, Overlay } from "../components/EVDrawer";
import { EpisodeDrawerContent } from "../components/EpisodeDrawer";
import { LedgerDrawer } from "../components/LedgerDrawer";

/** Command center (AppFlow §4): counters row + live failures stream + drawers. */
export default function Dashboard() {
  useStream();
  const { openEpisode, openEpisodeDrawer, evAction, openEvDrawer, ledgerEpisode, openLedgerDrawer } = useUi();
  const [armFilter, setArmFilter] = useState<string | null>("reflex");

  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<LiveMetrics>("/api/metrics/live"),
    refetchInterval: 2000,
  });
  const episodes = useQuery({
    queryKey: ["episodes", armFilter],
    queryFn: () =>
      api<{ total: number; items: EpisodeListItem[] }>(
        `/api/episodes?limit=60${armFilter ? `&arm=${armFilter}` : ""}`,
      ),
    refetchInterval: 2500,
  });
  const detail = useQuery({
    queryKey: ["episode", openEpisode],
    queryFn: () => api<EpisodeDetail>(`/api/episodes/${openEpisode}`),
    enabled: !!openEpisode,
  });

  const m = metrics.data;

  return (
    <div className="min-h-screen bg-cmd-bg text-ink-dark">
      <ControlBar />
      <main className="mx-auto max-w-[1400px] px-24 pb-48">
        {/* Counters row */}
        <section className="mt-24 grid grid-cols-2 gap-24 lg:grid-cols-4" aria-live="polite">
          <CounterCard
            label="Failed value"
            tone="red"
            value={m ? formatINR(asPaise(m.failed_today_paise)) : "—"}
            delta={m ? `${m.episodes_open} open · ${m.episodes_terminal} terminal` : ""}
          />
          <CounterCard
            label="Recovered — Reflex"
            tone="green"
            value={m ? formatINR(asPaise(m.recovered_reflex_paise)) : "—"}
            delta={m ? `cost/₹100 ${m.cost_per_100p != null ? `₹${m.cost_per_100p.toFixed(2)}` : "—"}` : ""}
          />
          <CounterCard
            label="Naive baseline would get"
            tone="blue"
            value={m ? formatINR(asPaise(m.recovered_b1_paise)) : "—"}
            delta="same batch · tuned naive B1"
          />
          <CounterCard
            label="Complaint rate"
            tone="amber"
            value={m ? `${(m.complaint_rate * 100).toFixed(2)}%` : "—"}
            delta={`×${m?.speed.toFixed(0) ?? 1} replay speed`}
          />
        </section>

        {/* Stream */}
        <section className="mt-32">
          <header className="mb-12 flex items-center justify-between">
            <h2 className="text-xl font-semibold">Failures stream</h2>
            <div className="flex items-center gap-8">
              <SimulatedBadge />
              {["reflex", "b1", "b0"].map((a) => (
                <button
                  key={a}
                  onClick={() => setArmFilter(a === armFilter ? null : a)}
                  className={`rounded-chip border px-12 py-4 text-xs ${
                    armFilter === a ? "border-primary text-indigo-200" : "border-cmd-border text-ink-muted"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </header>

          {episodes.data && episodes.data.items.length === 0 && (
            <EmptyState />
          )}

          <ul className="divide-y divide-cmd-border overflow-hidden rounded-card border border-cmd-border">
            {(episodes.data?.items ?? []).map((e) => (
              <li key={e.id}>
                <button
                  className="flex w-full items-center gap-16 border-l-2 border-transparent px-16 py-12 text-left hover:border-primary hover:bg-white/[0.03]"
                  onClick={() => openEpisodeDrawer(e.id)}
                >
                  <span
                    className={`h-32 w-3 rounded-full ${
                      e.status === "recovered"
                        ? "bg-emerald-500"
                        : e.status.includes("stop") || e.status.includes("halt")
                          ? "bg-red-500"
                          : e.status === "expired"
                            ? "bg-slate-600"
                            : "bg-sky-500"
                    }`}
                  />
                  <span className="w-100 tabular-nums font-semibold">{formatINR(asPaise(e.amount_paise))}</span>
                  <span className="w-80 text-xs uppercase text-slate-400">{e.rail}</span>
                  <DiagnosisChip d={e.diagnosis} />
                  <StatusChip status={e.status} />
                  <span className="ml-auto text-[11px] text-slate-500">{age(e.opened_at)} old</span>
                  {e.top_ev_paise != null && (
                    <span className={`tabular-nums ${e.top_ev_paise >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      EV {formatINR(asPaise(e.top_ev_paise))}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </section>
      </main>

      {openEpisode && detail.data && (
        <Overlay title="Episode" onClose={() => openEpisodeDrawer(null)}>
          <EpisodeDrawerContent
            ep={{ ...detail.data, amount_paise: detail.data.amount_paise }}
            onOpenEv={(a) => {
              openEvDrawer({
                actionId: a.id,
                formula: "",
                policy: a.policy_version,
                terms: { p: 0, gain: 0, cost: a.cost_paise, annoyance: 0, ev: 0 },
                guard: a.guardrail_snapshot,
              });
            }}
            onOpenLedger={() => openLedgerDrawer(detail.data.id)}
          />
        </Overlay>
      )}

      {evAction && detail.data && (
        <EvBridge episode={detail.data} actionId={evAction.actionId} />
      )}
      {ledgerEpisode && (
        <div data-testid="ledger-drawer">
          <LedgerDrawer episodeId={ledgerEpisode} />
        </div>
      )}
    </div>
  );
}

/** Pulls the selected action's candidate EV terms from the episode detail. */
function EvBridge({ episode, actionId }: { episode: EpisodeDetail; actionId: string }) {
  const action: ActionDto | undefined = episode.actions.find((a) => a.id === actionId);
  const cand: CandidateDto | undefined = episode.candidates.find(
    (c) => action !== undefined && c.intervention === action.intervention,
  );
  const guard = (action?.guardrail_snapshot ?? {}) as Record<string, unknown>;
  const ev = (guard["ev"] ?? {}) as Record<string, number>;
  const terms = {
    p: Number(cand?.p_recover ?? ev["p_recover"] ?? 0),
    gain: Number(cand?.expected_gain_paise ?? ev["expected_gain_paise"] ?? 0),
    cost: Number(cand?.cost_paise ?? action?.cost_paise ?? 0),
    annoyance: Number(cand?.annoyance_paise ?? ev["annoyance_paise"] ?? 0),
    ev: Number(cand?.ev_paise ?? ev["ev_paise"] ?? 0),
  };
  return (
    <Overlay title="EV drawer — AI-ranked rationale" onClose={() => useUi.getState().openEvDrawer(null)} width="480px">
      <div className="border-b border-cmd-border px-24 py-16">
        <div className="text-[11px] uppercase tracking-wide text-ai-accent">✦ AI-ranked action</div>
        <div className="mt-8 font-mono text-sm">
          EV {formatINR(asPaise(terms.ev))} = p {terms.p.toFixed(2)} ×{" "}
          {formatINR(asPaise(terms.gain))} − {formatINR(asPaise(terms.cost))} −{" "}
          {formatINR(asPaise(terms.annoyance))}
        </div>
      </div>
      <div className="px-24 py-16">
        <GuardrailSnapshot guard={guard} policy={action?.policy_version ?? "?"} />
        <h4 className="mt-16 text-[11px] uppercase text-ink-muted">Runner-ups</h4>
        <ul className="mt-8 space-y-4 font-mono text-[11px]">
          {episode.candidates.slice(0, 5).map((c) => (
            <li key={`${c.intervention}${c.ev_paise}`} className="flex justify-between">
              <span>{c.intervention}</span>
              <span className={c.ev_paise < 0 ? "text-red-400" : "text-emerald-400"}>
                {formatINR(asPaise(c.ev_paise))}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Overlay>
  );
}

function CounterCard({
  label,
  value,
  delta,
  tone,
}: {
  label: string;
  value: string;
  delta?: string;
  tone: "red" | "green" | "blue" | "amber";
}) {
  const tones = {
    red: "text-red-400",
    green: "text-emerald-400",
    blue: "text-sky-300",
    amber: "text-amber-300",
  };
  return (
    <div className="rounded-card border border-cmd-border bg-cmd-surface p-16 transition-colors hover:border-primary">
      <div className="text-[11px] uppercase tracking-wide text-ink-muted">{label}</div>
      <div className={`mt-4 text-4xl font-bold tabular-nums ${tones[tone]}`}>{value}</div>
      {delta && <div className="mt-4 text-[11px] text-slate-500">{delta}</div>}
    </div>
  );
}

function age(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

export function EmptyState({ onStart }: { onStart?: () => void }) {
  return (
    <div className="rounded-card border border-dashed border-cmd-border p-48 text-center">
      <p className="text-sm text-ink-muted">
        No failed payments in window. Start a replay to see Reflex work.
      </p>
      {onStart && (
        <button onClick={onStart} className="mt-16 rounded-btn bg-primary px-16 py-8 text-xs font-medium">
          Start demo slice
        </button>
      )}
    </div>
  );
}
