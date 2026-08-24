# REFLEX — Master Project Summary

> Single-source quick reference distilled from the 8 finalized docs (PRD · TechSpec · AppFlow · Design · Schema · ImplementationPlan · Tracker · Rules). Where this summary and the detailed docs disagree, **the detailed docs win**.

> **v1.3 SYNC:** implementation is ~68% effective (28✅/20🟡/7❌/1⚠️ of 56 tasks). **No official evaluation results exist yet** — all % figures herein are design targets [SIMULATED]. Authoritative status: PRD §22 + ImplementationPlan snapshot + Tracker. *(v1.3: AI-4 recall gate shipped, `actions.llm_call_id` provenance FK live, RISK_HELD in mixture, kill-switch drain measured 25.5 ms, error envelope + Idempotency store enforced — see TechSpec §21.)*

---

## 1. Project Identity

| Field | Value |
|---|---|
| **Product** | **Reflex** (renamed from working title "Recover") |
| **One-line pitch** | A bounded, root-cause-diagnosing payment-recovery agent that wins back failed payments and failed mandates with the cheapest intervention most likely to work — measured, audited, and safe by construction. |
| **Track** | Razorpay AI Buildathon — **03 · AI Revenue Recovery** |
| **Category** | Merchant-side fintech automation · agentic revenue operations |
| **Tagline** | *Recover more, annoy less, prove everything.* |
| **Governing principle** | **AI proposes, deterministic code disposes** — the LLM never authors an amount, link, deadline, or authorization |
| **Integration reality** | Razorpay **test mode** `[TEST MODE]`; all channels & customer data `[SIMULATED]`; real channels `[PLANNED]` post-MVP |
| **Status** | Design/docs complete (10 files, 56 tasks defined) · **build ~68% effective** (28✅/20🟡/7❌/1⚠️ — see §19; v1.3 fixes an earlier "build not started" contradiction here) |

---

## 2. Executive Overview

Indian subscription/D2C merchants lose recurring revenue to payment failures (UPI, cards, e-mandates/NACH) and respond with either silence or untargeted blast messaging. Reflex sits merchant-side on top of Razorpay test-mode APIs and closes the loop: **ingest failure → diagnose root cause (rules first, LLM for the ambiguous tail) → rank interventions by expected value → enforce deterministic guardrails → execute via retries/payment links/simulated channels (WhatsApp, SMS, email, Hinglish voice) → observe outcome → adapt policy → stop or escalate**. Every decision lands in a hash-chained action ledger.

Value is proven not asserted: a **pre-registered, reproducible evaluation** (3 arms × 3 seeds × 3,000 episodes, bootstrap CIs, component ablations, one honestly-reported losing cohort). Simulation design targets: **Reflex ~42% value recovery vs ~24% tuned-naive vs ~7% do-nothing, at ~₹3.0 vs ~₹6.9 cost per ₹100 recovered, with <0.5% complaint rate** — always labeled `[SIMULATED]`.

The strategic wedge: Razorpay's own shipped recovery tooling is publicly described at one-line depth; the buildathon bar (measured ₹ recovered, stopping rules, audit trail) is exactly the rigor gap Reflex fills. **Depth, rigor, and localization — not a new category.**

---

## 3. Problem & Why Now

| Dimension | Detail |
|---|---|
| **Exact problem** | Failed payments/mandates leak revenue; recovery is manual, root-cause-blind, unmeasured, and often customer-hostile |
| **Insufficiency of status quo** | Gateway retries re-attempt the same rail; bulk SMS ignores cause & timing; manual ops don't scale or audit; global dunning tools (Stripe Smart Retries, ChurnBuster, Recurly, Baremetrics Recover) are card-rail + English-first `[ASSUMPTION — verify before citing]` |
| **Financial stakes** | Recovered revenue ≈ 100% margin; spam cost = complaints, DND/compliance exposure, goodwill churn |
| **Why now** | (1) LLM reasoning cheap enough for messy Indian decline strings + Hinglish generation; (2) UPI AutoPay/eNACH mandate failures are mainstream `[VERIFIED — NPCI products]`; (3) agentic tool-calling/structured-output patterns mature; (4) Track 03's bar demands exactly this rigor |

---

## 4. Objectives

