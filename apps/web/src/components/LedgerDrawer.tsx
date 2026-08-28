import { useQuery } from "@tanstack/react-query";
import type { LedgerEventDto } from "../lib/api";
import { api } from "../lib/api";
import { useUi } from "../store";
import { Overlay } from "./EVDrawer";

/** Ledger drawer (Design §14): hash timeline incl. blocked actions. */
export function LedgerDrawer({ episodeId }: { episodeId: string }) {
  const close = useUi((s) => s.openLedgerDrawer);
  const verify = useQuery({
    queryKey: ["ledger-verify"],
    queryFn: () => api<{ valid: boolean; first_bad_seq: number | null; checked: number }>("/api/ledger/verify"),
    enabled: false,
  });
  const q = useQuery({
    queryKey: ["ledger", episodeId],
    queryFn: () => api<{ valid: boolean; events: LedgerEventDto[] }>(`/api/episodes/${episodeId}/ledger`),
  });

  return (
    <Overlay title="Ledger — hash-chained audit trail" onClose={() => close(null)} width="640px">
      {q.isError && <div className="px-6 md:px-24 py-6 text-sm text-error">409 chain break detected — system should halt itself.</div>}
      {q.isLoading && <Skeleton />}
      {q.data && (
        <>
          <div className={`mx-6 md:mx-24 mt-6 md:mt-16 rounded-xl border px-4 md:px-12 py-3 md:py-4 text-xs ${q.data.valid ? "border-secondary text-secondary bg-secondary-container/20" : "border-error text-error bg-error-container"}`}>
            chain verification: {q.data.valid ? "valid ✓" : "BROKEN ✗"}
          </div>
          <ol className="space-y-0 px-6 md:px-24 py-6 md:py-16">
            {q.data.events.map((e) => (
              <li key={e.seq} className="relative border-l border-outline-variant pb-6 md:pb-16 pl-4 md:pl-16 font-mono text-[11px]">
                <span className="absolute -left-[5px] top-4 h-8 w-8 rounded-full border border-outline-variant bg-background" />
                <div className="text-on-surface-variant">#{e.seq} · {new Date(e.created_at).toLocaleTimeString()}</div>
                <div className="text-on-surface">{String(e.event["type"] ?? "?")}</div>
                {typeof e.event["reason"] === "string" && e.event["reason"] && <div className="text-on-tertiary-container">reason: {e.event["reason"] as string}</div>}
                {typeof e.event["mode"] === "string" && <div className="text-on-surface-variant">mode={e.event["mode"] as string}</div>}
                {typeof e.event["intervention"] === "string" && <div className="text-on-surface">{e.event["intervention"] as string}</div>}
                <div className="truncate text-outline" title={`${e.prev_hash} → ${e.hash}`}>sha256 {e.hash.slice(0, 24)}…</div>
              </li>
            ))}
          </ol>
          <div className="px-6 md:px-24 pb-6 md:pb-24 flex items-center gap-4">
            <button
              className="rounded-full border border-primary px-4 md:px-12 py-2 md:py-3 text-xs text-primary hover:bg-surface-container"
              onClick={() => void verify.refetch()}
            >
              {verify.isFetching ? "verifying…" : "verify full chain"}
            </button>
            {verify.data && (
              <span className={`font-mono text-[11px] ${verify.data.valid ? "text-secondary" : "text-error"}`}>
                {verify.data.valid ? `valid ✓ — ${verify.data.checked} events` : `TAMPERED at seq ${verify.data.first_bad_seq}`}
              </span>
            )}
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
        <div key={i} className="h-10 rounded-card bg-surface-container-high" />
      ))}
    </div>
  );
}
