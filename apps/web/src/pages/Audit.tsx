import { useEffect, useState } from "react";
import { api, downloadFile } from "../lib/api";
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
  const [ledgerEvents, setLedgerEvents] = useState<{ seq: number; episode_id: string; event: Record<string, unknown>; created_at: string }[]>([]);

  useEffect(() => {
    Promise.all([
      api<{ items: EpRow[] }>("/api/episodes?limit=100").then((d) => setEps(d.items)),
      api<{ events: typeof ledgerEvents }>(`/api/ledger/export?format=json&limit=200`).then((d) => setLedgerEvents(d.events ?? [])),
    ]).catch(() => {});
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
          <button onClick={() => void verify()} className="rounded-full bg-primary-container text-on-primary px-6 py-3 text-xs font-mono font-semibold hover:bg-primary disabled:opacity-50" disabled={verifying}>
            {verifying ? "verifying…" : "Verify chain"}
          </button>
        </header>

        {result && (
          <div className={`mt-6 md:mt-16 rounded-xl border p-4 md:p-6 text-sm ${result.valid ? "border-secondary text-secondary bg-secondary-container/20" : "border-error text-error bg-error-container"}`}>
            {result.valid ? <>Chain valid ✓ — {result.checked} events verified in order.</> : <>TAMPER DETECTED at seq {result.first_bad_seq} — integrity over availability: halt.</>}
          </div>
        )}

        <section className="mt-8 md:mt-24 overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest warm-shadow">
          <div className="flex items-center justify-between border-b border-outline-variant px-4 md:px-6 py-4">
            <h2 className="font-display text-headline-sm text-primary">Episode summary</h2>
            <div className="flex gap-2">
              <button onClick={() => void downloadFile("/api/episodes/export?format=csv", "reflex_episodes_simulated.csv")} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Export episodes CSV</button>
              <button onClick={() => void downloadFile("/api/ledger/export?format=csv", "reflex_action_ledger_simulated.csv")} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Export ledger CSV</button>
              <button onClick={() => void downloadFile("/api/ledger/export?format=json", "reflex_action_ledger_simulated.json")} className="rounded-full border border-outline-variant px-4 py-2 text-xs hover:border-primary hover:text-primary">Export ledger JSON</button>
            </div>
          </div>
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

        <section className="mt-8 md:mt-24 overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest warm-shadow">
          <div className="flex items-center justify-between border-b border-outline-variant px-4 md:px-6 py-4">
            <h2 className="font-display text-headline-sm text-primary">Recent ledger events</h2>
            <span className="font-mono text-[11px] text-on-surface-variant">{ledgerEvents.length} events</span>
          </div>
          <ol className="space-y-0 px-4 md:px-6 py-4 font-mono text-[11px]">
            {ledgerEvents.map((e) => (
              <li key={e.seq} className="relative border-l border-outline-variant pb-4 pl-4 md:pl-8">
                <span className="absolute -left-[5px] top-2 h-3 w-3 rounded-full border border-outline-variant bg-background" />
                <div className="text-on-surface-variant">#{e.seq} · {new Date(e.created_at).toLocaleTimeString()}</div>
                <div className="text-on-surface">{String(e.event["type"] ?? "?")}</div>
                {typeof e.event["reason"] === "string" && e.event["reason"] && <div className="text-on-tertiary-container">reason: {e.event["reason"]}</div>}
                {typeof e.event["mode"] === "string" && <div className="text-on-surface-variant">mode={e.event["mode"]}</div>}
              </li>
            ))}
            {ledgerEvents.length === 0 && <li className="text-on-surface-variant">No events yet.</li>}
          </ol>
        </section>
      </main>
    </div>
  );
}