| # | Goal | Target |
|---|---|---|
| G1 | Recover more than naive retry | ≥ +15 pts value-weighted recovery vs B1 |
| G2 | Recover cheaper | ≤ ₹3.5 per ₹100 recovered (vs B1 ~₹6.9) |
| G3 | Recover without annoying | < 0.5% complaint rate (vs B1 ~1.9%) |
| G4 | Safe by construction | 0 guardrail violations; 100% actions ledgered |
| G5 | Provable | Pre-registered eval; one-command reproduction |
| G6 | Survive failures | Degraded-mode recovery ≥ 80% of full mode |

**Non-goals:** real customer contact · autonomous refunds/cancellations · replacing gateway retries · multi-tenant marketplace · production/live keys · fraud/chargebacks/recon (other tracks).

---

## 5. Core Idea

**Thesis:** most failed-payment revenue doesn't need a better retry button — it needs a **correct diagnosis**. "Insufficient funds" (salary-window timing), "issuer downtime" (retry later/alt rail), "mandate revoked" (re-registration journey), and "card expired" (nudge with link) are *different problems needing different fixes*, in the customer's language and channel, inside hard limits.

```text
Failure event → dedup → episode
  → DIAGNOSE   rules (≥70% of cases) → LLM tail (schema-validated, conf-gated)
  → DECIDE     EV = p_recover × amount − channel_cost − annoyance_penalty
  → GUARD      Shield: deterministic, fail-closed, non-overridable
  → ACT        RP-TM retry/link + [SIMULATED] channels (idempotent dispatch)
  → OBSERVE    outcome window → attribution → policy credit
  → STOP/ESCAPELATE    RECOVERED · EXPIRED(72h) · CAP · LOW_EV · CUSTOMER · APPROVAL_DECLINED · HALTED
  → AUDIT      hash-chained ledger, every step
```

---

## 6. Key Differentiators

1. **Root-cause-aware orchestration** across UPI, cards, NACH/e-mandate lifecycles — India-rail-native, not card-dunning ported.
2. **EV-justified actions, visible inline** — every action shows `EV +₹412 = p 0.34 × ₹1,299 − ₹0.8 − ₹22 · cap 2/4 · quiet-hours clear · policy v2 · Shield PASS`.
3. **Shield as separation of powers** — guardrails are a separate deterministic module; the policy can only *propose*.
4. **Hinglish-first messaging** with post-generation number injection + validator (LLM never authors digits/links).
5. **Honest evaluation architecture** — pre-registered protocol, tuned (never strawman) baseline, ablations, a published cohort where Reflex correctly *declines to act*.
6. **Degraded mode** — LLM outage → deterministic fallback, zero dropped episodes, actions stamped `DEGRADED`.
7. **Hash-chained append-only ledger** with tamper-detection endpoint.
8. **Structural anti-cheat** — agent DB role physically cannot read simulator ground truth (ADR-004).

---

## 7. Target Users

| Persona | Who | Pain | How Reflex helps |
|---|---|---|---|
| **Ananya Mehta** (primary) | Founder/ops, "SipDaily" — chai subscription, 40k customers, UPI AutoPay + cards + COD | ~8–11% monthly debit failures; weekly CSV → agency SMS; zero measurement | Autonomous bounded recovery within hours; per-rupee attribution; kill switch |
| **Rohit Kulkarni** (secondary) | Finance/ops manager | No visibility into automated actions; compliance anxiety | Approval queue, hash-chained ledger, cost ledger, suppression list |
| **Razorpay evaluator** (tertiary) | Judge / pilot engineer | Is this safe, measured, shippable? | Reproducible eval, labeled simulations, failure handling, clean boundaries |

---

## 8. Complete Workflow (episode lifecycle)

**Happy path (sim-time):** webhook (HMAC-verified, deduped) → episode `EPS-1042` created → rules diagnosis `INSUFFICIENT_FUNDS (0.97, RULE)` → Brain enumerates 4 candidates w/ full EV breakdowns persisted → Shield PASS (7 checks in fixed order) → action scheduled to 16:00 (salary-window) → Payment Link via RP-TM (idempotency key) + WhatsApp sim `[SIMULATED]` → message: skeleton → LLM phrasing (no digits) → DB-injects ₹299/link/date → validator → delivery → customer pays 17:22 → outcome attributed to action 1 → episode `RECOVERED` → credit assignment → policy update trigger → SSE counters.

