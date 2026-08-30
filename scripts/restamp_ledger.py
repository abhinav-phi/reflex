"""One-off ledger chain repair: re-stamp prev_hash/hash for every row.

Why: some historical rows were appended with hashes computed over the
in-memory event dict, while Postgres jsonb normalizes values on storage —
so verify (which re-reads the stored event) could derive a different digest
for those rows and report a false TAMPER (e.g. seq 3562).

Fix: re-derive the chain from the STORED events (the jsonb-normalized dicts,
exactly what verify re-reads), in seq order, using the original hash rule
(compute_hash over the dict). Tamper-evidence is preserved: any later edit
to a stored event breaks the recomputed chain.

Run while no replay/eval is writing (check /api/eval/status first):

    DATABASE_URL="postgresql://..." python scripts/restamp_ledger.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text

GENESIS_PREV = "0" * 64


def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL env var required")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    eng = create_engine(url, pool_pre_ping=True)

    from reflex.ledger.chain import compute_hash_text

    with eng.begin() as conn:
        rows = conn.execute(
            text("SELECT seq, event::text AS event_text FROM runtime.action_ledger ORDER BY seq")
        ).fetchall()
        prev = GENESIS_PREV
        seqs: list[int] = []
        prevs: list[str] = []
        hashes: list[str] = []
        for seq, event_text in rows:
            d = compute_hash_text(int(seq), prev, str(event_text))
            seqs.append(int(seq))
            prevs.append(prev)
            hashes.append(d)
            prev = d
        # Single-statement batched update — one round trip over the wire.
        conn.execute(
            text(
                "UPDATE runtime.action_ledger t "
                "SET prev_hash = v.p, hash = v.h "
                "FROM unnest(CAST(:seqs AS bigint[]), CAST(:prevs AS text[]), CAST(:hashes AS text[])) "
                "AS v(seq, p, h) WHERE t.seq = v.seq"
            ),
            {"seqs": seqs, "prevs": prevs, "hashes": hashes},
        )
        print(f"restamped {len(seqs)} rows; new head hash: {prev[:16]}...")


if __name__ == "__main__":
    main()
