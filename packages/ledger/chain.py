"""Hash-chained append-only ledger (PRD FR-010, Rules §4.3).

hash = sha256(seq ‖ prev_hash ‖ canonical(event)) with canonical JSON:
sorted keys, compact separators, UTF-8, ensure_ascii=False.

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
    h = hashlib.sha256()
    h.update(str(seq).encode("ascii"))
    h.update(b"|")
    h.update(prev_hash.encode("ascii"))
    h.update(b"|")
    h.update(canonical_event(event))
    return h.hexdigest()


class LedgerWriter:
    """Appends events to runtime.action_ledger.

    Runtime mode (default): concurrency-safe via pg advisory lock + fresh head read.
    Eval mode (`fast=True`): the writer is the only appender in its transaction;
    caches the chain head in memory and skips the advisory lock (one INSERT per
    event instead of three round-trips). Hash semantics identical.
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
        seq = last_seq + 1
        ev = dict(event)
        ev.setdefault("ts", (at or datetime.now(UTC)).isoformat())
        digest = compute_hash(seq, prev_hash, ev)
        self.s.execute(
            text(
                "INSERT INTO runtime.action_ledger "
                "(episode_id, action_id, event, prev_hash, hash, created_at) "
                "VALUES (:episode_id, :action_id, CAST(:event AS jsonb), :prev_hash, :hash, COALESCE(:at, now()))"
            ),
            {
                "episode_id": episode_id,
                "action_id": action_id,
                "event": json.dumps(ev, ensure_ascii=False),
                "prev_hash": prev_hash,
                "hash": digest,
                "at": at,
            },
        )
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
    """
    expected_seq = 0
    prev = GENESIS_PREV
    for row in rows:
        seq = int(row["seq"])  # type: ignore[index]
        event = row["event"]  # type: ignore[index]
        prev_hash = str(row["prev_hash"])  # type: ignore[index]
        digest = str(row["hash"])  # type: ignore[index]
        expected_seq += 1
        if seq != expected_seq or prev_hash != prev or compute_hash(seq, prev, event) != digest:
            return False, seq, len(rows)
        prev = digest
    return True, None, len(rows)


def verify_db(session: Session) -> tuple[bool, int | None, int]:
    stmt = session.execute(
        text(
            "SELECT seq, event, prev_hash, hash FROM runtime.action_ledger ORDER BY seq"
        )
    )
    valid = True
    first_bad: int | None = None
    checked = 0
    expected_seq = 0
    prev = GENESIS_PREV
    for seq, event, prev_hash, digest in stmt:
        checked += 1
        expected_seq += 1
        ok = (
            int(seq) == expected_seq
            and prev_hash == prev
            and compute_hash(int(seq), prev, dict(event)) == digest
        )
        if not ok and valid:
            valid = False
            first_bad = int(seq)
        if ok:
            prev = digest
    return valid, first_bad, checked


def log() -> logging.Logger:
    return logging.getLogger("reflex.ledger")