**State machines:**
- **Episode:** `WAITING_DIAGNOSIS → DIAGNOSED → {SCHEDULED | WAITING_APPROVAL} → ACTED → OBSERVING → {RECOVERED | EXPIRED | STOPPED_CAP | STOPPED_LOW_EV | STOPPED_CUSTOMER | ESCALATED | HALTED}` (terminals never reopen; re-fail ⇒ new episode)
- **Action:** `PROPOSED → SHIELD_PASS → SCHEDULED → DISPATCHED → DELIVERED_SIM → OBSERVED → {SUCCEEDED | FAILED}` + `BLOCKED / WAITING_APPROVAL / CANCELLED_HALT / SUPERSEDED / PARKED`

**Human approval gate (blocking):** triggers = value > ₹50,000 · pause/cancel-class · complaint handoff · custom rule → 4h sim timeout ⇒ **auto-decline (fail-closed)**; approve re-runs Shield (state may have changed); decline re-ranks low-risk alternatives.

---

## 9. AI & Agent Role

### AI components

| ID | Component | AI job | Why AI (vs rules) | Eval bar | Failure behavior |
|---|---|---|---|---|---|
| AI-1 | Diagnosis NLU | Canonical root-cause classification of messy decline strings | Same cause surfaces as different issuer strings; lookup can't cover the ~25–30% tail *(distinct concept: the generator's separate 6% "ambiguous tail" data category — v1.2 audit P3-2)* | ≥85% accuracy on 500-case held-out set | conf < 0.6 ⇒ UNKNOWN_AMBIGUOUS ⇒ conservative default; invalid JSON ⇒ 1 retry ⇒ fallback |
| AI-2 | EV policy | Propensity-to-recover scoring (logistic v1 priors → v2 learned) + deterministic EV arithmetic | Sequential decision under uncertainty; rules *are* the baseline we beat | Regret vs oracle; ablation A2 | Model down ⇒ frozen v1; EV<0 ⇒ STOP by design |
| AI-3 | Message generation | Hinglish/English tone-band phrasing around slot skeletons | Empathy + genuine vernacular at scale | Validator 100% digit-free; ablation A3 | Any digit/URL/₹ ⇒ template fallback, diff logged |
| AI-4 | Reply classifier | Intent from simulated replies: PROMISE(date)/REFUSE/COMPLAINT/OPTOUT/PAYING/AMBIGUOUS | Free-text understanding; missed complaint = trust killer | COMPLAIN precision ≥95% | AMBIGUOUS ⇒ non-response default; COMPLAINT also rule-gated |

### Where AI is deliberately NOT used (product-level rule)
EV arithmetic · caps/budgets/quiet hours · scheduling math · retry/link execution · ledger writes · compliance filtering · idempotency. **All deterministic.**

### Agent justification (Episode Agent — genuinely agentic)
Bounded horizon-1 planner (ADR-002) · allowlisted tools (RP-TM order/link, channel sims, ledger/policy/suppression writes) · state (episodes/actions) · memory (episode-, customer-, policy-scoped) · verification (Shield + validator + attribution) · recovery (degraded mode, backoff/park) · escalation (approval queue) · hard stop conditions. Shield, executors, ledger, replay engine are explicitly **not** agents.

---

## 10. System Architecture

Six subsystems (terminology used across all docs):

| Subsystem | Role | Nature |
|---|---|---|
| **Pulse** | Ingestion (webhook + replay), HMAC verify, dedup, episode creation, diagnosis | API + workers |
| **Brain** | EV policy, propensity model, policy versions | Service + model store |
| **Shield** | Deterministic guardrails; no network, no LLM deps (isolation-tested) | Library in dispatch path |
| **Hands** | RP-TM executors + `[SIMULATED]` channel gateways | Workers + adapters |
| **Ledger** | Append-only hash-chained action log + verification API | Service |
| **Proof** | Replay engine, hidden-param outcome simulator, baselines, ablations, eval harness | Separate service/CLI |

