import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, post, getRole, roleRankOf } from "../lib/api";
import { useUi } from "../store";
import { SimulatedBadge, TestModeBadge } from "./Chips";

export function ControlBar() {
  const qc = useQueryClient();
  const location = useLocation();
  const { mode, setMode, banner, setBanner, sseConnected } = useUi();
  const [confirmHalt, setConfirmHalt] = useState(false);
  const canSeeApprovals = (roleRankOf(getRole()) ?? -1) >= 2; // approver or admin

  // Sync the mode pill from the API on load — SSE only updates it on changes,
  // so a fresh page load would otherwise show a stale default (advisory).
  // 30s cadence keeps this far under the host edge rate-limit; SSE keeps the
  // pill fresh on real mode changes.
  const metrics = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<{ mode: string; llm_outage?: boolean }>("/api/metrics/live"),
    refetchInterval: 30000,
  });
  useEffect(() => {
    if (metrics.data?.mode) setMode(metrics.data.mode);
  }, [metrics.data?.mode, setMode]);

  const modeMut = useMutation({
    mutationFn: (m: string) => post("/api/control/mode", { mode: m, reason: m === "halted" ? "kill switch" : "resume from control bar" }),
    onSuccess: (_d, m) => {
      setMode(m);
      if (m === "halted") setBanner({ kind: "HALTED" });
      else setBanner({ kind: metrics.data?.llm_outage ? "DEGRADED" : null });
      setConfirmHalt(false);
      void qc.invalidateQueries();
    },
  });

  const halted = mode === "halted";

  return (
    <div className="sticky top-0 z-40 border-b border-outline-variant bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1440px] items-center gap-6 px-4 md:px-margin py-4">
        <Link to="/dashboard" className="flex items-center gap-2 shrink-0">
          <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" } as React.CSSProperties}>radio_button_checked</span>
          <span className="font-display text-headline-sm font-bold tracking-tight text-primary">Reflex</span>
        </Link>

        <div className="flex items-center gap-2">
          <SimulatedBadge />
          <span className="hidden md:inline-flex"><TestModeBadge /></span>
          <span className={`hidden md:inline-flex items-center gap-1 rounded-full px-3 py-1 font-mono text-[10px] tracking-widest ${halted ? "bg-error-container text-error" : banner.kind === "DEGRADED" ? "bg-tertiary-fixed text-on-tertiary-fixed" : "bg-outline-variant text-on-surface"}`}>MODE: {mode.toUpperCase()}</span>
        </div>

        <nav className="hidden md:flex gap-6 ml-4">
          {[
            ["/dashboard", "Dashboard"],
            ["/approvals", "Approvals"],
            ["/results", "Results"],
            ["/audit", "Audit"],
            ["/ops", "Ops"],
          ].filter(([to]) => to !== "/approvals" || canSeeApprovals)
            .map(([to, label]) => {
            const active = location.pathname === to;
            return (
              <Link key={to} to={to} className={`font-mono text-label-mono ${active ? "text-primary font-bold border-b-2 border-primary pb-1" : "text-on-surface-variant font-medium hover:text-primary"} transition-colors`}>
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3 md:gap-4">
          <span className={`hidden md:inline-flex items-center gap-1.5 text-[10px] font-mono ${sseConnected ? "text-secondary" : "text-outline"}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sseConnected ? "bg-secondary" : "bg-outline"} ${sseConnected ? "animate-pulse" : ""}`} />
            {sseConnected ? "connected" : "connecting…"}
          </span>
          <button
            onClick={() => (halted ? modeMut.mutate("advisory") : setConfirmHalt(true))}
            disabled={modeMut.isPending}
            className={`hidden md:inline-flex font-mono text-label-mono border rounded-full px-4 py-1.5 uppercase transition-colors disabled:opacity-50 ${halted ? "border-secondary text-secondary hover:bg-secondary-container/20" : "border-on-tertiary-container text-on-tertiary-container hover:bg-error-container"}`}
            aria-live={halted ? "assertive" : "polite"}
          >
            {halted ? "Resume" : "Kill switch"}
          </button>
          <button
            onClick={() => (halted ? modeMut.mutate("advisory") : setConfirmHalt(true))}
            disabled={modeMut.isPending}
            className="md:hidden px-4 py-2 rounded-full border border-error text-error font-mono text-label-mono hover:bg-error/10 transition-colors disabled:opacity-50"
          >
            {halted ? "Resume" : "Kill switch"}
          </button>
          <Link to="/ops" className="text-primary hover:text-primary-container transition-colors" aria-label="Ops settings">
            <span className="material-symbols-outlined">settings</span>
          </Link>
        </div>
      </div>

      {banner.kind === "DEGRADED" && !halted && (
        <div className="border-t border-amber-500/40 bg-amber-500/15 px-4 md:px-margin py-3 text-center text-xs text-amber-800">DEGRADED MODE — LLM unavailable · deterministic fallback active · actions stamped DEGRADED</div>
      )}
      {halted && (
        <div className="border-t border-error/60 bg-error-container px-4 md:px-margin py-3 text-center text-xs font-semibold text-on-error-container">HALTED — kill switch active · scheduled actions cancelled · deliberate re-enable required</div>
      )}

      {confirmHalt && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="Confirm kill switch">
          <div className="w-full max-w-md rounded-2xl border border-error/40 bg-surface-container-lowest p-8 warm-shadow-lg">
            <h2 className="font-display text-headline-sm text-error">Halt all actions immediately?</h2>
            <p className="mt-4 text-sm text-on-surface-variant">Scheduled actions are cancelled, episodes drain to HALTED, and dispatch stops everywhere. Resuming requires a deliberate click — this is the bounded-autonomy emergency stop.</p>
            <div className="mt-8 flex justify-end gap-3">
              <button onClick={() => setConfirmHalt(false)} className="rounded-full border border-outline-variant px-6 py-2 text-sm text-on-surface-variant hover:text-on-surface">Cancel</button>
              <button onClick={() => modeMut.mutate("halted")} disabled={modeMut.isPending} className="rounded-full bg-error text-on-error-container px-6 py-2 text-sm font-semibold hover:opacity-90 disabled:opacity-50">
                {modeMut.isPending ? "Halting…" : "Confirm halt"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
