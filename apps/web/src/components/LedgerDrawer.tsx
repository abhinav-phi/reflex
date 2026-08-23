import { useQuery } from "@tanstack/react-query";
import type { LedgerEventDto } from "../lib/api";
import { api, post } from "../lib/api";
import { Overlay } from "./EVDrawer";

/** Ledger drawer (Design §14): hash timeline incl. blocked actions. */
export function LedgerDrawer({ episodeId }: { episodeId: string }) {
  const q = useQuery({
    queryKey: ["ledger", episodeId],
    queryFn: () => api<{ valid: boolean; events: LedgerEventDto[] }>(`/api/episodes/${episodeId}/ledger`),
  });

  return (
    <Overlay title="Ledger — hash-chained audit trail" onClose={() => window.dispatchEvent(new CustomEvent("close-ledger"))} width="640px">
      {q.isError && <div className="px-24 py-16 text-sm text-red-400">409 chain break detected — system should halt itself.</div>}
      {q.isLoading && <Skeleton />}
      {q.data && (
        <>
          <div className={`mx-24 mt-16 rounded-card border px-12 py-8 text-xs ${q.data.valid ? "border-emerald-500/50 text-emerald-300" : "border-red-500/60 text-red-300"}`}>
            chain verification: {q.data.valid ? "valid ✓" : "BROKEN ✗"}
          </div>
          <ol className="space-y-0 px-24 py-16">
            {q.data.events.map((e) => (
              <li key={e.seq} className="relative border-l border-cmd-border pb-16 pl-16 font-mono text-[11px]">
                <span className="absolute -left-[5px] top-4 h-8 w-8 rounded-full border border-cmd-border bg-cmd-bg" />
                <div className="text-slate-400">#{e.seq} · {new Date(e.created_at).toLocaleTimeString()}</div>
                <div className="text-ink-dark">{String(e.event["type"] ?? "?")}</div>
                {typeof e.event["reason"] === "string" && e.event["reason"] && (
                  <div className="text-amber-300">reason: {e.event["reason"] as string}</div>
                )}
                {typeof e.event["mode"] === "string" && <div className="text-slate-400">mode={e.event["mode"] as string}</div>}
                {typeof e.event["intervention"] === "string" && (
                  <div className="text-slate-300">{e.event["intervention"] as string}</div>
                )}
                <div className="truncate text-slate-500" title={e.hash}>
                  sha256 {e.hash.slice(0, 24)}…
                </div>
              </li>
            ))}
          </ol>
          <div className="px-24 pb-24">
            <button
              className="rounded-btn border border-primary px-12 py-8 text-xs text-indigo-200 hover:bg-primary/20"
              onClick={() => void post("/api/ledger/verify")}
            >
              verify full chain
            </button>
          </div>
        </>
      )}
    </Overlay>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-8 p-24">
      {[...Array(6)].map((_, i) => (
        <div key={i} className="h-10 rounded-card bg-white/5" />
      ))}
    </div>
  );
}