```text
Razorpay TM webhooks ─┐
Replay engine [SIM] ──┴─► Ingestion (HMAC, dedup) ─► Redis Streams ─► Diagnosis worker
  ─► EV policy ─► Shield ─► {dispatch | approval queue | BLOCKED}
  ─► Executors (RP-TM + channel sims, idempotent) ─► Ledger (hash chain)
  ─► Outcome worker ─► attribution ─► policy credit ─► terminal state ─► metrics
                                    ▲
            React command center (REST + SSE) ──────┘ live counters/drawers
```

---

## 11. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React 18 + Vite + TS + Tailwind + shadcn/ui + Recharts | Team strength; internal-tool polish ceiling |
| Backend | Python 3.11+ (host/CI floor; 3.12 target) + FastAPI 0.111 | Async, Pydantic boundaries |
| Workers | Redis Streams consumers, partitioned by `payment_id` | Per-episode ordering; simple ops |
| DB | PostgreSQL 16 (schemas: `runtime` / `replay` / `eval`) | JSONB + relational integrity + role-based anti-cheat |
| Cache/queue | Redis 7 | Dedup TTL, rate limits, streams |
| LLM | Hosted OpenAI-compatible API; model `[Decision Required]`; MVP = GPT-4o-mini-class | Structured output; degraded mode covers outage |
| ML | scikit-learn 1.5 logistic regression | Coefficients = explainable EV drawer |
| Auth | JWT (8h) + RBAC (viewer/operator/approver/admin) | Minimal, testable |
| Observability | structlog JSON + trace/action IDs + `/metrics` | Demo-grade, zero-dependency |
| Tests/CI | pytest · Vitest · Playwright · GitHub Actions | Repo-as-evidence |
| Deploy | docker-compose, single VM | Judges run it in minutes |

**Repo layout:** `apps/{api,workers,eval,web}` · `packages/{core,shield,brain,connectors,ledger,prompts}` · `data/{generators,calibration_sources.md,seeds}` · `eval/{PROTOCOL.md,reproduce.sh,results}` · `docs/` · `tests/`.

---

## 12. Data & Simulation Strategy

| Element | Design |
|---|---|
| **Three-schema separation** | `runtime` (agent world) · `replay` (hidden simulator truth) · `eval` (evidence). **Agent DB role cannot `SELECT` `replay.sim_*`** — eliminates "agent peeked" accusation |
| **Synthetic universe** | 3,000 customers: LTV bands, salary days (1–7 cluster), 70% Hinglish, 3% DND; failure-code mixture (INSUFFICIENT_FUNDS 32%, AUTH_DECLINED_SOFT 14%, ISSUER_DOWNTIME 12%, MANDATE_REVOKED 9%, EXPIRED_CARD 7%, AUTH_DECLINED_HARD 6%, MANDATE_LIMIT_BREACH 5%, CUSTOMER_INITIATED 4%, INVALID_VPA 3%, RISK_HELD 2%, ambiguous tail 6%; amended per Protocol Amendment 1, tag eval-preregistered-v1.1-risk-held-amendment) with 5–8 issuer-string paraphrases per code |
| **Hidden simulator params** | Per-customer `p_respond_by_channel`, annoyance thresholds, intents (would_pay_if 55% / wait_pay 30% / never_pay 15%) — calibrated to public patterns via `data/calibration_sources.md`; **targets never hard-coded into the agent** |
| **Seeds** | Eval {42, 1337, 2025}; demo slice `demo-7` → exactly **214 episodes / ₹2,41,000**, incl. one ₹48,000 approval case + one pre-seeded complaint trajectory |
| **Reply corpus** | 300 labeled replies (Hinglish complaints/promises/opt-outs) + 40 prompt-injection attempts |
| **PII** | None real: pseudonyms (`C-4821`), masked VPAs; PII scrubber + no-PII-in-prompt CI test |

---

## 13. Key Features (grouped)

