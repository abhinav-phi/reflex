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
import { SimulatedBadge } from "../components/Chips";


function point(m: Record<string, unknown>): number | null {
  const v = m["point"] ?? m["value"];
  return typeof v === "number" ? v : null;
}

/** Results (AppFlow §4G): arm table with CIs + ablation bars — all [SIMULATED]. */
export default function Results() {
  const q = useQuery({
    queryKey: ["eval"],
    queryFn: () => api<{ "[SIMULATED]": boolean; runs: EvalRunDto[] }>("/api/metrics/eval"),
    refetchInterval: 5000,
  });

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
      rate: (() => { const m = metric(r, "recovery_rate_pct"); return m ? (point(m) ?? 0) : 0; })(),
      ci: (() => {
        const m = metric(r, "recovery_rate_pct") ?? {};
        const lo = Number(m["ci_low"] ?? 0);
        return point(m) != null ? point(m)! - lo : 0;
      })(),
    }))
    .concat(
      headline.map((r) => ({
        name: r.arm.toUpperCase(),
        rate: (() => { const m = metric(r, "recovery_rate_pct"); return m ? (point(m) ?? 0) : 0; })(),
        ci: 0,
      })),
    );

  async function runEval() {
    await post("/api/eval/run", {});
  }

  return (
    <div className="min-h-screen bg-lightbg text-ink-light">
      <div className="[&_*]:!text-ink-light [&_.bg-cmd-bg]:bg-lightbg">
        <ControlBar />
      </div>
      <main className="mx-auto max-w-[1200px] px-24 pb-48 pt-32">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-12 text-xl font-semibold">
              Evaluation results <SimulatedBadge />
            </h1>
            <p className="mt-4 text-xs text-slate-500">
              Pre-registered protocol · seeds {"{42, 1337, 2025}"} · bootstrap 95% CI (1,000 resamples)
            </p>
          </div>
          <button
            onClick={() => void runEval()}
            className="rounded-btn bg-primary px-16 py-8 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            ▶ Run eval (protocol-tagged)
          </button>
        </header>

        {runs.length === 0 && (
          <div className="mt-24 rounded-card border border-dashed border-slate-300 p-48 text-center text-sm text-slate-500">
            No evaluation runs yet. <code>./eval/reproduce.sh</code> or press Run — protocol pre-registered.
          </div>
        )}

        {/* Arm table */}
        <section className="mt-24 overflow-hidden rounded-card border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-16 py-8">Arm</th>
                <th className="px-16 py-8">Recovery rate % [CI]</th>
                <th className="px-16 py-8">Cost / ₹100</th>
                <th className="px-16 py-8">Complaint %</th>
                <th className="px-16 py-8">Tag</th>
              </tr>
            </thead>
            <tbody>
              {headline.map((r) => {
                const rr = metric(r, "recovery_rate_pct");
                const cp = metric(r, "cost_per_100");
                const cm = metric(r, "complaint_rate_pct");
                return (
                  <tr key={r.run_id} className="border-b border-slate-100 last:border-0">
                    <td className="px-16 py-10 font-semibold">{r.arm.toUpperCase()}</td>
                    <td className="px-16 py-10 tabular-nums">{fmtCi(rr)}</td>
                    <td className="px-16 py-10 tabular-nums">{pt(cp)}</td>
                    <td className="px-16 py-10 tabular-nums">{pt(cm)}</td>
                    <td className="px-16 py-10 font-mono text-[11px] text-slate-400">
                      {r.preregistered_tag ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* Ablation bars */}
        {chartData.length > 0 && (
          <section className="mt-24 rounded-card border border-slate-200 bg-white p-24 shadow-sm">
            <h2 className="text-sm font-semibold">Ablations — which AI component buys which points</h2>
            <div className="mx-auto mt-16 h-240 w-full">
              <ResponsiveContainer>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="rate" fill="#4F46E5" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function pt(m?: Record<string, unknown>): string {
  const v = m ? point(m) : null;
  return v == null ? "—" : String(v);
}

function fmtCi(m?: Record<string, unknown>): string {
  const p = m ? point(m) : null;
  if (p == null || !m) return "—";
  const lo = Number(m["ci_low"]);
  const hi = Number(m["ci_high"]);
  return `${p.toFixed(1)} [${lo.toFixed(1)}, ${hi.toFixed(1)}]`;
}
