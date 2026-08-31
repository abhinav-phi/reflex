"""Hash-chained append-only ledger (PRD FR-010, Rules §4.3).

hash = sha256(seq ‖ prev_hash ‖ event::text) — the event text is the
jsonb-normalized form Postgres stores, computed server-side inside the INSERT
itself (see LedgerWriter.append). Append and verify therefore hash the exact
same bytes by construction: no value jsonb normalizes differently can produce
a false TAMPER, and no concurrent appender can fork the chain (single
statement, advisory-lock serialized).

Ledger-first invariant: an action that cannot be ledgered must not be
dispatched — callers append BEFORE dispatch and treat failure as blocking.
"""

from __future__ import annotations

import contextvars
import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reflex.core.models import ActionLedgerRow
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

LEDGER_LOCK_KEY = 723301  # pg advisory lock id for global append serialization
GENESIS_PREV = "0" * 64

# Eval pipelines enable this per-thread: each arm-run is the single appender
# inside its own transaction, so the advisory lock + head re-read are skipped.
# Hash semantics identical either way. ContextVar ⇒ safe under parallel arms.

_FAST_MODE: contextvars.ContextVar[bool] = contextvars.ContextVar("reflex_fast_ledger", default=False)


class fast_ledger:
    """Context manager enabling single-writer fast appends (Proof harness only)."""

    def __enter__(self) -> fast_ledger:
        self._token = _FAST_MODE.set(True)
        return self

    def __exit__(self, *exc: object) -> None:
        _FAST_MODE.reset(self._token)


def canonical_event(event: dict[str, Any]) -> bytes:
    return json.dumps(
        event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_hash(seq: int, prev_hash: str, event: dict[str, Any]) -> str:
    """Hash the in-memory canonical form — used by the in-process eval ledger
    and as the verify fallback for rows that carry no stored text."""
    h = hashlib.sha256()
    h.update(str(seq).encode("ascii"))
    h.update(b"|")
    h.update(prev_hash.encode("ascii"))
    h.update(b"|")
    h.update(canonical_event(event))
    return h.hexdigest()


def compute_hash_text(seq: int, prev_hash: str, event_text: str) -> str:
    """Hash the jsonb-normalized event text (`event::text`).

    Postgres jsonb normalizes values on storage, so the STORED text is the only
    stable truth. Append computes the hash server-side over exactly this text
    (one atomic INSERT — see LedgerWriter.append), and verify re-hashes the same
    text read back. Both sides agree by construction.
    """
    h = hashlib.sha256()
    h.update(str(seq).encode("ascii"))
    h.update(b"|")
    h.update(prev_hash.encode("ascii"))
    h.update(b"|")
    h.update(event_text.encode("utf-8"))
    return h.hexdigest()


# One atomic statement: seq (nextval), event (jsonb), and the hash — computed
# server-side from the jsonb-normalized text with pgcrypto — are written in a
# single INSERT. No follow-up UPDATE (the agent role's append-only grants have
# no UPDATE on this table), and no window for a concurrent writer to fork the
# chain (the advisory lock is held for the whole transaction).
_APPEND_SQL = text(
    """
    WITH new_seq AS (
        SELECT nextval('runtime.action_ledger_seq_seq') AS seq
    ),
    payload AS (
        SELECT new_seq.seq AS seq,
               CAST(:event AS jsonb) AS ev,
               CAST(:prev_hash AS text) AS prev,
               COALESCE(CAST(:at AS timestamptz), now()) AS cat
        FROM new_seq
    )
    INSERT INTO runtime.action_ledger
        (seq, episode_id, action_id, event, prev_hash, hash, created_at)
    SELECT payload.seq,
           CAST(:episode_id AS uuid),
           CAST(:action_id AS uuid),
           payload.ev,
           payload.prev,
           encode(digest(concat(payload.seq::text, '|', payload.prev, '|', (payload.ev)::text), 'sha256'), 'hex'),
           payload.cat
    FROM payload
    RETURNING seq, hash, event::text AS event_text
    """
)


class LedgerWriter:
    """Appends events to runtime.action_ledger.

    Runtime mode (default): concurrency-safe via pg advisory lock + fresh head
    read. Eval mode (`fast=True`): the writer is the only appender in its
    transaction; caches the chain head in memory. Hash semantics identical.
    """

    def __init__(self, session: Session, *, fast: bool | None = None) -> None:
        self.s = session
        self.fast = _FAST_MODE.get() if fast is None else fast
        self._seq: int | None = None
        self._prev: str = GENESIS_PREV

    def head(self) -> tuple[int, str]:
        if self.fast and self._seq is not None:
            return self._seq, self._prev
        row = self.s.execute(
            text("SELECT seq, hash FROM runtime.action_ledger ORDER BY seq DESC LIMIT 1")
        ).first()
        if row is None:
            return 0, GENESIS_PREV
        seq, prev = int(row[0]), str(row[1])
        return seq, prev

    def append(
        self,
        *,
        episode_id: Any,
        event: dict[str, Any],
        action_id: Any | None = None,
        at: datetime | None = None,
    ) -> tuple[int, str]:
        if not self.fast:
            self.s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LEDGER_LOCK_KEY})
        last_seq, prev_hash = self.head()
        ev = dict(event)
        ev.setdefault("ts", (at or datetime.now(UTC)).isoformat())
        row = self.s.execute(
            _APPEND_SQL,
            {
                "episode_id": str(episode_id),
                "action_id": str(action_id) if action_id else None,
                "event": json.dumps(ev, ensure_ascii=False),
                "prev_hash": prev_hash,
                "at": at,
            },
        ).mappings().one()
        seq = int(row["seq"])
        digest = str(row["hash"])
        self._seq = seq
        self._prev = digest
        return seq, digest