| Cluster | Features | Acceptance essence |
|---|---|---|
| Ingestion & episodes | FR-001–003: HMAC-verified webhook ingestion, replay engine, 72h episode lifecycle | 1,000-event storm → 214 episodes, 0 dupes |
| Diagnosis | FR-004–005: rules engine (≥70% coverage, p95 <100ms) + LLM tail (conf-gated) | ≥85% holdout accuracy; schema-valid 100% |
| Decision | FR-006–007: EV policy w/ persisted 4-term breakdown; Shield 7-check guardrails | 0 violations under adversarial suite; negative-EV STOP shown with math |
| Execution & messaging | FR-008–009: RP-TM retry/link + channel sims; Hinglish tone-band generation w/ validator | Idempotent dispatch; validator rejects 100% digit-bearing spans |
| Command center & audit | FR-010, **FR-011**, 012–014, 018: command-center dashboard w/ live counters+stream+drawers *(restored by v1.2 audit P2-9)*; hash-chained ledger + audit drawer; approval queue; kill switch & modes; degraded mode; suppression/complaint handling *(v1.3: FR-018 elevated to Must Have/P0 — recall gate green)* | Counter delta <2s @×100; rationale ≤2 clicks; chain tamper detected; kill ≤1s drain *(measured: 25.5 ms/500 actions)*; zero post-complaint contact |
| Outcomes & learning | FR-015: watch windows, attribution, policy credit | 100% episodes reach terminal state |
| Evaluation & demo | FR-016–017, 019–020: B0/B1 baselines *(restored to Must Have by v1.2 audit P0-1 — this is the FR-016 restoration referenced in PRD §12; distinct from the FR-011 note above)*, pre-registered eval harness + ablations, metrics views, demo/failure-injection controls | One-command repro; demo ≤10 min end-to-end |

---

## 14. Security & Safety

**Shield guardrails (deterministic, fail-closed, non-overridable):** 4 actions/episode · 2 contacts/customer/day · ₹5,000/day budget · quiet hours 21:00–09:00 IST · suppression/DND list · value > ₹50,000 ⇒ approval · pause/cancel-class ⇒ approval always · kill switch.

**Financial safety:** no irreversible money movement in MVP (orders/links/simulated messages only) · DB-level idempotency (unique `idempotency_key`) · ledger-first invariant (can't ledger ⇒ can't dispatch) · approval timeout auto-declines · Action Preview Card (WHAT/WHY/IMPACT/RISK/GATE/APPROVAL/REVERSIBILITY) on every human-facing action.

**AI safety:** schema-validated outputs (1 retry → fallback) · `<data>`-wrapped untrusted text + injection corpus in CI · confidence gating · LLM calls fully logged (hash, redacted input, validity, cost) · tool allowlist.

**Security:** HMAC webhook verify · server-side RBAC (matrix-tested) · secrets via env + gitleaks CI · rate limits + idempotency on POSTs · no PII in prompts/logs · append-only ledger grants · agent/replay role separation.

**Demo integrity (zero tolerance):** never fake metrics/API responses/results; every simulated datum labeled `[SIMULATED]`; failures demoed as real injections; `docs/limitations.md` lists what Reflex does NOT do + one losing cohort.

---

## 15. Evaluation Methodology & Metrics

**Protocol (pre-registered, git tag `eval-preregistered-v1` BEFORE first results):** N=3,000 episodes × seeds {42, 1337, 2025} × 3 arms · bootstrap 1,000 resamples, 95% CI · identical batch across arms · `./reproduce.sh` from clean clone (<15 min) · results committed as JSON + tables.

**Primary KPI:** incremental value-weighted recovery rate & incremental ₹ recovered vs tuned naive baseline (B1).

**Arms (simulation design targets — actuals come from runs, always `[SIMULATED]`):**

| Arm | Recovery rate | Cost / ₹100 recovered | Complaint rate | Median TTR |
|---|---|---|---|---|
| B0 — do nothing | ~7% | ₹0 | ~0% | — (organic) |
| B1 — tuned naive (same-rail retry ×3 + blast SMS ×2) | ~24% | ~₹6.9 | ~1.9% | ~26h |
| **Reflex** | **~42%** | **~₹3.0** | **<0.5%** | **~9h** |

**Secondary KPIs:** contacts/recovery · escalation precision · p95 decision latency (rules <1.5s / LLM <6s) · degraded-mode delta · learning-curve slope (v1→v2) · ablation deltas.

---

## 16. Major Experiments

| ID | Ablation | What it proves |
|---|---|---|
| A1 | Rules-only diagnosis (LLM off) | **Core gate** — value of AI-1 on the ambiguous tail |
| A2 | Fixed-priority policy (EV off) | **The AI-necessity proof** — rules-policy is the baseline |
| A3 | Static templates (personalization off) | Value of AI-3 generation |
| A4 | No timing optimization | Value of salary-window/hour scheduling |

