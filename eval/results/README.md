# Eval Results Index — what is citable, what is not

Every run in this folder is committed evidence. Nothing here was deleted or tuned.
Label legend: **OFFICIAL** = citable, quoted in README/docs · SMOKE = scale-verification
only, never citable as results.

| Directory | What it is | Citable? |
|---|---|---|
| `20260826T105147Z/` | **OFFICIAL keyed deterministic run** (Protocol Amendment 2): LLM key configured, `EVAL_OPENED_AT` clock anchor. Reflex 31.27% [28.91, 33.9] vs B1 21.22% — quoted in README + `docs/limitations.md`. | ✅ YES (headline) |
| `20260825T221826Z/` | **First keyed official run** (same day, pre-clock-anchor code path). Byte-identical per-seed results to `20260826T105147Z` — together these two runs are the **G5 reproduction PROOF** (`docs/limitations.md` §2). | ✅ YES (G5 counterpart) |
| `20260824T225305Z/` | Pre-key official run (Amendment-1 era, rules-only reflex arm). Preserved verbatim; superseded as headline by Amendment 2 — this is the DEGRADED-mode record. | 🟡 historical (labeled) |
| `20260824T194332Z-smoke/` · `20260824T194627Z-smoke/` · `20260824T203526Z-smoke/` · `20260825T184931Z-smoke/` | Scale-verification smoke runs (N=120). Harness proof only. | ❌ never as results |
| `dx_holdout/` | AI-1 diagnosis holdout: 500-case degraded-mode report + confusion matrix. | ✅ (component-level) |
| `g5_repro_check/` | Pre-fix G5 divergence investigation (isolated the wall-clock drift that TASK-061 fixed). Kept as the "how we found it" record. | 🟡 investigation record |
| `superseded_pre_amendment/` | Archived runs invalidated by Amendment 1 / harness fixes — see its own README. | ❌ explicitly non-citable |
| `b1_tuning.json` | B1 baseline tuning grid search (dev seeds only — never reported as results). | ✅ (methodology evidence) |

Rule of thumb: quote `20260826T105147Z/` for headline numbers, cite
`20260825T221826Z/` alongside it for the reproduction proof, and read
`docs/limitations.md` before repeating any metric anywhere.
