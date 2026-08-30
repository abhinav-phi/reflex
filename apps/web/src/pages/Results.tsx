import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EvalRunDto } from "../lib/api";
import { api, post } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { BottomNav } from "../components/BottomNav";
import { SimulatedBadge } from "../components/Chips";
import { useTitle } from "../hooks/useTitle";


function point(m: Record<string, unknown>): number | null {
  const v = m["point"] ?? m["value"];
  return typeof v === "number" ? v : null;
}

/** Results (AppFlow §4G): arm table with CIs + ablation bars — all [SIMULATED]. */
export default function Results() {
  useTitle("Results — Reflex");
  const q = useQuery({
    queryKey: ["eval"],
    queryFn: () => api<{ "[SIMULATED]": boolean; runs: EvalRunDto[] }>("/api/metrics/eval"),
    refetchInterval: 60000,
  });

  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function runEval() {
    setRunning(true);
    setRunMsg(null);
    try {
      await post("/api/eval/run", {});
      setRunMsg("eval run started — the table refreshes when the run commits");
      setTimeout(() => void q.refetch(), 8000);
    } catch (e) {
      setRunMsg(e instanceof Error ? e.message : "eval run failed");
    } finally {
      setRunning(false);
    }
  }

  const runs = q.data?.runs ?? [];
  // latest official protocol run per (arm, ablation)
  const byKey = new Map<string, EvalRunDto>();
  for (const r of runs) {
    const k = `${r.arm}|${r.ablation ?? ""}`;
    if (!byKey.has(k)) byKey.set(k, r);
  }
  const headline = [...byKey.values()].filter((r) => !r.ablation);
  const ablations = [...byKey.values()].filter((r) => r.ablation);

  function metric(r: EvalRunDto, name: string): Record<string, unknown> | undefined {
    return r.metrics.find((m) => m.metric === name) as unknown as Record<string, unknown> | undefined;
  }

  const chartData = ablations
    .map((r) => ({
      name: `A-${r.ablation}`,
      rate: (() => { const m = metric(r, "recovery_rate"); return m ? ((point(m) ?? 0) * 100) : 0; })(),
      ci: (() => {
        const m = metric(r, "recovery_rate") ?? {};
        const lo = Number(m["ci_low"] ?? 0);
        return point(m) != null ? point(m)! - lo : 0;
      })(),
    }))
    .concat(
      headline.map((r) => ({
        name: r.arm.toUpperCase(),
        rate: (() => { const m = metric(r, "recovery_rate"); return m ? ((point(m) ?? 0) * 100) : 0; })(),
        ci: 0,
      })),
    );

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[1200px] px-4 md:px-24 pb-48 pt-8 md:pt-32">
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-3 font-display text-headline-md text-primary">Evaluation results <SimulatedBadge /></h1>
            <p className="mt-2 font-mono text-label-mono text-on-surface-variant">Pre-registered protocol · seeds {`{${[...new Set(q.data?.runs.flatMap((r) => r.metrics.map((m) => m.seed).filter((x): x is number => x != null)))].sort((a, b) => a - b).join(", ") || "?..."}}`} · bootstrap 95% CI (1,000 resamples)</p>
          </div>
          <button onClick={() => void runEval()} disabled={running} className="rounded-full bg-primary-container text-on-primary px-6 py-3 text-xs font-mono font-semibold hover:bg-primary disabled:opacity-50">{running ? "starting…" : "▶ Run eval (protocol-tagged)"}</button>
        </header>

        {runMsg && <p className="mt-4 font-mono text-[11px] text-on-surface-variant">{runMsg}</p>}

        {runs.length === 0 && <div className="mt-8 md:mt-24 rounded-xl border border-dashed border-outline-variant p-8 md:p-12 text-center text-sm text-on-surface-variant bg-surface-container-lowest warm-shadow">No evaluation runs yet. <code>./eval/reproduce.sh</code> or press Run — protocol pre-registered.</div>}

        <section className="mt-8 md:mt-24 overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest warm-shadow">
          <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-outline-variant bg-surface-container text-left font-mono text-label-mono uppercase text-on-surface-variant">
              <tr>
                <th className="px-4 md:px-6 py-3 md:py-4">Arm</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Recovery rate % [CI]</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Cost / ₹100</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Complaint %</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Tag</th>
              </tr>
            </thead>
            <tbody>
              {headline.map((r) => {
                const rr = metric(r, "recovery_rate");
                const cp = metric(r, "cost_per_100p");
                const cm = metric(r, "complaint_rate");
                return (
                  <tr key={r.run_id} className="border-b border-surface-container-high last:border-0 h-[64px]">
                    <td className="px-4 md:px-6 font-semibold">{r.arm.toUpperCase()}</td>
                    <td className="px-4 md:px-6 tabular-nums">{fmtCi(rr)}</td>
                    <td className="px-4 md:px-6 tabular-nums">{pt(cp)}</td>
                    <td className="px-4 md:px-6 tabular-nums">{pt(cm, true)}</td>
                    <td className="px-4 md:px-6 font-mono text-[11px] text-outline">{r.preregistered_tag ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>
        </section>

        {chartData.length > 0 && (
          <section className="mt-8 md:mt-24 rounded-xl border border-outline-variant bg-surface-container-lowest p-6 md:p-6 warm-shadow">
            <h2 className="font-display text-headline-sm text-primary">Ablations — which AI component buys which points</h2>
            <div className="mx-auto mt-6 md:mt-4 h-60 w-full">
              <ResponsiveContainer>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e3e3dd" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="rate" fill="#16261d" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}
      </main>
      <BottomNav />
    </div>
  );
}

/** The eval DB stores rates as fractions (0.31 = 31%); render as percentages. */
function pt(m?: Record<string, unknown>, asPct = false): string {
  const v = m ? point(m) : null;
  if (v == null) return "—";
  return asPct ? `${(v * 100).toFixed(1)}%` : String(v);
}

function fmtCi(m?: Record<string, unknown>): string {
  const p = m ? point(m) : null;
  if (p == null || !m) return "—";
  const lo = Number(m["ci_low"]);
  const hi = Number(m["ci_high"]);
  if (lo === 0 && hi === 0) return `${(p * 100).toFixed(1)}%`;
  return `${(p * 100).toFixed(1)} [${(lo * 100).toFixed(1)}, ${(hi * 100).toFixed(1)}]`;
}