Plus: **losing cohort** — low-value ephemeral failures where Reflex correctly declines to act (contact cost > EV) while naive wastes spend *(threshold = amount < 15,000 paise i.e. ₹150, pinned in eval/PROTOCOL.md §2 — v1.2 audit P3-3 source added)*; AI suite gates (dx ≥85%, validator 100%, COMPLAIN precision ≥95%, injection corpus 100% safe — CI-blocking); load test (5k-event burst, 40% dupes, zero dup episodes, p95 <800ms).

---

## 17. MVP Scope & Cut Line

**Must have:** everything FR-001–015/017/019–020 — ingestion, episodes, rules+LLM diagnosis, EV policy, Shield, executors + channel sims, message validator, ledger, dashboard w/ drawers, approvals, kill switch, degraded mode, outcomes/attribution, baselines, eval harness, metrics, demo controls.

**Should have:** full ablation suite (min A1+A2), voice-call sim, policy v2 learning, learning curve. **Nice:** mandate re-registration journey, B2B invoice flavor, policy profiles.

**Cut order if time runs out:** (1) voice sim → (2) policy v2 → (3) ablations A3/A4 → (4) onboarding flow → (5) `/ops` niceties.
**NEVER cut:** Shield · ledger · B0/B1 comparison · degraded mode · injection demos · `[SIMULATED]` labeling · reproduce.sh · pre-registration tag.

---

## 18. Implementation Roadmap

**4 working days · 3 engineers** (A: Data/Sim/AI+Eval · B: Backend/Agent+Security · C: Frontend/Design) · 52 core tasks + 4 audit-remediation tasks (053–056) = **56 total** · 10 phases:

| Phase | Day | Essence |
|---|---|---|
| 0 Setup | 0 | Repo, compose, Alembic V1 + role grants, FE scaffold, **pre-register eval protocol (TASK-005, critical)** |
| 1 Foundation | 0.5–1 | Core domain/state machine, ledger, ingestion, streams/workers, RP-TM client, auth/RBAC |
| 2 Core product | 1–1.5 | Rules diagnosis, Shield, dispatch path, channel sims, outcome worker, dashboard+SSE |
| 3 AI | 1.5–2 | Prompts, LLM tail, message gen + validator, reply classifier, PII scrub |
| 4 Agentic workflow | 2–2.5 | EV policy, decision integration, approvals, kill switch/modes, degraded mode, injections |
| 5 Eval | 2.5–3 | **Replay engine (TASK-031, critical)**, B1 tuning, runner+ablations, reproduce.sh, results UI |
| 6 Security | 3 | RBAC/rate-limit tests, security suite, ledger grants |
| 7 UI polish | 3 (parallel) | Design system, drawers, Action Preview Card, a11y, `/audit` + `/ops` |
| 8 Demo prep | 3.5 | Demo slice seed, 3× rehearsals + outage drill, video/README, backup recording |
| 9 Final QA | 4 | Full regression, 10 acceptance criteria, 8-doc consistency, submission |

**Critical path:** TASK-003 → 006 → 008 → 009 → 012/014 → 024/025 → **031 → 033 → 034** → 047. Schedule-killers: replay engine & eval runs — start 031 design Day 0.5.

---

## 19. Current Status & Open Items

| Item | Status |
|---|---|
| 10 design docs | ✅ Finalized, cross-checked (v1.3 audit sync applied to all) |
| Build | 🟡 **~68% effective** — 28✅ / 20🟡 / 7❌ / 1⚠️ of 56 tasks *(v1.3 fix: §1 and this row previously contradicted — "69%" here vs "not started" below; both now reflect the Tracker)* |
| Official eval run | ⚠️ BLOCKED by host Docker issue — **v1.3 root cause: Windows excluded-port ranges cover 5432**; harness re-proven against healthy containers; workaround documented (TechSpec §21.2) |
| Eval protocol tag | ✅ `eval-preregistered-v1` predates all results; amendment tag owed before official RISK_HELD run (TASK-053) |
| Razorpay subscriptions "charge now" endpoint | `[TBD — verify existence/naming]`; fallback = new order + link (retry-honesty note in PRD §22.8) |
| LLM model choice | `[Decision Required]` (MVP assumption: GPT-4o-mini-class); **a key MUST be configured for the live demo or AI-1/AI-3 fall back to rules/templates** |
| External claims (Razorpay Agent Studio details, competitor stats, churn figures) | `[ASSUMPTION]` — run the 20-min verification protocol **before** citing in pitch/video |
| README / LICENSE / CONTRIBUTING | 🟡 **README.md + CONTRIBUTING.md + MANUAL_STEPS.md created (v1.3)**; LICENSE pending from owner |
| Milestones ahead | `eval-preregistered-v1` (done) → `eval-protocol-amendment-risk-held` → `v1.0-submission` |

