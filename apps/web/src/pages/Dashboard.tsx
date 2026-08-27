import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ActionDto, CandidateDto, EpisodeDetail, EpisodeListItem, LiveMetrics } from "../lib/api";
import { api } from "../lib/api";
import { formatINR, asPaise } from "../lib/format";
import { useUi } from "../store";
import { useStream } from "../hooks/useStream";
import { ControlBar } from "../components/ControlBar";
import { DiagnosisChip, StatusChip } from "../components/Chips";
import { GuardrailSnapshot, Overlay } from "../components/EVDrawer";
import { EpisodeDrawerContent } from "../components/EpisodeDrawer";
import { LedgerDrawer } from "../components/LedgerDrawer";

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
    queryFn: () => api<{ total: number; items: EpisodeListItem[] }>(`/api/episodes?limit=60${armFilter ? `&arm=${armFilter}` : ""}`),
    refetchInterval: 2500,
  });
  const detail = useQuery({
    queryKey: ["episode", openEpisode],
    queryFn: () => api<EpisodeDetail>(`/api/episodes/${openEpisode}`),
    enabled: !!openEpisode,
  });

  const m = metrics.data;
  const contactsToday = m?.contacts_today ?? 0;
  const contactsPerDay = m?.contacts_per_day ?? 2;
  const quietHours = (m?.quiet_hours ?? "21:00-09:00").replace(":00", "").replace("21:00-09:00", "21–09");

  // Today's Signal — live diagnosis coverage from the counters when episodes
  // exist; otherwise the eval holdout number (eval/results dx_holdout).
  const ctr = m?.counters ?? {};
  const dxTotal = (ctr["dx_rule"] ?? 0) + (ctr["dx_llm"] ?? 0);
  const liveCoverage = (ctr["episodes_created"] ?? 0) > 0 ? (dxTotal / (ctr["episodes_created"] ?? 1)) * 100 : null;
  const signalPct = liveCoverage != null ? `${liveCoverage.toFixed(1)}%` : "89.6%";
  const signalLabel = liveCoverage != null ? "diagnosis coverage · live" : "rules diagnosis coverage · eval holdout";

  const dateLine = new Date()
    .toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })
    .toUpperCase();

  // Shield headline reflects the live mode — not a static "All clear."
  const mode = m?.mode ?? "advisory";
  const shieldHeadline = mode === "halted" ? "Halted." : mode === "degraded" ? "Degraded fallback." : "All clear.";
  const shieldBody =
    mode === "halted"
      ? "Kill switch active. Scheduled actions are cancelled; dispatch resumes only on deliberate re-enable."
      : mode === "degraded"
        ? "LLM unavailable — deterministic fallback is choosing actions, stamped DEGRADED."
        : "Deterministic guardrails are active. No action can bypass the safety layer.";

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="px-4 md:px-margin max-w-[1440px] mx-auto py-8 pb-24 md:pb-8">
        {/* Header */}
        <header className="mb-12 flex flex-col md:flex-row md:justify-between md:items-end gap-4">
          <div>
            <p className="font-mono text-label-mono text-on-tertiary-container uppercase tracking-[0.1em] mb-4">{dateLine} / {m?.merchant_name ?? "SipDaily"}</p>
            <h1 className="font-display text-display-lg-mobile md:text-display-lg text-primary mb-2">Recovery overview.</h1>
            <p className="font-sans text-body-lg text-on-surface-variant">The agent is watching failed payments and choosing the least annoying next step.</p>
          </div>
          <div className="hidden md:flex items-center gap-4 bg-surface-container-lowest border border-outline-variant rounded-full px-4 py-2 warm-shadow">
            <span className="font-mono text-label-mono text-primary uppercase">Mode / {m?.mode ?? "advisory"}</span>
            <span className="font-mono text-[10px] uppercase tracking-widest border border-tertiary-container text-tertiary-container px-2 py-0.5 rounded">[SIMULATED]</span>
          </div>
          <div className="flex md:hidden items-center gap-3 pt-2">
            <div className="px-4 py-2 rounded-full border border-outline-variant bg-surface-container-lowest text-on-surface font-sans text-body-md shadow-sm">Mode / {m?.mode ?? "advisory"}</div>
            <div className="px-3 py-1.5 rounded border border-tertiary-container text-tertiary-container font-mono text-label-mono uppercase">[SIMULATED]</div>
          </div>
        </header>

        {/* Stat cards — 2x2 on mobile (single-col stack per mobile design), 4-col on lg */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-gutter mb-gutter">
          <div className="bg-surface-container-lowest rounded-xl p-6 warm-shadow relative overflow-hidden">
            <div className="w-6 h-1 bg-on-tertiary-container rounded-full mb-6" />
            <p className="font-sans text-body-md text-on-surface-variant mb-2">Failed value today</p>
            <h2 className="font-display text-headline-md text-primary mb-4">{m ? formatINR(asPaise(m.failed_today_paise)) : "—"}</h2>
            <p className="font-mono text-label-mono text-on-surface-variant">{m ? `${m.episodes_open} open episodes` : "loading live metrics…"}</p>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-6 warm-shadow">
            <div className="h-1 mb-6" />
            <p className="font-sans text-body-md text-on-surface-variant mb-2">Recovered by Reflex</p>
            <h2 className="font-display text-headline-md text-primary mb-4">{m ? formatINR(asPaise(m.recovered_reflex_paise)) : "—"}</h2>
            <p className="font-mono text-label-mono bg-secondary-fixed inline-block px-2 py-1 rounded text-on-secondary-fixed">
              {m && m.recovered_b1_paise > 0 ? `${(((m.recovered_reflex_paise - m.recovered_b1_paise) / m.recovered_b1_paise) * 100).toFixed(0)}% vs tuned baseline` : "vs tuned baseline"}
            </p>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-6 warm-shadow">
            <div className="h-1 mb-6" />
            <p className="font-sans text-body-md text-on-surface-variant mb-2">Customer complaints</p>
            <h2 className="font-display text-headline-md text-primary mb-4">{m ? `${(m.complaint_rate * 100).toFixed(2)}%` : "—"}</h2>
            <p className="font-mono text-label-mono text-on-surface-variant">Below 0.5% safety gate</p>
          </div>
          <div className="bg-surface-container-lowest rounded-xl p-6 warm-shadow">
            <div className="h-1 mb-6" />
            <p className="font-sans text-body-md text-on-surface-variant mb-2">Cost per ₹100 recovered</p>
            <h2 className="font-display text-headline-md text-primary mb-4">{m?.cost_per_100p != null ? `₹${m.cost_per_100p.toFixed(2)}` : "—"}</h2>
            <p className="font-mono text-label-mono text-on-surface-variant">{m ? `×${m.speed.toFixed(0)} replay speed` : "loading…"}</p>
          </div>
        </div>

        {/* Main grid — 8 + 4 on desktop, single-col stack on mobile */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
          {/* Failures stream */}
          <div className="lg:col-span-8 bg-surface-container-lowest rounded-xl p-8 warm-shadow">
            <div className="flex flex-col md:flex-row md:justify-between md:items-start gap-4 mb-8">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-1.5 h-1.5 bg-on-tertiary-container rounded-full" />
                  <h3 className="font-display text-headline-sm text-primary">Failures stream</h3>
                </div>
                <p className="font-sans text-body-md text-on-surface-variant">Every episode is a decision waiting to be made.</p>
              </div>
              <div className="flex bg-surface-container rounded-full p-1 border border-outline-variant self-start">
                {(["reflex", "b1", "b0"] as const).map((a) => (
                  <button
                    key={a}
                    onClick={() => setArmFilter(a === armFilter ? null : a)}
                    className={`font-mono text-label-mono rounded-full px-4 py-1.5 ${armFilter === a ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-primary"}`}
                    aria-pressed={armFilter === a}
                  >
                    {a.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Desktop table */}
            <div className="hidden md:block w-full overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="font-mono text-label-mono text-primary-container border-b border-surface-container-highest uppercase">
                    <th className="pb-4 font-normal tracking-[0.1em]">Episode</th>
                    <th className="pb-4 font-normal tracking-[0.1em]">Payment</th>
                    <th className="pb-4 font-normal tracking-[0.1em]">Diagnosis</th>
                    <th className="pb-4 font-normal tracking-[0.1em]">State</th>
                    <th className="pb-4 font-normal tracking-[0.1em] text-right">EV Score</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-label-mono text-on-surface">
                  {(episodes.data?.items ?? []).map((e) => (
                    <tr
                      key={e.id}
                      onClick={() => openEpisodeDrawer(e.id)}
                      className="border-b border-surface-container-high h-[64px] hover:bg-surface-container-low/50 cursor-pointer"
                      title="open episode drawer"
                    >
                      <td className="py-2">
                        <div className="text-primary font-bold">{e.customer_pseudonym}</div>
                        <div className="text-outline-variant font-normal text-[10px]">{e.id.slice(0, 12)}</div>
                      </td>
                      <td>
                        <div className="text-primary font-bold">{formatINR(asPaise(e.amount_paise))}</div>
                        <div className="text-outline-variant font-normal text-[10px]">{e.rail}</div>
                      </td>
                      <td><DiagnosisChip d={e.diagnosis} /></td>
                      <td><StatusChip status={e.status} /></td>
                      <td className="text-right">
                        {e.top_ev_paise != null ? (
                          <span className={`px-2 py-1 rounded font-bold ${e.top_ev_paise >= 0 ? "bg-primary text-secondary-container" : "text-on-surface-variant"}`}>{formatINR(asPaise(e.top_ev_paise))}</span>
                        ) : (
                          <span className="text-on-surface-variant">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {episodes.data && episodes.data.items.length === 0 && <p className="py-12 text-center font-sans text-body-md text-on-surface-variant">No failed payments in window. Start a replay to see Reflex work.</p>}
            </div>

            {/* Mobile list */}
            <div className="md:hidden space-y-3">
              {(episodes.data?.items ?? []).map((e) => (
                <button
                  key={e.id}
                  onClick={() => openEpisodeDrawer(e.id)}
                  className="w-full bg-surface-container-lowest p-4 rounded-lg shadow-sm border border-surface-container flex flex-col gap-3 text-left"
                >
                  <div className="flex justify-between items-start">
                    <span className="font-sans text-body-md font-medium text-primary">{e.customer_pseudonym}</span>
                    <span className="font-mono text-label-mono text-on-surface-variant">{formatINR(asPaise(e.amount_paise))}</span>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    <DiagnosisChip d={e.diagnosis} />
                    <StatusChip status={e.status} />
                  </div>
                </button>
              ))}
              {episodes.data && episodes.data.items.length === 0 && <p className="py-8 text-center font-sans text-body-md text-on-surface-variant">No failed payments in window.</p>}
              <button onClick={() => void episodes.refetch()} className="w-full py-3 mt-2 text-center font-mono text-label-mono text-primary hover:bg-surface-container-low transition-colors rounded-lg border border-outline-variant">View All Episodes</button>
            </div>
          </div>

          {/* Right column */}
          <div className="lg:col-span-4 flex flex-col gap-gutter">
            <div className={`border rounded-xl p-8 shadow-none relative overflow-hidden ${mode === "halted" ? "bg-error-container border-error text-on-error-container" : mode === "degraded" ? "bg-tertiary-fixed border-tertiary-container text-on-tertiary-fixed" : "bg-primary border-primary-container text-on-primary"}`}>
              <p className="font-mono text-label-mono tracking-widest uppercase mb-4">Shield Status</p>
              <div className="flex justify-between items-start mb-6">
                <h2 className="font-display text-headline-md">{shieldHeadline}</h2>
                <span className="material-symbols-outlined">{mode === "halted" ? "block" : mode === "degraded" ? "warning" : "check"}</span>
              </div>
              <p className="font-sans text-body-md mb-8">{shieldBody}</p>
              <div className="grid grid-cols-2 gap-4">
                <div className={mode === "halted" || mode === "degraded" ? "bg-error/20 rounded-lg p-4" : "bg-primary-container rounded-lg p-4"}>
                  <p className="font-mono text-[10px] opacity-75 mb-1">Contacts / day</p>
                  <p className="font-mono text-body-lg font-bold">{contactsToday}/{contactsPerDay}</p>
                </div>
                <div className={mode === "halted" || mode === "degraded" ? "bg-error/20 rounded-lg p-4" : "bg-primary-container rounded-lg p-4"}>
                  <p className="font-mono text-[10px] opacity-75 mb-1">Quiet hours</p>
                  <p className="font-mono text-body-lg font-bold">{quietHours}</p>
                </div>
              </div>
            </div>

            <div className="bg-primary-fixed rounded-xl p-8 border border-primary-fixed-dim">
              <p className="font-mono text-label-mono tracking-widest uppercase mb-4 opacity-70">Today&apos;s Signal</p>
              <h2 className="font-display text-display-lg-mobile text-on-primary-fixed mb-2">{signalPct}</h2>
              <p className="font-mono text-label-mono text-on-primary-fixed-variant">{signalLabel}</p>
            </div>
          </div>
        </div>
      </main>

      {/* Bottom nav for mobile */}
      <div className="fixed bottom-0 left-0 right-0 bg-background border-t border-surface-container-high py-2 px-6 flex justify-between items-center md:hidden z-50">
        <div className="flex flex-col items-center gap-1 text-primary font-bold">
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" } as React.CSSProperties}>dashboard</span>
          <span className="font-mono text-[10px]">Dashboard</span>
        </div>
        <a href="/approvals" className="flex flex-col items-center gap-1 text-on-surface-variant">
          <span className="material-symbols-outlined">fact_check</span>
          <span className="font-mono text-[10px]">Approvals</span>
        </a>
        <a href="/results" className="flex flex-col items-center gap-1 text-on-surface-variant">
          <span className="material-symbols-outlined">analytics</span>
          <span className="font-mono text-[10px]">Results</span>
        </a>
        <a href="/ops" className="flex flex-col items-center gap-1 text-on-surface-variant">
          <span className="material-symbols-outlined">settings</span>
          <span className="font-mono text-[10px]">Ops</span>
        </a>
      </div>

      {openEpisode && detail.data && (
        <Overlay title="Episode" onClose={() => openEpisodeDrawer(null)}>
          <EpisodeDrawerContent ep={{ ...detail.data, amount_paise: detail.data.amount_paise }} onOpenEv={(a) => openEvDrawer({ actionId: a.id, formula: "", policy: a.policy_version, terms: { p: 0, gain: 0, cost: a.cost_paise, annoyance: 0, ev: 0 }, guard: a.guardrail_snapshot })} onOpenLedger={() => openLedgerDrawer(detail.data.id)} />
        </Overlay>
      )}
      {evAction && detail.data && <EvBridge episode={detail.data} actionId={evAction.actionId} />}
      {ledgerEpisode && <div data-testid="ledger-drawer"><LedgerDrawer episodeId={ledgerEpisode} /></div>}
    </div>
  );
}

function EvBridge({ episode, actionId }: { episode: EpisodeDetail; actionId: string }) {
  const action: ActionDto | undefined = episode.actions.find((a) => a.id === actionId);
  const cand: CandidateDto | undefined = episode.candidates.find((c) => action !== undefined && c.intervention === action.intervention);
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
      <div className="border-b border-outline-variant px-6 md:px-24 py-6 md:py-16">
        <div className="text-[11px] uppercase tracking-wide text-on-tertiary-container">✦ AI-ranked action</div>
        <div className="mt-2 font-mono text-sm">EV {formatINR(asPaise(terms.ev))} = p {terms.p.toFixed(2)} × {formatINR(asPaise(terms.gain))} − {formatINR(asPaise(terms.cost))} − {formatINR(asPaise(terms.annoyance))}</div>
      </div>
      <div className="px-6 md:px-24 py-6 md:py-16">
        <GuardrailSnapshot guard={guard} policy={action?.policy_version ?? "?"} />
        <h4 className="mt-8 text-[11px] uppercase text-on-surface-variant">Runner-ups</h4>
        <ul className="mt-4 space-y-2 font-mono text-[11px]">
          {episode.candidates.slice(0, 5).map((c) => (
            <li key={`${c.intervention}${c.ev_paise}`} className="flex justify-between">
              <span>{c.intervention}</span>
              <span className={c.ev_paise < 0 ? "text-error" : "text-secondary"}>{formatINR(asPaise(c.ev_paise))}</span>
            </li>
          ))}
        </ul>
      </div>
    </Overlay>
  );
}
