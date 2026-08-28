import { Link, useLocation } from "react-router-dom";
import { getRole, roleRankOf } from "../lib/api";

/** Mobile bottom nav (desktop uses the ControlBar links). */
export function BottomNav() {
  const { pathname } = useLocation();
  const canSeeApprovals = (roleRankOf(getRole()) ?? -1) >= 2; // approver or admin
  const items: [string, string, string][] = [
    ["/dashboard", "dashboard", "Dashboard"],
    ...(canSeeApprovals ? [["/approvals", "fact_check", "Approvals"] as [string, string, string]] : []),
    ["/results", "analytics", "Results"],
    ["/audit", "receipt_long", "Audit"],
    ["/ops", "settings", "Ops"],
  ];
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-between border-t border-surface-container-high bg-background px-6 py-2 md:hidden">
      {items.map(([to, icon, label]) => (
        <Link
          key={to}
          to={to}
          className={`flex flex-col items-center gap-1 ${pathname === to ? "font-bold text-primary" : "text-on-surface-variant"}`}
        >
          <span className="material-symbols-outlined">{icon}</span>
          <span className="font-mono text-[10px]">{label}</span>
        </Link>
      ))}
    </nav>
  );
}