---

## 20. Risks & Limitations

| Risk | Severity | Mitigation |
|---|---|---|
| **Simulator credibility** (top risk — "is the win rigged?") | High | Calibration doc w/ cited public sources · pre-registration · generously tuned B1 · published losing cohort · ADR-007 structural anti-cheat |
| Reminder-bot clones in Track 03 | Medium | Win on policy quality + eval rigor + safety engineering — not novelty |
| Razorpay product-claim error in pitch | High if unverified | Verification protocol; soften/cut unverified specifics |
| LLM dependency | Medium | Rules-first design; degraded mode; cache; system runs LLM-absent |
| Demo-day failure | Medium | Real injections rehearsed; backup video + ≤2min DB restore; honest-failure brand |
| Scale ceiling | Low (demo scope) | Documented ~10⁴-episode limit in `docs/limitations.md` |
| Cold-start in real deployment | Accepted | Out of MVP; future priors from aggregate stats `[PLANNED]` |

---

## 21. Competitive Positioning

| Alternative | Their position | Reflex's gap-exploit |
|---|---|---|
| Global dunning SaaS (Stripe Smart Retries, ChurnBuster, Recurly, Baremetrics Recover) `[VERIFIED products; ASSUMPTION gap]` | Card rails, English-first | UPI/mandate failure modes, salary-cycle timing, Hinglish-first, EV with annoyance cost |
| Gateway-level retries | Same-rail re-attempts | Merchant-side orchestration *above* the gateway: channel/timing/message/cause + measurement — complementary |
| Razorpay's own shipped agents `[ASSUMPTION — verify]` | One-line product depth | The measured, audited, root-cause-specific layer a blurb doesn't show |
| Chargebee / Juspay (must acknowledge) | India-adjacent billing / routing orchestration | Positioned as merchant-side recovery layer, not billing platform or gateway router |

---

## 22. Demo Flow

**Setup:** `make demo` · slice 214 eps / ₹2,41,000 · seed `demo-7` · ×100 speed · naive arm running in parallel.

| Time | Screen | Beat |
|---|---|---|
| 0:00–0:30 | Red counters `FAILED ₹2,41,000 · RECOVERED ₹0 · NAIVE ~₹57,800` | Problem lands emotionally |
| 0:30–1:00 | 3-number margin slide | Recovered ₹ ≈ 100% margin; India needed root-cause thinking |
| 1:00–2:30 | **Live:** toggle ON → diagnosis chips → EV drawer on ₹299 episode → approve ₹48,000 case live → green counter climbs past ₹1,01,200 | "Every action shows its math and its guardrail state" |
| ~2:10 | **Flip LLM-outage switch** → amber DEGRADED banner → stream continues, actions stamped | "It never stops, and it never lies about what it did" |
| 2:30–3:30 | Architecture + AI/not-AI table | "AI decides *what* and *when*; deterministic code decides *whether it's allowed*" |
| 3:30–4:15 | `/results`: 3-arm table w/ CIs + ablation bars `[SIMULATED]` | Pre-registered, one command, reproducible |
| 4:15–4:45 | Failure table + `/audit` chain verify + `/approvals` | Caps, quiet hours, kill switch, human gates |
| 4:45–5:00 | Razorpay pilot frame | "Ten subscription merchants in a week" |

**60-second WOW:** red counter → toggle → chips → EV drawer + approval → counters pass baseline → outage switch → still recovering. Demoable injections: `llm_outage` · `webhook_storm` (1,000→214 dedup shown live) · `complaint` (auto-suppress + human handoff).

