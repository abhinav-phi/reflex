<!-- Reflex PR checklist — see CONTRIBUTING.md and docs/8. Rules.md -->

## What does this PR change?
<!-- One short paragraph. Reference task IDs from docs/7.Tracker.md if applicable. -->

## Evidence
- [ ] `make test` passes locally (backend suite green)
- [ ] Every number added to docs/ or UI traces to a committed artifact in `eval/results/`
- [ ] Simulated metrics keep their `[SIMULATED]` label; design targets stay labeled as targets
- [ ] No real API keys, no live-customer paths, Razorpay test-mode only (`rzp_test_`)

## Honesty check (Rules §16)
- [ ] Actuals and targets are distinguishable in every user-facing sentence
- [ ] Negative results are reported, not tuned away
