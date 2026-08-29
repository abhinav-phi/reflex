#!/usr/bin/env bash
# Reflex - one-command reproduction from a clean clone (eval/PROTOCOL.md §4).
# Target: < 15 min on the 4-core reference VM.
# Full runbook (incl. troubleshooting + Windows port-range workaround): MANUAL_STEPS.md §8.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Reflex reproduction ([SIMULATED] evaluation) =="

# 0) protocol provenance gate — refuses to run official eval without the tag
python - <<'PY'
from reflex.eval.runner import preregistration_tag_present, PREREG_TAG
import sys
if not preregistration_tag_present():
    print(f"REFUSING: git tag {PREREG_TAG} missing from history", file=sys.stderr)
    sys.exit(2)
print(f"protocol tag {PREREG_TAG}: present ✓")
PY

# 1) infra
docker compose up -d postgres redis
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U postgres -d reflex >/dev/null 2>&1; then break; fi
  sleep 1
done

# 2) environment
if [ ! -d ".venv" ]; then
  python -m venv .venv
fi
# Windows venvs put interpreters in Scripts/, POSIX in bin/ (Git Bash is Windows).
if [ -f ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
else
  PY=".venv/bin/python"
fi
# [dev] installs alembic (schema migrations) alongside runtime deps — without it
# `python -m alembic` resolves to the repo's local alembic/ migrations directory
# (a namespace package with no __main__) and the clean-clone run dies here.
$PY -m pip install -e ".[dev]" --quiet

export DATABASE_URL_ADMIN="${DATABASE_URL_ADMIN:-postgresql+psycopg://postgres:reflex_dev_pg@localhost:15432/reflex}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://reflex_agent:agent_dev_pw@localhost:15432/reflex}"
export DATABASE_URL_EVAL="${DATABASE_URL_EVAL:-postgresql+psycopg://reflex_eval:eval_dev_pw@localhost:15432/reflex}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
# The 0001 migration creates the app roles with env-overridable passwords
# (defaults are the CI-secure ones, which would NOT match the URLs above —
# compose passes these same vars to its services).
export REFLEX_AGENT_PW="${REFLEX_AGENT_PW:-agent_dev_pw}"
export REFLEX_EVAL_PW="${REFLEX_EVAL_PW:-eval_dev_pw}"
export REFLEX_ADMIN_PW="${REFLEX_ADMIN_PW:-admin_dev_pw}"
export PYTHONIOENCODING=utf-8

# 3) schema + reference data (idempotent)
$PY -m alembic upgrade head
$PY -m reflex.eval.seed

# 4) OFFICIAL pre-registered evaluation: 3 seeds x {b0,b1,reflex} x ablations A1-A4
$PY -m reflex.eval.cli run "$@"
echo "done — see eval/results/<run_id>/results.json and tables.md [SIMULATED]"
