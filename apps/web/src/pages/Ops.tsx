import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, post, downloadFile, clearToken, getRole, roleRankOf } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { BottomNav } from "../components/BottomNav";
import { useStream } from "../hooks/useStream";
import { useTitle } from "../hooks/useTitle";
import { useUi } from "../store";
import { Chip, SimulatedBadge } from "../components/Chips";

/** Ops (AppFlow §12): replay demo, modes, injections, guardrails, live event console. */
export default function Ops() {
  useTitle("Ops — Reflex");
  useStream();
  const qc = useQueryClient();
  const canOperate = (roleRankOf(getRole()) ?? -1) >= 1; // operator or admin
  const events = useUi((s) => s.events);
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<Record<string, unknown>>("/api/metrics/live"),
    refetchInterval: 60000,
  });
  const evalStatus = useQuery({
    queryKey: ["evalstatus"],
    queryFn: () => api<{ running: boolean; preregistered_tag?: string; tag_present: boolean }>("/api/eval/status"),
  });
  const guardrails = useQuery({
    queryKey: ["guardrails"],
    queryFn: () => api<{ configured: boolean; merchant: { cfg: Record<string, unknown>; mode: string } | null }>("/api/onboarding/state"),
    retry: false,
    enabled: (roleRankOf(getRole()) ?? -1) >= 3, // admin only — a lower role would just 403
  });
  const [msg, setMsg] = useState<string | null>(null);
  const [replay, setReplay] = useState<{ n: number; speed: number }>({ n: 214, speed: 100 });
  const [exportErr, setExportErr] = useState<string | null>(null);

  async function downloadCsv(): Promise<void> {
    try {
      await downloadFile(`/api/episodes/export?format=csv`, "reflex_episodes_simulated.csv");
      setExportErr(null);
    } catch (e) {
      setExportErr(`Episodes CSV failed: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }
  async function downloadLedgerCsv(): Promise<void> {
    try {
      await downloadFile(`/api/ledger/export?format=csv`, "reflex_action_ledger_simulated.csv");
      setExportErr(null);
    } catch (e) {
      setExportErr(`Ledger CSV failed: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }
  async function downloadLedgerJson(): Promise<void> {
    try {
      await downloadFile(`/api/ledger/export?format=json`, "reflex_action_ledger_simulated.json");
      setExportErr(null);
    } catch (e) {
      setExportErr(`Ledger JSON failed: ${e instanceof Error ? e.message : "unknown"}`);
    }
  }

  const mode = useMutation({
    mutationFn: (m: string) => post("/api/control/mode", { mode: m }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["metrics"] }),
    onError: (e) => setMsg(`mode change failed: ${e instanceof Error ? e.message : "unknown"}`),
  });
  const inject = useMutation({
    mutationFn: (scenario: string) => post<Record<string, unknown>>(`/api/control/inject/${scenario}`, {}),
    onSuccess: (d, scenario) => {
      setMsg(`${scenario} → ${JSON.stringify(d)}`);
      void qc.invalidateQueries();
    },
    onError: (e) => setMsg(`injection failed: ${e instanceof Error ? e.message : "unknown"}`),
  });
  const startReplay = useMutation({
    mutationFn: (v: { n: number; speed: number }) =>
      post<{ batch_ids: string[] }>("/api/replay/start", { n: v.n, speed: v.speed, arm: "reflex", demo: true }),
    onSuccess: (d) => {
      setMsg(`demo started — batches ${d.batch_ids.join(", ")}`);
      void qc.invalidateQueries();
    },
    onError: (e) => setMsg(`replay failed: ${e instanceof Error ? e.message : "unknown"}`),
  });
  const saveGuardrails = useMutation({
    mutationFn: (body: Record<string, unknown>) => post("/api/onboarding/guardrails", body),
    onSuccess: () => {
      setMsg("guardrails saved (ledgered)");
      void qc.invalidateQueries({ queryKey: ["guardrails"] });
    },
    onError: (e) => setMsg(`save failed: ${e instanceof Error ? e.message : "unknown"}`),
  });

  const counters = (metrics.data?.["counters"] ?? {}) as Record<string, number>;

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[1200px] px-4 md:px-24 pb-48">
        <h1 className="mt-8 md:mt-32 font-display text-headline-md text-primary">Ops — controls & failure injections</h1>

        {msg && (
          <p className="mt-4 rounded-lg border border-outline-variant bg-surface-container px-4 py-2 font-mono text-[11px] text-on-surface-variant">
            {msg} <button onClick={() => setMsg(null)} className="ml-2 text-primary">✕</button>
          </p>
        )}

        <div className="mt-8 md:mt-24 grid gap-6 md:gap-4 md:grid-cols-2">
          <Card title="Demo replay — start the live simulation" sub="streams real episodes through the full pipeline; dashboard counters climb [SIMULATED]">
            {canOperate ? (
              <div className="flex flex-wrap items-center gap-2">
                <label className="font-mono text-[11px] text-on-surface-variant">episodes</label>
                <input
                  type="number"
                  min={1}
                  max={214}
                  value={replay.n}
                  onChange={(e) => setReplay({ ...replay, n: Math.max(1, Math.min(214, Number(e.target.value) || 1)) })}
                  className="w-20 rounded-lg border border-outline-variant bg-surface-container px-2 py-1 font-mono text-xs"
                />
                <label className="ml-2 font-mono text-[11px] text-on-surface-variant">×speed</label>
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={replay.speed}
                  onChange={(e) => setReplay({ ...replay, speed: Math.max(1, Number(e.target.value) || 100) })}
                  className="w-20 rounded-lg border border-outline-variant bg-surface-container px-2 py-1 font-mono text-xs"
                />
                <button
                  onClick={() => startReplay.mutate(replay)}
                  disabled={startReplay.isPending}
                  className="rounded-full bg-primary-container px-6 py-2 text-xs font-mono font-semibold text-on-primary hover:bg-primary disabled:opacity-50"
                >
                  {startReplay.isPending ? "starting…" : "▶ Start demo"}
                </button>
              </div>
            ) : (
              <p className="font-mono text-[11px] text-on-surface-variant">operator or admin role required — replays dispatch through the live pipeline.</p>
            )}
            <p className="mt-2 font-mono text-[10px] text-outline">POST /api/replay/start · 409 if a batch is already running</p>
          </Card>

          <Card title="Mode control">
            {canOperate ? (
              <div className="flex flex-wrap gap-2 md:gap-2">
                {["advisory", "autonomous", "degraded", "halted"].map((m) => (
                  <button
                    key={m}
                    onClick={() => mode.mutate(m)}
                    disabled={mode.isPending}
                    className={`rounded-full border px-4 md:px-6 py-2 md:py-3 text-xs hover:border-primary hover:text-primary disabled:opacity-50 ${String(metrics.data?.["mode"]) === m ? "border-primary bg-surface-container text-primary" : "border-outline-variant"}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            ) : (
              <p className="font-mono text-[11px] text-on-surface-variant">operator or admin role required — mode changes are ledgered.</p>
            )}
          </Card>

          <Card title="Failure injections" sub="real paths — labeled events, never UI fakery (Rules §16.4)">
            {canOperate ? (
              <div className="flex flex-wrap gap-2 md:gap-2">
                {[
                  ["llm_outage", "LLM outage → DEGRADED"],
                  ["llm_restore", "LLM restore"],
                  ["webhook_storm", "Webhook storm 1,000→214"],
                  ["complaint", "Complaint mid-episode"],
                ].map(([s, label]) => (
                  <button
                    key={s}
                    onClick={() => inject.mutate(s)}
                    disabled={inject.isPending}
                    className="rounded-full border border-tertiary-container/50 px-4 md:px-6 py-2 md:py-3 text-xs text-tertiary-container hover:bg-tertiary-container/10 disabled:opacity-50"
                  >
                    ⚡ {label}
                  </button>
                ))}
              </div>
            ) : (
              <p className="font-mono text-[11px] text-on-surface-variant">operator or admin role required — injections exercise real control paths.</p>
            )}
            {Boolean(metrics.data?.["llm_outage"]) && (
              <p className="mt-4 font-mono text-[11px] text-on-tertiary-fixed">LLM outage active — banner live until llm_restore.</p>
            )}
          </Card>

          <Card title="Guardrail settings" sub="merchant cfg may only tighten hard bounds; changes are ledgered">
            {guardrails.data?.merchant ? (
              <GuardrailForm
                cfg={guardrails.data.merchant.cfg}
                onSave={(b) => saveGuardrails.mutate(b)}
                saving={saveGuardrails.isPending}
              />
            ) : (
              <p className="font-mono text-[11px] text-on-surface-variant">requires admin role · merchant config loads for admins only</p>
            )}
          </Card>

          <Card title="Counters">
            <dl className="grid grid-cols-2 gap-x-6 md:gap-x-24 gap-y-2 md:gap-y-4 font-mono text-xs">
              {Object.entries(counters).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-outline-variant/60 py-2">
                  <dt className="text-on-surface-variant">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Evaluation runner">
            <div className="flex items-center justify-between text-sm">
              <span>protocol tag {evalStatus.data?.preregistered_tag ?? ""}</span>
              <Chip tone={evalStatus.data?.tag_present ? "green" : "red"}>{String(evalStatus.data?.tag_present ?? false)}</Chip>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm">
              <span>run in progress</span>
              <Chip tone={evalStatus.data?.running ? "amber" : "slate"}>{String(evalStatus.data?.running ?? false)}</Chip>
            </div>
            <div className="mt-4"><SimulatedBadge /></div>
          </Card>

          <Card title="Exports" sub="watermarked CSV/JSON — # REFLEX SIMULATION DATA">
            <div className="flex flex-wrap gap-2">
              <button onClick={() => void downloadCsv()} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Episodes CSV</button>
              <button onClick={() => void downloadLedgerCsv()} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Ledger CSV</button>
              <button onClick={() => void downloadLedgerJson()} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Ledger JSON</button>
            </div>
            {exportErr && <p className="mt-2 font-mono text-[11px] text-error">{exportErr}</p>}
          </Card>

          <Card title="Session">
            <div className="flex flex-wrap gap-2">
              <button onClick={() => void inject.mutate("llm_restore")} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">clear degraded banner</button>
              <Link to="/login" onClick={() => { clearToken(); qc.clear(); }} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Sign out</Link>
            </div>
          </Card>

          <Card title="Channel simulator console" sub="live [SIMULATED] pipeline events from /api/stream (SSE)">
            <ol className="space-y-2 font-mono text-[11px]">
              {events.map((e, i) => (
                <li key={`${e.at}-${i}`} className="flex justify-between border-b border-outline-variant/60 py-1">
                  <span className="text-on-surface">{e.type}</span>
                  <span className="text-on-surface-variant">{e.detail ? `${e.detail} · ` : ""}{new Date(e.at).toLocaleTimeString()}</span>
                </li>
              ))}
              {events.length === 0 && <li className="text-on-surface-variant">waiting for events — start the demo replay…</li>}
            </ol>
          </Card>
        </div>
      </main>
      <BottomNav />
    </div>
  );
}

function GuardrailForm({ cfg, onSave, saving }: { cfg: Record<string, unknown>; onSave: (b: Record<string, unknown>) => void; saving: boolean }) {
  const [caps, setCaps] = useState(Number(cfg["caps_per_episode"] ?? 4));
  const [contacts, setContacts] = useState(Number(cfg["contacts_per_day"] ?? 2));
  const [budget, setBudget] = useState(Number(cfg["budget_paise_daily"] ?? 500000));
  const [threshold, setThreshold] = useState(Number(cfg["approval_threshold_paise"] ?? 5000000));
  useEffect(() => {
    setCaps(Number(cfg["caps_per_episode"] ?? 4));
    setContacts(Number(cfg["contacts_per_day"] ?? 2));
    setBudget(Number(cfg["budget_paise_daily"] ?? 500000));
    setThreshold(Number(cfg["approval_threshold_paise"] ?? 5000000));
  }, [cfg]);
  return (
    <div className="mt-4 space-y-3 text-xs">
      <label className="block font-mono text-[11px] text-on-surface-variant">caps / episode: {caps}
        <input type="range" min={0} max={4} value={caps} onChange={(e) => setCaps(Number(e.target.value))} className="mt-1 w-full" />
      </label>
      <label className="block font-mono text-[11px] text-on-surface-variant">contacts / customer / day: {contacts}
        <input type="range" min={0} max={4} value={contacts} onChange={(e) => setContacts(Number(e.target.value))} className="mt-1 w-full" />
      </label>
      <label className="block font-mono text-[11px] text-on-surface-variant">daily budget (paise): {budget.toLocaleString()}
        <input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value) || 0)} className="mt-1 w-full rounded-lg border border-outline-variant bg-surface-container px-2 py-1 font-mono" />
      </label>
      <label className="block font-mono text-[11px] text-on-surface-variant">approval threshold (paise): {threshold.toLocaleString()}
        <input type="number" value={threshold} onChange={(e) => setThreshold(Number(e.target.value) || 0)} className="mt-1 w-full rounded-lg border border-outline-variant bg-surface-container px-2 py-1 font-mono" />
      </label>
      <p className="font-mono text-[10px] text-outline">quiet hours 21:00–09:00 IST (fixed in this build)</p>
      <button onClick={() => onSave({ caps_per_episode: caps, contacts_per_day: contacts, quiet_hours: "21:00-09:00", budget_paise_daily: budget, approval_threshold_paise: threshold })} disabled={saving} className="rounded-full bg-primary-container px-6 py-2 font-mono text-[11px] font-semibold text-on-primary hover:bg-primary disabled:opacity-50">
        {saving ? "saving…" : "Save (ledgered)"}
      </button>
    </div>
  );
}

function Card({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-outline-variant bg-surface-container-lowest p-6 md:p-6 warm-shadow">
      <h2 className="font-display text-headline-sm text-primary">{title}</h2>
      {sub && <p className="mb-4 mt-2 font-mono text-[11px] text-on-surface-variant">{sub}</p>}
      <div className={sub ? "" : "mt-4"}>{children}</div>
    </section>
  );
}
