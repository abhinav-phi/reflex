import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ApprovalItem } from "../lib/api";
import { api, post } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { useStream } from "../hooks/useStream";
import { ActionPreviewCard } from "../components/ActionPreviewCard";
import { Chip, SimulatedBadge } from "../components/Chips";
import { formatINR, asPaise } from "../lib/format";

/** Human approval queue (AppFlow §10) — fail-closed 4h timeout auto-declines. */
export default function Approvals() {
  useStream();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<{ items: ApprovalItem[] }>("/api/approvals"),
    refetchInterval: 3000,
  });

  const decide = useMutation({
    mutationFn: (v: { id: string; decision: "approve" | "decline" }) =>
      post(`/api/approvals/${v.id}/decide`, { decision: v.decision, reason }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["approvals"] }),
  });

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[1100px] px-4 md:px-24 pb-48">
        <h1 className="mt-8 md:mt-32 font-display text-headline-md text-primary">Approvals — human gate</h1>
        <p className="mt-4 font-mono text-label-mono text-on-surface-variant">Triggers: value &gt; ₹50,000 · mandate-class action · complaint handoff. Timeout ⇒ auto-decline (fail-closed).</p>

        {q.data && q.data.items.length === 0 && (
          <div className="mt-12 md:mt-24 rounded-xl border border-dashed border-outline-variant p-12 md:p-48 text-center text-sm text-on-surface-variant bg-surface-container-lowest warm-shadow">Queue is clear — nothing is waiting on a human.</div>
        )}

        <ul className="mt-12 md:mt-24 space-y-6 md:space-y-16">
          {(q.data?.items ?? []).map((a) => (
            <li key={a.id} className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 md:p-6 warm-shadow">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-lg font-bold tabular-nums">{formatINR(asPaise(a.amount_paise))}</span>
                  <span className="ml-12 font-mono text-xs text-slate-500">{a.episode_id.slice(0, 8)}</span>
                  <Chip tone="slate">{a.pseudonym}</Chip>
                </div>
                <div className="text-right text-xs">
                  <Countdown until={a.timeout_at} />
                  <div className="mt-4"><SimulatedBadge /></div>
                </div>
              </div>

              <ActionPreviewCard
                what={`${a.intervention} · ${a.action_status}`}
                why={a.dx_code ?? "—"}
                impact={`recovery ${formatINR(asPaise(a.amount_paise))}${
                  a.top_ev_paise != null ? ` · EV ${formatINR(asPaise(a.top_ev_paise))}` : ""
                }`}
                risk={
                  a.guardrail_snapshot
                    ? `contacts ${String((a.guardrail_snapshot as Record<string, unknown>)["contacts_today"] ?? "—")}`
                    : undefined
                }
                gate={`Shield ${String((a.guardrail_snapshot as Record<string, unknown>)["outcome_reason"] ?? "—")}`}
                approval="required — this card gates the action"
                message={a.message_final}
              />

              <input
                placeholder="reason (recorded in the ledger)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="mt-12 w-full rounded-btn border border-cmd-border bg-black/30 px-12 py-8 text-sm outline-none focus:border-primary"
              />
              <div className="mt-12 flex gap-12">
                <button
                  onClick={() => decide.mutate({ id: a.id, decision: "approve" })}
                  className="rounded-btn bg-primary px-24 py-8 text-sm font-semibold hover:bg-primary-hover"
                >
                  Approve → dispatch (Shield re-checks)
                </button>
                <button
                  onClick={() => decide.mutate({ id: a.id, decision: "decline" })}
                  className="rounded-btn border border-red-500/70 px-24 py-8 text-sm font-semibold text-red-300 hover:bg-red-600/20"
                >
                  Decline — stop branch
                </button>
              </div>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}

function Countdown({ until }: { until: string }) {
  const secs = Math.max(0, Math.round((new Date(until).getTime() - Date.now()) / 1000));
  const h = Math.floor(secs / 3600);
  const mnt = Math.floor((secs % 3600) / 60);
  return (
    <span className={secs < 600 ? "text-red-400" : "text-amber-300"} title="sim-time countdown">
      ⏳ {h}h {mnt}m to auto-decline
    </span>
  );
}
