import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ApprovalItem } from "../lib/api";
import { api, post, getRole, roleRankOf } from "../lib/api";
import { ControlBar } from "../components/ControlBar";
import { BottomNav } from "../components/BottomNav";
import { useStream } from "../hooks/useStream";
import { useTitle } from "../hooks/useTitle";
import { ActionPreviewCard } from "../components/ActionPreviewCard";
import { Chip, SimulatedBadge } from "../components/Chips";
import { formatINR, asPaise } from "../lib/format";

/** Human approval queue (AppFlow §10) — fail-closed 4h timeout auto-declines. */
export default function Approvals() {
  useTitle("Approvals — Reflex");
  useStream();
  const qc = useQueryClient();
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [decideErr, setDecideErr] = useState<string | null>(null);
  const canDecide = (roleRankOf(getRole()) ?? -1) >= 2; // approver or admin
  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<{ items: ApprovalItem[] }>("/api/approvals"),
    refetchInterval: 60000,
    // Don't even ask the API when the session role can't decide — the request
    // would 403 and the error card would read as a broken page.
    enabled: canDecide,
  });

  const decide = useMutation({
    mutationFn: (v: { id: string; decision: "approve" | "decline" }) =>
      post(`/api/approvals/${v.id}/decide`, { decision: v.decision, reason: reasons[v.id] || undefined }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      setDecideErr(null);
    },
    onError: (e) => setDecideErr(e instanceof Error ? e.message : "decision failed"),
  });

  return (
    <div className="min-h-screen bg-background text-on-surface">
      <ControlBar />
      <main className="mx-auto max-w-[1100px] px-4 md:px-24 pb-48">
        <h1 className="mt-8 md:mt-32 font-display text-headline-md text-primary">Approvals — human gate</h1>
        <p className="mt-4 font-mono text-label-mono text-on-surface-variant">Triggers: value &gt; ₹50,000 · mandate-class action · complaint handoff. Timeout ⇒ auto-decline (fail-closed).</p>

        {!canDecide && (
          <div className="mt-12 rounded-xl border border-dashed border-outline-variant bg-surface-container-lowest p-8 text-center text-sm text-on-surface-variant">
            This queue is an approver/admin-only human gate. Your session is a viewer/operator role — nothing is missing; the dashboard and results continue to work.
          </div>
        )}

        {canDecide && !q.isLoading && q.isError && (
          <div className="mt-12 rounded-xl border border-error/40 bg-error-container p-8 text-sm text-on-error-container">
            {q.error instanceof Error ? q.error.message : "Could not load the approvals queue. Try again later."}
          </div>
        )}

        {decideErr && (
          <p className="mt-4 rounded-lg border border-error/40 bg-error-container px-4 py-2 text-xs text-on-error-container">
            {decideErr} <button onClick={() => setDecideErr(null)} className="ml-2 text-on-error-container">✕</button>
          </p>
        )}

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
                value={reasons[a.id] ?? ""}
                onChange={(e) => setReasons((r) => ({ ...r, [a.id]: e.target.value }))}
                className="mt-12 w-full rounded-lg border border-outline-variant bg-surface-container px-12 py-8 text-sm outline-none focus:border-primary"
              />
              {canDecide ? (
                <div className="mt-12 flex gap-12">
                  <button
                    onClick={() => decide.mutate({ id: a.id, decision: "approve" })}
                    disabled={decide.isPending}
                    className="rounded-btn bg-primary px-24 py-8 text-sm font-semibold text-on-primary hover:opacity-90 disabled:opacity-50"
                  >
                    Approve → dispatch (Shield re-checks)
                  </button>
                  <button
                    onClick={() => decide.mutate({ id: a.id, decision: "decline" })}
                    disabled={decide.isPending}
                    className="rounded-btn border border-error/60 px-24 py-8 text-sm font-semibold text-error hover:bg-error/10 disabled:opacity-50"
                  >
                    Decline — stop branch
                  </button>
                </div>
              ) : (
                <p className="mt-12 text-xs text-on-surface-variant">approver or admin role required to decide — this queue is a human gate.</p>
              )}
            </li>
          ))}
        </ul>
      </main>
      <BottomNav />
    </div>
  );
}

function Countdown({ until }: { until: string }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const secs = Math.max(0, Math.round((new Date(until).getTime() - Date.now()) / 1000));
  const h = Math.floor(secs / 3600);
  const mnt = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return (
    <span className={secs < 600 ? "text-error" : "text-tertiary-container"} title="sim-time countdown">
      ⏳ {h}h {mnt}m {s}s to auto-decline
    </span>
  );
}
