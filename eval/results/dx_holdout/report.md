# AI-1 Diagnosis Holdout — 500-case degraded-mode report

* Cases: **500** · construction seed `2026` · `[SIMULATED]` corpus
* Mode: LLM_API_KEY absent ⇒ rules-first, conservative `UNKNOWN_AMBIGUOUS` tail
* End-to-end accuracy: **100.00%** (500/500)
* Rules coverage (share classified by rules alone): **89.60%** (target ≥70% of matchable events, TechSpec §7 AI-1)
* Prompt-injection cases fail-closed to UNKNOWN_AMBIGUOUS: **YES**

## Confusion matrix (rows = ground truth, columns = prediction)

| truth \ pred | AUTH_DECLINED_HARD | AUTH_DECLINED_SOFT | CUSTOMER_INITIATED | EXPIRED_CARD | INSUFFICIENT_FUNDS | INVALID_VPA | ISSUER_DOWNTIME | MANDATE_LIMIT_BREACH | MANDATE_REVOKED | RISK_HELD | UNKNOWN_AMBIGUOUS |
|---|---|---|---|---|---|---|---|---|---|---|---|
| INSUFFICIENT_FUNDS | 0 | 0 | 0 | 0 | 63 | 0 | 0 | 0 | 0 | 0 | 0 |
| ISSUER_DOWNTIME | 0 | 0 | 0 | 0 | 0 | 0 | 45 | 0 | 0 | 0 | 0 |
| EXPIRED_CARD | 0 | 0 | 0 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| AUTH_DECLINED_SOFT | 0 | 54 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| AUTH_DECLINED_HARD | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| RISK_HELD | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 |
| MANDATE_REVOKED | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 54 | 0 | 0 |
| MANDATE_LIMIT_BREACH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 |
| INVALID_VPA | 0 | 0 | 0 | 0 | 0 | 36 | 0 | 0 | 0 | 0 | 0 |
| CUSTOMER_INITIATED | 0 | 0 | 34 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| UNKNOWN_AMBIGUOUS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 52 |

Reproduce: `python -m pytest tests/ai/test_diagnosis_accuracy.py -q`
