import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { Chip, SimulatedBadge } from "../components/Chips";
import { formatINR, asPaise } from "../lib/format";

/** Audit (AppFlow §4I): ledger browser + chain verification; tamper ⇒ red. */
interface LedgerResp {
  valid: boolean;
  first_bad_seq: number | null;
  checked: number;
}

interface EpRow {
  id: string;
  amount_paise: number;
  status: string;
}

export default function Audit() {
  const [result, setResult] = useState<LedgerResp | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [eps, setEps] = useState<EpRow[]>([]);

  useEffect(() => {
    api<{ items: EpRow[] }>("/api/episodes?limit=100")
      .then((d) => setEps(d.items))
      .catch(() => setEps([]));
  }, []);

  async function verify(): Promise<void> {
    setVerifying(true);
    try {
      setResult(await api<LedgerResp>("/api/ledger/verify"));
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="min-h-screen bg-lightbg text-ink-light">
      <ControlBar />
      <main className="mx-auto max-w-[1200px] px-24 pb-48 pt-32">
        <header className="flex items-center justify-between">
          <h1 className="flex items-center gap-12 text-xl font-semibold">
            Audit — append-only ledger <SimulatedBadge />
          </h1>
          <button
            onClick={() => void verify()}
            className="rounded-btn bg-primary px-16 py-8 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            {verifying ? "verifying…" : "Verify chain"}
          </button>
        </header>

        {result && (
          <div
            className={`mt-16 rounded-card border p-16 text-sm ${
              result.valid
                ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                : "border-red-400 bg-red-50 text-red-700"
            }`}
          >
            {result.valid ? (
              <>Chain valid ✓ — {result.checked} events verified in order.</>
            ) : (
              <>TAMPER DETECTED at seq {result.first_bad_seq} — integrity over availability: halt.</>
            )}
          </div>
        )}

        <section className="mt-24 overflow-hidden rounded-card border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-16 py-8">Episode</th>
                <th className="px-16 py-8">Amount</th>
                <th className="px-16 py-8">Status</th>
              </tr>
            </thead>
            <tbody>
              {eps.map((e) => (
                <tr key={e.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-16 py-10 font-mono text-xs">{e.id.slice(0, 8)}</td>
                  <td className="px-16 py-10 tabular-nums">{formatINR(asPaise(e.amount_paise))}</td>
                  <td className="px-16 py-10">
                    <Chip tone={e.status === "recovered" ? "green" : "slate"}>{e.status}</Chip>
                  </td>
                </tr>
              ))}
              {eps.length === 0 && (
                <tr>
                  <td className="px-16 py-24 text-center text-slate-400" colSpan={3}>
                    Ledger empty — start a replay first.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
