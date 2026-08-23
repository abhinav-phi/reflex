import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, post, getToken, clearToken } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { Chip, SimulatedBadge } from "../components/Chips";

/** Ops (AppFlow §12): modes, injections, guardrail settings, parked actions. */
export default function Ops() {
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<Record<string, unknown>>("/api/metrics/live"),
    refetchInterval: 3000,
  });
  const evalStatus = useQuery({
    queryKey: ["evalstatus"],
    queryFn: () => api<{ running: boolean; tag_present: boolean }>("/api/eval/status"),
  });
  const [msg, setMsg] = useState<string | null>(null);

  const mode = useMutation({
    mutationFn: (m: string) => post("/api/control/mode", { mode: m }),
    onSuccess: () => void metrics.refetch(),
  });
  const inject = useMutation({
    mutationFn: (scenario: string) => post<{ ok: boolean }>(`/api/control/inject/${scenario}`, {}),
    onSuccess: (d) => setMsg(JSON.stringify(d)),
  });

  const counters = (metrics.data?.["counters"] ?? {}) as Record<string, number>;

  return (
    <div className="min-h-screen bg-cmd-bg text-ink-dark">
      <ControlBar />
      <main className="mx-auto max-w-[1200px] px-24 pb-48">
        <h1 className="mt-32 text-xl font-semibold">Ops — controls & failure injections</h1>

        <div className="mt-24 grid gap-16 md:grid-cols-2">
          <Card title="Mode control">
            <div className="flex flex-wrap gap-8">
              {["advisory", "autonomous", "degraded", "halted"].map((m) => (
                <button
                  key={m}
                  onClick={() => mode.mutate(m)}
                  className="rounded-btn border border-cmd-border px-16 py-8 text-xs hover:border-primary"
                >
                  {m}
                </button>
              ))}
            </div>
          </Card>

          <Card title={`Failure injections ${" "}`} sub="real paths — labeled events, never UI fakery (Rules §16.4)">
            <div className="flex flex-wrap gap-8">
              {[
                ["llm_outage", "LLM outage → DEGRADED"],
                ["llm_restore", "LLM restore"],
                ["webhook_storm", "Webhook storm 1,000→214"],
                ["complaint", "Complaint mid-episode"],
              ].map(([s, label]) => (
                <button
                  key={s}
                  onClick={() => inject.mutate(s)}
                  className="rounded-btn border border-amber-500/50 px-16 py-8 text-xs text-amber-200 hover:bg-amber-600/10"
                >
                  ⚡ {label}
                </button>
              ))}
            </div>
            {msg && <p className="mt-8 font-mono text-[11px] text-slate-400">{msg}</p>}
          </Card>

          <Card title="Counters">
            <dl className="grid grid-cols-2 gap-x-24 gap-y-4 font-mono text-xs">
              {Object.entries(counters).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-cmd-border/60 py-2">
                  <dt className="text-slate-400">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Evaluation runner">
            <div className="flex items-center justify-between text-sm">
              <span>protocol tag present</span>
              <Chip tone={evalStatus.data?.tag_present ? "green" : "red"}>
                {String(evalStatus.data?.tag_present ?? false)}
              </Chip>
            </div>
            <div className="mt-8 flex items-center justify-between text-sm">
              <span>run in progress</span>
              <Chip tone={evalStatus.data?.running ? "amber" : "slate"}>
                {String(evalStatus.data?.running ?? false)}
              </Chip>
            </div>
            <SimulatedBadge />
          </Card>

          <Card title="Session">
            <button
              onClick={() => {
                clearToken();
                location.href = "/login";
              }}
              className="rounded-btn border border-cmd-border px-16 py-8 text-xs"
            >
              Sign out {getToken()?.slice(0, 10)}…
            </button>
          </Card>
        </div>
      </main>
    </div>
  );
}

function Card({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-card border border-cmd-border bg-cmd-surface p-16">
      <h2 className="text-sm font-semibold">{title}</h2>
      {sub && <p className="mb-8 mt-4 text-[11px] text-slate-500">{sub}</p>}
      <div className={sub ? "" : "mt-8"}>{children}</div>
    </section>
  );
}
