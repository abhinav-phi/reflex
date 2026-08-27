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
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[1200px] px-4 md:px-24 pb-48 pt-8 md:pt-32">
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <h1 className="flex items-center gap-3 font-display text-headline-md text-primary">Audit — append-only ledger <SimulatedBadge /></h1>
          <button onClick={() => void verify()} className="rounded-full bg-primary-container text-on-primary px-6 py-3 text-xs font-mono font-semibold hover:bg-primary"> {verifying ? "verifying…" : "Verify chain"} </button>
        </header>

        {result && (
          <div className={`mt-6 md:mt-16 rounded-xl border p-4 md:p-6 text-sm ${result.valid ? "border-secondary text-secondary bg-secondary-container/20" : "border-error text-error bg-error-container"}`}>
            {result.valid ? <>Chain valid ✓ — {result.checked} events verified in order.</> : <>TAMPER DETECTED at seq {result.first_bad_seq} — integrity over availability: halt.</>}
          </div>
        )}

        <section className="mt-8 md:mt-24 overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest warm-shadow">
          <table className="w-full text-sm">
            <thead className="border-b border-outline-variant bg-surface-container text-left font-mono text-label-mono uppercase text-on-surface-variant">
              <tr>
                <th className="px-4 md:px-6 py-3 md:py-4">Episode</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Amount</th>
                <th className="px-4 md:px-6 py-3 md:py-4">Status</th>
              </tr>
            </thead>
            <tbody>
              {eps.map((e) => (
                <tr key={e.id} className="border-b border-surface-container-high last:border-0 h-[64px]">
                  <td className="px-4 md:px-6 font-mono text-xs">{e.id.slice(0, 8)}</td>
                  <td className="px-4 md:px-6 tabular-nums">{formatINR(asPaise(e.amount_paise))}</td>
                  <td className="px-4 md:px-6"><Chip tone={e.status === "recovered" ? "green" : "slate"}>{e.status}</Chip></td>
                </tr>
              ))}
              {eps.length === 0 && <tr><td className="px-6 py-12 text-center text-on-surface-variant" colSpan={3}>Ledger empty — start a replay first.</td></tr>}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
