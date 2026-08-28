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
  merchant_name?: string | null;
  contacts_today?: number;
  contacts_per_day?: number;
  quiet_hours?: string;
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

const API_BASE = ((import.meta.env.VITE_REFLEX_API as string | undefined) || (import.meta.env.VITE_API_URL as string | undefined) || "").replace(/\/$/, "");
function withBase(path: string): string {
  if (!API_BASE) return path;
  if (path.startsWith("/api") || path.startsWith("/webhooks") || path.startsWith("/healthz") || path.startsWith("/metrics")) {
    return `${API_BASE}${path}`;
  }
  return path;
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

function decodeJwt(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, "=")));
  } catch {
    return null;
  }
}

/** Role from the JWT payload (also returned by /api/auth/login). */
export function getRole(): Role | null {
  const t = getToken();
  if (!t) return null;
  const role = decodeJwt(t)?.["role"];
  return typeof role === "string" ? (role as Role) : null;
}

/** True when the JWT `exp` claim has passed. */
export function isTokenExpired(): boolean {
  const t = getToken();
  if (!t) return false;
  const exp = decodeJwt(t)?.["exp"];
  return typeof exp === "number" && exp * 1000 <= Date.now();
}

/** Role rank for UI gating — mirrors packages/core/enums ROLE_ORDER. */
export function roleRankOf(role: Role | null): number {
  return role === "viewer" ? 0 : role === "operator" ? 1 : role === "approver" ? 2 : role === "admin" ? 3 : -1;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const url = withBase(path);
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch {
    // fetch only rejects on transport-level failures (DNS, CORS, connection
    // reset by a throttling proxy). The host's Cloudflare edge rate-limits a
    // burst by IP — the browser sees "Failed to fetch" — and it self-clears.
    throw new NetworkError("API unreachable (often a momentary rate-limit) — retrying automatically");
  }
  if (!res.ok) {
    // Expired/invalid session: drop the token and bounce to login (but never
    // while the login page itself is trying, or bad creds would redirect-loop).
    if (res.status === 401 && getToken() && !window.location.pathname.startsWith("/login")) {
      clearToken();
      window.location.assign("/login");
    }
    if (res.status === 429) {
      throw new ApiError(429, "rate-limited — retrying automatically in a moment");
    }
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

/** Download a file endpoint (CSV/JSON export) with the Authorization header —
 *  plain <a href> links can't carry the JWT and would 401. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(withBase(path), { headers });
  if (!res.ok) throw new ApiError(res.status, `export failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
