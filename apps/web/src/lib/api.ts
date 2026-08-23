/** API client + shared types. Mirrors packages/core/schemas.py (Rules §8.2). */

export type Role = "viewer" | "operator" | "approver" | "admin";
export type Mode = "advisory" | "autonomous" | "degraded" | "halted";

export interface DiagnosisDto {
  canonical_code: string;
  confidence: number;
  method: string;
  rationale: string;
  created_at: string;
}

export interface CandidateDto {
  intervention: string;
  p_recover: number;
  expected_gain_paise: number;
  cost_paise: number;
  annoyance_paise: number;
  ev_paise: number;
  policy_version: string;
}

export interface ActionDto {
  id: string;
  episode_id?: string;
  intervention: string;
  status: string;
  channel: string | null;
  cost_paise: number;
  mode: string;
  policy_version: string;
  guardrail_snapshot: Record<string, unknown>;
  scheduled_for: string | null;
  dispatched_at: string | null;
  message_final: string | null;
  created_at: string;
}

export interface OutcomeDto {
  outcome: string;
  action_id: string | null;
  observed_at: string;
  latency_secs: number | null;
}

export interface EpisodeListItem {
  id: string;
  customer_pseudonym: string;
  amount_paise: number;
  status: string;
  arm: string;
  rail: string;
  actions_used: number;
  opened_at: string;
  closes_at: string;
  top_ev_paise: number | null;
  diagnosis: (DiagnosisDto & { created_at: string }) | null;
}

export interface EpisodeDetail extends EpisodeListItem {
  code_raw: string;
  diagnoses: DiagnosisDto[];
  candidates: CandidateDto[];
  actions: ActionDto[];
  outcomes: OutcomeDto[];
}

export interface LedgerEventDto {
  seq: number;
  episode_id: string;
  action_id: string | null;
  event: Record<string, unknown>;
  prev_hash: string;
  hash: string;
  created_at: string;
}

export interface LiveMetrics {
  failed_today_paise: number;
  recovered_reflex_paise: number;
  recovered_b1_paise: number;
  complaint_rate: number;
  cost_per_100p: number | null;
  episodes_open: number;
  episodes_terminal: number;
  speed: number;
  mode: string;
  llm_outage?: boolean;
  counters: Record<string, number>;
}

export interface ApprovalItem {
  id: string;
  requested_at: string;
  timeout_at: string;
  episode_id: string;
  amount_paise: number;
  pseudonym: string;
  dx_code: string | null;
  intervention: string;
  action_status: string;
  message_final: string | null;
  guardrail_snapshot: Record<string, unknown>;
  top_ev_paise: number | null;
}

export interface EvalMetricRow {
  metric: string;
  value: number | null;
  ci_low: number | null;
  ci_high: number | null;
  seed: number | null;
}

export interface EvalRunDto {
  run_id: string;
  arm: string;
  ablation: string | null;
  preregistered_tag: string | null;
  created_at: string;
  "[SIMULATED]"?: boolean;
  metrics: EvalMetricRow[];
}

const TOKEN_KEY = "reflex_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep status */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const post = <T>(path: string, body?: unknown): Promise<T> =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
