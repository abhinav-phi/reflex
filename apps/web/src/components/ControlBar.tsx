import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../lib/api";
import { useUi } from "../store";
import { SimulatedBadge, TestModeBadge } from "./Chips";

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
    <div className="sticky top-0 z-40 border-b border-outline-variant bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1440px] items-center gap-6 px-4 md:px-margin py-4">
        <a href="/dashboard" className="flex items-center gap-2 shrink-0">
          <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" } as React.CSSProperties}>radio_button_checked</span>
          <span className="font-display text-headline-sm font-bold tracking-tight text-primary">Reflex</span>
        </a>

        <div className="hidden md:flex items-center gap-2">
          <SimulatedBadge />
          <TestModeBadge />
          <span className="bg-outline-variant text-on-surface rounded-full px-3 py-1 flex items-center font-mono text-[10px] tracking-widest">MODE: {mode.toUpperCase()}</span>
        </div>

        <nav className="hidden md:flex gap-6 ml-4">
          {[
            ["/dashboard", "Dashboard"],
            ["/approvals", "Approvals"],
            ["/results", "Results"],
            ["/audit", "Audit"],
            ["/ops", "Ops"],
          ].map(([href, label]) => {
            const active = typeof window !== "undefined" && window.location.pathname === href;
            return (
              <a key={href} href={href} className={`font-mono text-label-mono ${active ? "text-primary font-bold border-b-2 border-primary pb-1" : "text-on-surface-variant font-medium hover:text-primary"} transition-colors`}>
                {label}
              </a>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3 md:gap-4">
          <span className={`hidden md:inline-flex items-center gap-1.5 text-[10px] font-mono ${sseConnected ? "text-secondary" : "text-outline"}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sseConnected ? "bg-secondary" : "bg-outline"} ${sseConnected ? "animate-pulse" : ""}`} />
            {sseConnected ? "LIVE" : `connecting${lastEventAt ? ` (${new Date(lastEventAt).toLocaleTimeString()})` : ""}`}
          </span>
          <button
            onClick={() => modeMut.mutate(halted ? "advisory" : "halted")}
            className={`hidden md:inline-flex font-mono text-label-mono border rounded-full px-4 py-1.5 uppercase transition-colors ${halted ? "border-secondary text-secondary hover:bg-secondary-container/20" : "border-on-tertiary-container text-on-tertiary-container hover:bg-error-container"}`}
            aria-live={halted ? "assertive" : "polite"}
          >
            Kill switch
          </button>
          <button
            onClick={() => modeMut.mutate(halted ? "advisory" : "halted")}
            className="md:hidden px-4 py-2 rounded-full border border-error text-error font-mono text-label-mono hover:bg-error/10 transition-colors"
          >
            Kill switch
          </button>
          <a href="/ops" className="text-primary hover:text-primary-container transition-colors" aria-label="Settings">
            <span className="material-symbols-outlined">settings</span>
          </a>
        </div>
      </div>

      {banner.kind === "DEGRADED" && !halted && (
        <div className="border-t border-amber-500/40 bg-amber-500/15 px-4 md:px-margin py-3 text-center text-xs text-amber-800">DEGRADED MODE — LLM unavailable · deterministic fallback active · actions stamped DEGRADED</div>
      )}
      {halted && (
        <div className="border-t border-error/60 bg-error-container px-4 md:px-margin py-3 text-center text-xs font-semibold text-on-error-container">HALTED — kill switch active · scheduled actions cancelled · deliberate re-enable required</div>
      )}
    </div>
  );
}
