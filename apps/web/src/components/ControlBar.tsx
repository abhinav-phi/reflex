import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../lib/api";
import { useUi } from "../store";
import { TestModeBadge, SimulatedBadge } from "./Chips";

/** Sticky control bar (AppFlow §4.1): mode badge · kill switch · demo controls. */
export function ControlBar() {
  const qc = useQueryClient();
  const { mode, setMode, banner, setBanner, sseConnected, lastEventAt } = useUi();

  const modeMut = useMutation({
    mutationFn: (m: string) => post("/api/control/mode", { mode: m }),
    onSuccess: (_d, m) => {
      setMode(m);
      if (m === "halted") setBanner({ kind: "HALTED" });
      else setBanner({ kind: null });
      void qc.invalidateQueries();
    },
  });

  const halted = mode === "halted";

  return (
    <div className="sticky top-0 z-40 border-b border-cmd-border bg-cmd-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1400px] items-center gap-16 px-24 py-12">
        <a href="/dashboard" className="text-lg font-bold tracking-tight text-ink-dark">
          Refl<span className="text-ai-accent">e</span>x
        </a>
        <SimulatedBadge />
        <TestModeBadge />

        <span
          className={`ml-16 rounded-chip px-12 py-4 text-xs font-semibold ${
            mode === "halted"
              ? "bg-red-600/30 text-red-200"
              : mode === "degraded"
                ? "bg-amber-500/25 text-amber-200"
                : mode === "autonomous"
                  ? "bg-emerald-600/25 text-emerald-200"
                  : "bg-slate-700/50 text-slate-200"
          }`}
          aria-live={halted ? "assertive" : "polite"}
        >
          MODE: {mode.toUpperCase()}
        </span>

        <nav className="ml-16 flex gap-12 text-[13px] text-ink-muted">
          {[
            ["/dashboard", "Dashboard"],
            ["/approvals", "Approvals"],
            ["/results", "Results"],
            ["/audit", "Audit"],
            ["/ops", "Ops"],
          ].map(([href, label]) => (
            <a key={href} href={href} className="hover:text-ink-dark">
              {label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-12">
          <span className={`text-[11px] ${sseConnected ? "text-emerald-400" : "text-amber-400"}`}>
            {sseConnected ? "live ●" : `reconnecting… data may lag${lastEventAt ? ` (${new Date(lastEventAt).toLocaleTimeString()})` : ""}`}
          </span>
          <button
            onClick={() => modeMut.mutate(halted ? "autonomous" : "halted")}
            className={`rounded-btn border px-16 py-8 text-xs font-semibold ${
              halted
                ? "border-emerald-500 text-emerald-300 hover:bg-emerald-600/20"
                : "border-red-500/70 text-red-300 hover:bg-red-600/20"
            }`}
          >
            {halted ? "▶ Resume agent" : "⏻ Kill switch"}
          </button>
        </div>
      </div>

      {banner.kind === "DEGRADED" && !halted && (
        <div className="border-t border-amber-500/40 bg-amber-500/15 px-24 py-6 text-center text-xs text-amber-200">
          DEGRADED MODE — LLM unavailable · deterministic fallback active · actions stamped DEGRADED
        </div>
      )}
      {halted && (
        <div className="border-t border-red-500/60 bg-red-600/20 px-24 py-6 text-center text-xs font-semibold text-red-200">
          HALTED — kill switch active · scheduled actions cancelled · deliberate re-enable required
        </div>
      )}
    </div>
  );
}