---

## 23. Key Design Decisions (ADRs)

| ADR | Decision | Rationale |
|---|---|---|
| 001 | Modular monolith + workers, not microservices | Demo ops cost > benefit; import-lint enforces boundaries |
| 002 | Horizon-1 EV policy, not open-ended planner | Money actions need auditable bounded decisions; observe→re-plan recovers adaptivity |
| 003 | Rules-first diagnosis, LLM only on tail | Cost, latency, honesty ("LLM touched only ~25%") |
| 004 | Postgres schema + role separation (agent can't read simulator truth) | Structural anti-cheat |
| 005 | Logistic regression over GBM | Coefficients explainable in the EV drawer |
| 006 | SSE over WebSockets | Unidirectional live updates; simpler reconnects |
| 007 | Simulation-honesty architecture | Pre-registration, hidden params, tuned baseline, losing cohort — rigging made structurally difficult, then labeled |

---

## 24. One-Page Understanding

**REFLEX** *(Razorpay AI Buildathon · Track 03 — AI Revenue Recovery)* is a merchant-side autonomous recovery agent for failed payments and failed UPI/card/mandate collections, built on Razorpay test-mode APIs with fully simulated channels and customers.

**The loop:** diagnose the root cause (rules first, LLM for messy tail) → score every intervention by expected value (propensity × amount − cost − annoyance) → enforce deterministic guardrails (caps, budget, quiet hours, approvals, kill switch) → execute idempotently → observe, attribute, adapt → stop or escalate → hash-chain every decision.

**The numbers it must produce** (pre-registered, reproducible, `[SIMULATED]`): **~42% recovery vs ~24% naive vs ~7% organic · ~₹3.0 vs ~₹6.9 per ₹100 recovered · <0.5% complaints · ~9h vs ~26h time-to-recover** — with ablations proving which AI component buys which points, and one cohort where the system correctly refuses to act.

**The identity:** *AI proposes, deterministic code disposes.* The LLM never touches a number; Shield never consults a model; the ledger never forgets.

**Why it wins:** the only concept simultaneously top-tier on the track's literal bar (measured ₹, escalation, stopping rules, audit trail), demo impact (60-second counter + live outage survival), Razorpay fit (raises effective payment success rate on their own rails, pilot-ready), and hiring signal (pre-registration, safety-as-product, honest limitations).

**Why Razorpay cares:** their shipped recovery tooling is one line deep; Reflex is the measured, audited, India-rail-native layer above it — recovered revenue is pure merchant margin and pure platform stickiness.

**Biggest risk:** simulator credibility — neutralized by calibration citations, pre-registration, a tuned baseline, and published loss cases.

**Current state:** design complete (10 docs · 56 tasks · 4-day plan · 3 engineers); build ~68% effective — the critical path runs through TASK-033 (official eval, environment-unblocked workaround documented); README/LICENSE templates pending.

---

## Appendix — Consistency Constants (quick lookup)

| Constant | Value |
|---|---|
| Guardrails | 4 actions/episode · 2 contacts/customer/day · ₹5,000/day · 21:00–09:00 IST · >₹50,000 approval · 72h episode · 4h approval timeout |
| Eval | N=3,000 · seeds {42, 1337, 2025} · 3 arms · 4 ablations · 1,000 bootstrap · 95% CI |
| Demo | 214 episodes · ₹2,41,000 · seed `demo-7` · ₹48,000 approval case · ×100 speed |
| AI gates | dx ≥85% · validator 100% · COMPLAIN ≥95% precision AND ≥90% recall · injection corpus 100% safe |
| Perf | rules dx <100ms · LLM dx <6s · decision <1.5s · eval <10min · reproduce <15min · SSE <2s |
| Modes / roles | advisory·autonomous·degraded·halted / viewer·operator·approver·admin |
| Routes | `/login /onboarding /dashboard /approvals /results /audit /ops` |
| Subsystems | Pulse · Brain · Shield · Hands · Ledger · Proof |
| Tags | `eval-preregistered-v1` → `v1.0-submission` |
| Labels | `[VERIFIED] [ASSUMPTION] [SIMULATED] [PLANNED] [TBD] [Decision Required]` |
