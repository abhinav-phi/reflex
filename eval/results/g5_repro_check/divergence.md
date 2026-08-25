# G5 Reproduction & A2 Divergence — seed 42 [SIMULATED]

G5 all arms within ±0.005: **FAIL**

| Arm | Committed % | Rerun % | Diff pp | In tol |
|---|---|---|---|---|
| b0 | 4.11 | 4.11 | 0.0049 | ✅ |
| b1 | 23.75 | 25.38 | 1.6326 | ❌ |
| reflex | 34.33 | 33.46 | -0.8696 | ❌ |
| reflex:A1 | 34.33 | 33.46 | -0.8696 | ❌ |
| reflex:A2 | 40.44 | 39.63 | -0.8093 | ❌ |
| reflex:A3 | 34.33 | 33.46 | -0.8696 | ❌ |
| reflex:A4 | 30.25 | 27.42 | -2.8348 | ❌ |
| reflex:DEGRADED | 34.33 | 33.46 | -0.8696 | ❌ |

## Reflex(full-EV) vs A2(EV-off) paired episode outcomes

- episodes_total: `3000`
- both_recovered: `{'count': 686, 'value_paise': 34700900}`
- only_full_ev_recovered: `{'count': 15, 'value_paise': 1118700}`
- only_ev_off_recovered: `{'count': 407, 'value_paise': 7724000}`
- full_contacts: `1065`
- evoff_contacts: `2197`
- full_complaints: `5`
- evoff_complaints: `11`
- full_declined_cohort: `1221`
- evoff_declined_cohort: `66`
- full_cost_paise: `82038`
- evoff_cost_paise: `212828`
- only_a2_sample_codes: `['AUTH_DECLINED_HARD', 'AUTH_DECLINED_SOFT', 'EXPIRED_CARD', 'INSUFFICIENT_FUNDS', 'ISSUER_DOWNTIME', 'MANDATE_LIMIT_BREACH', 'MANDATE_REVOKED', 'RISK_HELD', 'UNKNOWN_AMBIGUOUS']`
- only_reflex_sample_codes: `['EXPIRED_CARD']`

_Wall-clock start differs between runs by construction; any drift beyond
tolerance indicates hidden wall-clock dependence (opened_at=2026-08-25T05:46:14+00:00)._
