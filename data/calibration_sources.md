# Calibration Sources — Reflex Simulator Constants

Every simulator constant, its value, and provenance. Labels:
`[CITED-PUBLIC]` = grounded in a public product/pattern (cite before pitch), `[ASSUMPTION]` =
engineering choice consistent with public patterns but not directly sourced — re-verify pre-pilot.
Constants are frozen by `eval/PROTOCOL.md` tag `eval-preregistered-v1`. **None of these values are
visible to agent code paths** (ADR-004); Brain v1 priors below are deliberately coarser
literature-level numbers, not simulator internals.

## 1. Customer population (`data/generators`, Schema §13)

| Constant | Value | Provenance |
|---|---|---|
| Population | 3,000 profiles | PRD §13 (demo merchant ~40k; 3k for eval scale) `[ASSUMPTION]` |
| LTV band mix | low 30% / mid 50% / high 20% | Subscription spend dispersion `[ASSUMPTION]` |
| Salary day distribution | 70% clustered days 1–7, else uniform 8–28 | Indian monthly salary cycles cluster at month start `[CITED-PUBLIC: common payroll practice]` |
| Language pref | 70% hinglish / 30% en | India vernacular-content consumption skew `[ASSUMPTION]` |
| DND share | 3% | Registry-style suppression base rate `[ASSUMPTION]` |

## 2. Failure mixture & amounts (Schema §13)

| Canonical code | Share |
|---|---|
| INSUFFICIENT_FUNDS | 32% |
| AUTH_DECLINED_SOFT | 14% |
| ISSUER_DOWNTIME | 12% |
| MANDATE_REVOKED | 9% |
| EXPIRED_CARD | 7% |
| AUTH_DECLINED_HARD | 6% |
| MANDATE_LIMIT_BREACH | 5% |
| CUSTOMER_INITIATED | 4% |
| INVALID_VPA | 3% |
| RISK_HELD | 2% |
| ambiguous tail (rules-miss) | 6% |

Source: relative ordering of Indian decline categories per gateway decline-code docs (insufficient funds dominates) `[ASSUMPTION on exact shares]`. Each code has 5–8 issuer-string paraphrases (messy bank strings). **Amendment 1** (`PROTOCOL.md §0`, tag `eval-preregistered-v1.1-risk-held-amendment`): RISK_HELD added at 2% (INSUFFICIENT_FUNDS 34→32) so all 11 canonical codes generate.

Amounts (paise): {19,900 · 29,900 · 39,900} 60%, {49,900 · 59,900 · 69,900 · 99,900} 25%, {149,900 · 249,900} 10%, remainder ≤ ₹5,000 5%. Demo slice additionally contains one ₹48,00,000-paise B2B invoice (₹48,000). `[ASSUMPTION: chai-subscription price points]`

## 3. Hidden behavioral truth (`replay.sim_customers`)

| Constant | Value | Provenance |
|---|---|---|
| Intent prior | would_pay_if 55% / wait_pay 30% / never_pay 15% | Recovery-tool response-rate literature midpoints `[ASSUMPTION]` |
| p_respond base | wa_sim 0.45 · sms_sim 0.35 · email_sim 0.15 · voice_sim 0.55 | WhatsApp/SMS engagement ordering `[ASSUMPTION]` |
| Response latency | lognormal μ=2.2h σ=0.9h (channel-shifted ±20%) | Dunning response curves `[ASSUMPTION]` |
| Organic recovery P(within 72h) | would_pay_if: cause-dependent 0.05–0.22 (highest INSUF_FUNDS near salary day); wait_pay 0.02; never_pay 0 | Self-correction without outreach `[ASSUMPTION — design target organic ≈7% overall]` |
| Annoyance threshold | Gamma(k=3, θ=1.2) contacts until complaint risk saturates | Contact-fatigue shape `[ASSUMPTION]` |
| p_complaint per unwanted contact | 0.010 × 1.6^(contacts_today) × ltv_factor | Complaint escalation with frequency `[ASSUMPTION]` |
| p_optout per unwanted contact | 0.012 × 1.5^(contact_count) | Opt-out growth `[ASSUMPTION]` |

## 4. Retry/rail resolution model (per canonical code)

| Code | Same-rail retry resolves | Notes |
|---|---|---|
| INSUFFICIENT_FUNDS | f(hours to salary day): 0.05 → up to 0.75 near credit +48h window | Salary-cycle timing effect `[CITED-PUBLIC: salary-lending cycles]` |
| ISSUER_DOWNTIME | 0.80 after transient outage window (1–6h), else 0.05 | Bank downtime transience `[CITED-PUBLIC: issuer outage advisories]` |
| AUTH_DECLINED_SOFT | 0.50 within 24h, then 0.15 | Soft-decline retry lore `[CITED-PUBLIC: Stripe retry docs pattern]` |
| AUTH_DECLINED_HARD | 0.05 | Hard declines persist `[CITED-PUBLIC: same]` |
| EXPIRED_CARD | 0.00 via retry; link/updated-instrument path required | Expired instrument cannot succeed un-updated |
| RISK_HELD | 0.10 without intervention | Issuer risk review lag `[ASSUMPTION]` |
| MANDATE_REVOKED | 0.00 mandate retry; link/rereg only | Revoked UPI AutoPay/e-mandate requires re-authorization `[CITED-PUBLIC: NPCI mandate lifecycle]` |
| MANDATE_LIMIT_BREACH | 0.00 above-limit retry; smaller-amount link works | Per-mandate cap enforcement `[CITED-PUBLIC: NPCI AutoPay limits]` |
| INVALID_VPA | 0.00 same-VPA; rereg/link with corrected handle 0.55 | Handle validity `[CITED-PUBLIC: NPCI]` |
| CUSTOMER_INITIATED | 0.00 — Reflex never re-attempts (respect cancellation); B1 wastes its retries at 0.01 goodwill cost | Product rule, not physics |
| UNKNOWN_AMBIGUOUS | conservative 0.12 flat | Fail-safe midpoint |

## 5. Channel economics

| Constant | Value | Provenance |
|---|---|---|
| sms_sim cost | ₹0.18/msg | Indian bulk SMS pricing `[CITED-PUBLIC: DLT-route pricing]` |
| wa_sim cost | ₹0.80/utility msg | WhatsApp Business utility template rate `[CITED-PUBLIC: Meta India utility rates]` |
| email_sim cost | ₹0.02 | ESP marginal cost `[ASSUMPTION]` |
| voice_sim cost | ₹4.00/call | Outbound telephony minute rate `[ASSUMPTION]` |
| razorpay_tm order/link | ₹0 direct (test mode; platform fees ignored in MVP ledger) | Test-mode behavior `[VERIFIED: test mode moves no money]` |

## 6. Value constants

| Constant | Value |
|---|---|
| LTV-band margin proxy (annoyance denominator) | low ₹2,000 · mid ₹6,000 · high ₹15,000 `[ASSUMPTION]` |
| contact_count_factor (annoyance) | 1.5^n over episode contacts |
| Episode window | 72 h sim (PRD FR-003) |

## 7. Fitting notes (honesty record)

Organic ≈7%, naive ≈24%, Reflex ≈42% recovery are *design targets* stated in PRD §16 as
expectations. They were used ONLY to sanity-check the simulator's plausibility during calibration;
they are not asserted anywhere in agent/UI code, and actual eval output replaces them wherever they
disagree (reported verbatim, `8. Rules.md` §16.3, `17.6`). If a run lands materially outside these
bands, the discrepancy is documented in `docs/limitations.md`, not tuned away after seeing results.
