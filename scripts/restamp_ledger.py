"""One-off ledger chain repair: re-stamp prev_hash/hash for every row.

Why: hashes were originally computed over the Python-side canonical JSON,
but the event column is jsonb — Postgres normalizes values (float rendering,
unicode) on storage, so verify (which reads event::text) could derive a
different byte string for some rows and report a false TAMPER.

Append + verify now both hash `event::text` (see packages/ledger/chain.py).
This script re-stamps the existing rows with that same rule, in seq order,
so the chain becomes self-consistent again. Tamper-evidence is preserved:
any later edit to a stored event breaks the recomputed chain.

Run while no replay/eval is writing (check /api/eval/status first):

    DATABASE_URL="postgresql://..." python scripts/restamp_ledger.py
"""

from __future__ import annotations

import hashlib
import os
import sys

from sqlalchemy import create_engine, text

GENESIS_PREV = "0" * 64


def _digest(seq: int, prev_hash: str, event_text: str) -> str:
    h = hashlib.sha256()
    h.update(str(seq).encode("ascii"))
    h.update(b"|")
    h.update(prev_hash.encode("ascii"))
    h.update(b"|")
    h.update(event_text.encode("utf-8"))
    return h.hexdigest()


def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL env var required")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    eng = create_engine(url, pool_pre_ping=True)

    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT seq, event::text FROM runtime.action_ledger ORDER BY seq")
        ).fetchall()
        prev = GENESIS_PREV
        for seq, event_text in rows:
            d = _digest(int(seq), prev, str(event_text))
            conn.execute(
                text("UPDATE runtime.action_ledger SET prev_hash = :p, hash = :h WHERE seq = :s"),
                {"p": prev, "h": d, "s": int(seq)},
            )
            prev = d
        print(f"restamped {len(rows)} rows; new head hash: {prev[:16]}...")


if __name__ == "__main__":
    main()