class InMemoryLedger:
    """Deterministic in-process ledger for Proof's eval pipeline (same hashing)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._seq = 0
        self._prev = GENESIS_PREV

    def append(
        self,
        *,
        episode_id: Any,
        event: dict[str, Any],
        action_id: Any | None = None,
        at: datetime | None = None,
    ) -> tuple[int, str]:
        self._seq += 1
        ev = dict(event)
        ev.setdefault("ts", (at or datetime.now(UTC)).isoformat())
        digest = compute_hash(self._seq, self._prev, ev)
        self.rows.append(
            {
                "seq": self._seq,
                "episode_id": str(episode_id),
                "action_id": str(action_id) if action_id else None,
                "event": ev,
                "prev_hash": self._prev,
                "hash": digest,
            }
        )
        self._prev = digest
        return self._seq, digest


def verify_rows(rows: Sequence[dict[str, Any] | ActionLedgerRow]) -> tuple[bool, int | None, int]:
    """Walk chain in seq order; returns (valid, first_bad_seq, checked).

    Detects tampering with event payloads, hashes, or sequence linkage.

    Seq numbers may have gaps (BIGSERIAL skips values on rolled-back
    transactions) — the integrity guarantee is the hash chain, not contiguity.

    Rows fetched from the database carry `event_text` (the jsonb-normalized
    event::text) and are hashed with compute_hash_text. In-memory rows (eval
    harness) carry only the dict and keep the canonical-dict fallback.
    """
    prev_seq = 0
    prev = GENESIS_PREV
    for row in rows:
        seq = int(row["seq"])  # type: ignore[index]
        event = row["event"]  # type: ignore[index]
        prev_hash = str(row["prev_hash"])  # type: ignore[index]
        digest = str(row["hash"])  # type: ignore[index]
        event_text = row.get("event_text") if hasattr(row, "get") else None
        expected = (
            compute_hash_text(seq, prev, str(event_text))
            if event_text is not None
            else compute_hash(seq, prev, event)
        )
        if seq <= prev_seq or prev_hash != prev or expected != digest:
            return False, seq, len(rows)
        prev_seq = seq
        prev = digest
    return True, None, len(rows)


def verify_episode_slice(
    session: Session, episode_id: str
) -> tuple[bool, int | None, int, list[dict[str, Any]]]:
    """Verify one episode's trail against the GLOBAL chain, row by row.

    Under the replay driver, episodes' rows interleave in seq order, so a
    slice cannot be verified by walking it with a single seeded head — each
    row must link to its OWN global predecessor. For every row this checks:

    1. linkage: `prev_hash` equals the hash of the globally preceding row
       (genesis for the chain's first row) — detects deletions and tampered
       links anywhere before the row, even outside the slice;
    2. self-consistency: `hash` equals sha256 over (seq | prev_hash | stored
       event text) — detects event or hash tampering.

    Returns (valid, first_bad_seq, checked, rows); rows carry the fields the
    ledger API renders plus `global_prev_hash`/`global_prev_seq` used by the
    checks. An unknown episode yields an empty, valid trail.
    """
    rows = session.execute(
        text(
            """
            SELECT l.seq, l.episode_id::text AS episode_id,
                   l.action_id::text AS action_id, l.event,
                   l.event::text AS event_text, l.prev_hash, l.hash,
                   l.created_at, g.hash AS global_prev_hash,
                   g.seq AS global_prev_seq
            FROM runtime.action_ledger l
            LEFT JOIN LATERAL (
                SELECT g.hash, g.seq FROM runtime.action_ledger g
                WHERE g.seq < l.seq ORDER BY g.seq DESC LIMIT 1
            ) g ON true
            WHERE l.episode_id = CAST(:e AS uuid)
            ORDER BY l.seq
            """
        ),
        {"e": str(episode_id)},
    ).mappings().all()
    if not rows:
        return True, None, 0, []
    valid, first_bad, checked = _check_slice_rows([dict(r) for r in rows])
    return valid, first_bad, checked, [dict(r) for r in rows]


def _check_slice_rows(
    rows: list[dict[str, Any]],
) -> tuple[bool, int | None, int]:
    """Pure checks for `verify_episode_slice`: each row must link to its own
    global predecessor (genesis for the chain's first row) and carry a hash
    consistent with its own stored prev_hash and event text."""
    valid = True
    first_bad: int | None = None
    checked = 0
    prev_seq = 0
    for r in rows:
        seq = int(r["seq"])
        stored_prev = str(r["prev_hash"])
        digest = str(r["hash"])
        expected_link = GENESIS_PREV if r["global_prev_hash"] is None else str(r["global_prev_hash"])
        event_text = r.get("event_text")
        expected_hash = (
            compute_hash_text(seq, stored_prev, str(event_text))
            if event_text is not None
            else compute_hash(seq, stored_prev, r["event"])
        )
        ok = (
            seq > prev_seq
            and stored_prev == expected_link
            and expected_hash == digest
        )
        if not ok and valid:
            valid = False
            first_bad = seq
        if ok:
            prev_seq = seq
        checked += 1
    return valid, first_bad, checked


def verify_db(session: Session) -> tuple[bool, int | None, int]:
    stmt = session.execute(
        text(
            "SELECT seq, event::text, prev_hash, hash FROM runtime.action_ledger ORDER BY seq"
        )
    )
    valid = True
    first_bad: int | None = None
    checked = 0
    prev_seq = 0
    prev = GENESIS_PREV
    for seq, event_text, prev_hash, digest in stmt:
        checked += 1
        ok = (
            int(seq) > prev_seq
            and prev_hash == prev
            and compute_hash_text(int(seq), prev, str(event_text)) == digest
        )
        if not ok and valid:
            valid = False
            first_bad = int(seq)
        if ok:
            prev_seq = int(seq)
            prev = digest
    return valid, first_bad, checked


def log() -> logging.Logger:
    return logging.getLogger("reflex.ledger")
