# Superseded / stranded evaluation artifacts

These runs were produced on 2026-08-24 by an earlier working copy whose
`RESULTS_DIR` resolved **outside the repository** (`~/Desktop/eval/results`),
so they were never committed. They are preserved here verbatim for honesty.

**None of the numbers in these files are citable**, for two independent reasons:

1. **Bootstrap CI bug (fixed):** `_bootstrap_ratio_ci` reduced the resampled
   denominator with a scalar `.sum()` instead of `.sum(axis=1)`, compressing
   every ratio-metric confidence interval by a factor of 1,000
   (= `BOOTSTRAP_RESAMPLES`). Point estimates are unaffected; all CIs here are
   wrong. Fixed in the same commit that added this note.
2. **Pre-amendment mixture (`20260824T152027Z` only):** this run is labeled
   `eval-preregistered-v1` but executed BEFORE Protocol Amendment 1
   (`eval-preregistered-v1.1-risk-held-amendment`: RISK_HELD 2%,
   INSUFFICIENT_FUNDS 34→32). Per `eval/PROTOCOL.md §0`, results produced
   before an amendment are superseded by it — the official post-amendment run
   supersedes this one entirely.

Additionally, `cost_per_100` was missing its ×100 factor and organic (b0)
recoveries were excluded from TTR in these versions; both fixed.

The official, citable artifacts live in `eval/results/<run_id>/` produced by
the fixed harness under Amendment 1.
