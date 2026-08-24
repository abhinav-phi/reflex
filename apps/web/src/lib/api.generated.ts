// GENERATED from packages/core/schemas.py — do not hand-edit (Rules §8.2).

export interface ApiError {
  error: string;
}

export interface RazorpayWebhookPayload {
  event: string;
  payload: string;
}

export interface NormalizedFailureEvent {
  provider_event_id: string;
  source: string;
  rail: string;
  code_raw: string;
  amount_paise: number;
  occurred_at: string;
}

export interface WebhookAck {
  accepted: boolean;
  duplicate?: boolean;
  episode_id?: string;
}

export interface ReplayStartRequest {
  n?: number;
  seed?: string;
  arm?: string;
  speed?: number;
  demo?: boolean;
}

export interface ModeChangeRequest {
  mode: string;
  reason?: string;
}

export interface ApprovalDecisionRequest {
  decision: string;
  reason?: string;
}

export interface EvalRunRequest {
  config?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface GuardrailSettingsUpdate {
  caps_per_episode?: number;
  contacts_per_day?: number;
  quiet_hours?: string;
  budget_paise_daily?: number;
  approval_threshold_paise?: number;
}

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
  episode_id: string;
  intervention: string;
  status: string;
  channel: string;
  cost_paise: number;
  mode: string;
  policy_version: string;
  guardrail_snapshot: string;
  scheduled_for: string;
  dispatched_at: string;
  message_final: string;
  created_at: string;
}

export interface OutcomeDto {
  outcome: string;
  action_id: string;
  observed_at: string;
  latency_secs: number;
}

export interface EpisodeDto {
  id: string;
  customer_pseudonym: string;
  amount_paise: number;
  status: string;
  arm: string;
  rail: string;
  actions_used: number;
  opened_at: string;
  closes_at: string;
  diagnosis?: unknown;
  candidates?: unknown[];
  actions?: unknown[];
  outcomes?: unknown[];
}

export interface LedgerEventDto {
  seq: number;
  episode_id: string;
  action_id: string;
  event: string;
  prev_hash: string;
  hash: string;
  created_at: string;
}

export interface LedgerVerifyResponse {
  valid: boolean;
  first_bad_seq?: number;
  checked: number;
}

export interface LiveMetrics {
  failed_today_paise: number;
  recovered_reflex_paise: number;
  recovered_b1_paise: number;
  complaint_rate: number;
  cost_per_100p: number;
  episodes_open: number;
  episodes_terminal: number;
  speed: number;
  mode: string;
}

export interface CountersSnapshot {
  events_ingested: number;
  duplicates_collapsed: number;
  episodes_created: number;
  dx_rule: number;
  dx_llm: number;
  shield_pass: number;
  shield_block: number;
  shield_approval: number;
  dispatched: number;
  recovered: number;
}
