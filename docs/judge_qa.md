# Judge Q&A — Prepared Answers (created v1.2, audit P2-8)

Companion to `7.Tracker.md` 5-Minute Pitch Checklist. One-line answers; detail pointers in brackets.

**Q: Why is AI needed at all — why not pure rules?**
Rules cover ~70–88% of clean strings, but the same root cause surfaces as different messy issuer strings across banks; the LLM covers only that ambiguous tail (target ~25–30% touch rate), everything else stays deterministic. [PRD §14, ADR-003]

**Q: How do we know your numbers aren't rigged?**
Structural anti-cheat: agent DB role physically cannot read simulator truth (`replay.sim_*`); protocol git-tagged before first results; B1 honestly tuned on dev seeds; losing cohort published. [ADR-004/007, eval/PROTOCOL.md]

**Q: What happens when the model is wrong?**
Three nets: strict JSON schema (retry once → UNKNOWN_AMBIGUOUS), confidence <0.6 → conservative default, and Shield — which never consults the model — blocks anything out of bounds. [TechSpec §7, Rules §2]

**Q: Can the LLM spend money?**
No. It never authors an amount/link/date; those are DB-injected post-generation and validator-rejected if it tries ("AI proposes, deterministic code disposes"). MVP moves no money at all — orders/links in test mode only. [Rules §2.2, §4]

**Q: What's your baseline?**
B0 organic-only and B1 tuned-naive (retry×3 + SMS×2), tuned via committed grid search on dev seeds, run on the identical batch as Reflex. [FR-016, PROTOCOL §3]

**Q: Where does Reflex lose?**
Published losing cohort: tiny (<₹150) ephemeral failures where contact cost > EV — we decline; naive wastes spend. [PROTOCOL §2]

**Q: What happens when the LLM provider is down?**
Two consecutive failures flip DEGRADED mode: rules-only diagnosis + frozen policy, actions stamped, zero episodes dropped — demoable via a real injection endpoint. [F1, AppFlow §8]

**Q: How do you stop contacting someone who complains?**
Three layers: keyword gate runs first regardless of model health; COMPLAINT ⇒ instant global suppression + human handoff + episode STOPPED_CUSTOMER; Shield then blocks all further contact for that customer. Gates: COMPLAIN precision ≥95% AND recall ≥90% offline — both green. [AI-4, F5, TASK-054]

**Q: Prompt injection?**
Untrusted text is `<data>`-wrapped with an instruction contract, outputs schema-gated, tools allowlisted; an adversarial corpus runs in CI. Delimiters reduce but don't provably eliminate injection risk — defense is layered and fail-closed.

**Q: Is this just retry logic?**
No — retries re-attempt one rail blindly. Reflex changes diagnosis→intervention→timing→channel per failure, inside hard caps/budget/quiet-hours, with per-action EV math shown and hash-chained audit.

**Q: Why is there a ₹48,000 payment in a chai-subscription dataset?**
Corporate bulk-gifting order — deliberately included to exercise the >₹50,000-class human approval gate. [Schema §13]

**Q: What's NOT implemented?**
Real channels (simulated); the official eval HAS run ([SIMULATED], committed at `eval/results/20260824T225305Z/`) but without an LLM key — degraded==full caveat, and G5 second-run reproduction is pending; export UI wiring unverified (API shipped); live Razorpay test-mode observation (TASK-056); mandate deep-journey UI; pitch video — all tracked in Tracker/limitations. README/CONTRIBUTING/MANUAL_STEPS are in the repo root.

**Q: Are the demo numbers real?**
The counters on stage are live system output from a seeded, deterministic replay slice. The pre-registered targets were 42%/24%/7%; the official run's actuals [SIMULATED] are committed at `eval/results/20260824T225305Z/`: **31.40% vs 21.16% vs 4.68%** with bootstrap CIs, incremental vs naive +10.24 pp CI[+7.83,+12.62] — we miss the aspirational ≥+15 pp gate and say so plainly (`docs/limitations.md`). [AppFlow §13 annotation, Rules §16]
