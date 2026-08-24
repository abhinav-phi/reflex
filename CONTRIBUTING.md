# Contributing to Reflex

Welcome — and read this twice. Reflex is a **money-adjacent agentic system**: it sits on payment rails, touches customer trust, and its entire value proposition is that it can be *proven* safe and honest. That means the safety rules in this document are **non-negotiable**. A PR that is elegant but violates a safety rule is rejected. When in doubt: **fail closed, log everything, label simulations.**

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Git Workflow & Branching Strategy](#git-workflow--branching-strategy)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Code Style & Quality Standards](#code-style--quality-standards)
- [Fintech & AI Safety Rules (CRITICAL)](#fintech--ai-safety-rules-critical)
- [Pull Request Process](#pull-request-process)

## Code of Conduct

This project follows the **Contributor Covenant v1.4**:

> ### Contributor Code of Conduct
> #### Our Pledge
> In the interest of fostering an open and welcoming environment, we as contributors and maintainers pledge to making participation in our project and our community a harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity and expression, level of experience, nationality, personal appearance, race, religion, or sexual identity and orientation.
> #### Our Standards
> Examples of behavior that contributes to creating a positive environment include using welcoming and inclusive language, being respectful of differing viewpoints and experiences, gracefully accepting constructive criticism, focusing on what is best for the community, and showing empathy towards other community members. Examples of unacceptable behavior by participants include the use of sexualized language or imagery, derogatory comments or personal or political attacks, public or private harassment, publishing others' private information, or other conduct which could reasonably be considered inappropriate in a professional setting.
> #### Our Responsibilities
> Project maintainers are responsible for clarifying the standards of acceptable behavior and are expected to take appropriate and fair corrective action in response to any instances of unacceptable behavior. Maintainers have the right and responsibility to remove, edit, or reject comments, commits, code, wiki edits, issues, and other contributions that are not aligned to this Code of Conduct.
> #### Scope
> This Code of Conduct applies both within project spaces and in public spaces when an individual is representing the project or its community.
> #### Enforcement
> Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the project team. All complaints will be reviewed and investigated and will result in a response that is deemed necessary and appropriate to the circumstances. The project team is obligated to maintain confidentiality with regard to the reporter of an incident. Maintainers who do not follow or enforce the Code of Conduct in good faith may face temporary or permanent repercussions as determined by other members of the project's leadership.
> #### Attribution
> This Code of Conduct is adapted from the [Contributor Covenant][homepage], version 1.4, available at https://www.contributor-covenant.org/version/1/4/code-of-conduct.html

[homepage]: https://www.contributor-covenant.org

## Development Setup

```bash
# 1. Clone & enter
git clone https://github.com/abhinav-phi/reflex.git
cd reflex

# 2. Backend — Python 3.11+ virtualenv
python -m venv .venv
.\.venv\Scripts\activate          # Windows   (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev]"

# 3. Environment
cp .env.example .env              # never commit your real .env

# 4. Infrastructure + schema + seed data
make up                           # docker compose (postgres/redis/api/workers/web) + migrations
make seed                         # idempotent: users / merchant / policy v1 / corpora

# 5. Frontend (for local dev server instead of the compose web container)
cd apps/web && npm install && npm run dev   # http://localhost:5173

# 6. Sanity check
make test                         # full backend suite
```

Full operator walkthrough: [`MANUAL_STEPS.md`](MANUAL_STEPS.md).

## Git Workflow & Branching Strategy

Trunk-based development:

- `main` is always releasable; CI must be green.
- Short-lived branches off `main`: `<type>/<short-description>` — e.g. `feat/ev-drawer-sparkline`, `fix/webhook-raw-body`, `docs/tracker-sync`.
- Squash-merge via PR; ≥1 approval, or self-approval with recorded reasoning during the buildathon window.

## Commit Message Guidelines

Conventional Commits, enforced by review:

```text
feat(shield): add quiet-hours boundary check at exactly 21:00:00
fix(api): verify HMAC on raw webhook body before parsing
docs(tracker): sync statuses after v1.3 audit remediation
test(eval): add kill-switch drain timing harness
refactor(workers): extract context loader from dispatcher
perf(ledger): fast single-writer mode for Proof arm transactions
chore(ci): wire gitleaks-action into secrets job
```

Types: `feat` · `fix` · `docs` · `refactor` · `perf` · `test` · `chore`. Scope = package/app touched.

## Code Style & Quality Standards

All of these must pass before you open a PR:

```bash
# Backend lint + format (ruff, line-length 100, py311 target)
ruff check packages apps tests scripts
ruff format packages apps tests scripts

# Types
mypy packages apps

# Backend tests (e2e + live-LLM excluded by default)
pytest tests -m "not e2e and not ai_live"

# Frontend
cd apps/web
npm run typecheck        # tsc strict --noEmit: zero errors
npm test -- --run        # vitest
npm run build            # vite production build
```

Frontend rules:
- **No `any`** anywhere in `apps/web/src` — TypeScript `strict` or it doesn't ship.
- Money is a branded type (`Paise`); a paise value cannot be rendered as a count.
- All amounts render through `formatINR` (Indian grouping ₹2,41,000, tabular numerals). Never raw paise.
- No business logic in components — calculations live in generated utils, unit-tested.
- API payload types are generated from Pydantic schemas — never hand-duplicated.
- Design tokens only (no ad-hoc hex/spacing); every simulated datum gets its `[SIMULATED]` badge.

## Fintech & AI Safety Rules (CRITICAL)

Violating any of these = instant PR rejection, no exceptions:

1. **Test-mode only.** Razorpay keys MUST start with `rzp_test_` (enforced in code — `TestModeViolation` otherwise). **Live keys are forbidden in this project, period.**
2. **AI boundary: "AI proposes, deterministic code disposes."** The LLM never authors money-bearing content — amounts, links, dates, UPI handles are DB-injected into slots *after* generation, and the validator rejects 100% of digit/URL/₹ spans. If your change lets the LLM emit a digit into user-visible text, stop.
3. **Never trust raw LLM output.** Every LLM response passes schema validation; invalid ⇒ one retry ⇒ deterministic fallback. Never a third guess.
4. **Database isolation is structural, not conventional.** Never widen grants for the `reflex_agent` DB role — it must never read `replay.sim_*` hidden simulator truth (ADR-004 anti-cheat boundary, verified by SQLSTATE-42501 tests). Any PR that widens these grants is rejected on sight.
5. **The ledger is append-only.** `runtime.action_ledger` has INSERT/SELECT grants only — no UPDATE/DELETE, ever, verified by test. Ledger-first invariant: an action that cannot be ledgered must not be dispatched.
6. **Eval pre-registration.** Never commit evaluation results before the `eval-preregistered-v1` tag exists in git history — and never rewrite history after it. Results without the protocol tag are treated as fabricated.
7. **No secrets, ever.** Config via env only; `.env.example` documents every variable; gitleaks runs in CI on every push including history.
8. **Label everything simulated.** Every simulated channel/datum/metric carries `[SIMULATED]`; Razorpay surfaces carry `[TEST MODE]`. No exceptions — including charts and exports.
9. **Fail closed.** Approval timeout ⇒ decline. Budget uncertainty ⇒ stop paid actions. Ledger failure ⇒ halt dispatch. DB loss ⇒ ingestion 503. Uncertainty ⇒ escalate to a human, never improvise.

## Pull Request Process

1. **Branch** from `main` using the naming convention above.
2. **Green locally:** all commands from [Code Style](#code-style--quality-standards) pass on your machine.
3. **CI green:** backend (lint + migrate/seed + pytest), web (typecheck/vitest/build), and gitleaks jobs must pass.
4. **Docs impact:** if you change an interface (API routes, SSE event names, enums, schema), update the internal design documentation and generated TS types in the same PR — TechSpec's API table is the contract, the schema enums are the source of truth.
5. **AI prompt changes:** prompts are versioned artifacts (`packages/prompts/templates/`). Bump the version file, register it in `packages/prompts/registry.py`, note the prompt hash change, and run the AI eval suite (`pytest tests/ai -q`) in the PR.
6. **Bug fixes ship with the test that would have caught them** — no exceptions.
7. **Describe demo impact** in the PR template: does this change what judges see?
8. **Squash merge** with a clean conventional-commit message; delete the branch.

---

*Questions about whether something is safe? That uncertainty is your answer: fail closed and open an issue first.*
