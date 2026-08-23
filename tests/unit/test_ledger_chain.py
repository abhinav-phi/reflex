"""Hash-chain semantics: append, verify, tamper detection (FR-010)."""

import pytest

from reflex.ledger.chain import (
    GENESIS_PREV,
    InMemoryLedger,
    compute_hash,
    canonical_event,
    verify_rows,
)


def test_deterministic_hash():
    ev = {"type": "X", "n": 1}
    h1 = compute_hash(1, GENESIS_PREV, ev)
    h2 = compute_hash(1, GENESIS_PREV, dict(reversed(list(ev.items()))))
    assert h1 == h2  # canonical JSON sorts keys
    assert compute_hash(2, GENESIS_PREV, ev) != h1


def test_chain_append_and_verify():
    led = InMemoryLedger()
    for i in range(5):
        seq, digest = led.append(episode_id="e", event={"i": i})
        assert seq == i + 1
    ok, bad, checked = verify_rows(led.rows)
    assert ok and bad is None and checked == 5
    assert led.rows[0]["prev_hash"] == GENESIS_PREV
    assert led.rows[3]["prev_hash"] == led.rows[2]["hash"]


def test_tamper_detected():
    led = InMemoryLedger()
    for i in range(4):
        led.append(episode_id="e", event={"i": i})
    rows = [dict(r) for r in led.rows]
    rows[2]["event"]["i"] = 999  # tamper a payload
    ok, bad, _ = verify_rows(rows)
    assert not ok and bad == 3  # first BAD seq is the next link

    rows2 = [dict(r) for r in led.rows]
    rows2[1]["hash"] = "0" * 64  # tamper a hash directly
    ok, bad, _ = verify_rows(rows2)
    assert not ok and bad == 2


def test_reorder_detected():
    led = InMemoryLedger()
    for i in range(3):
        led.append(episode_id="e", event={"i": i})
    rows = [dict(r) for r in led.rows]
    rows[0], rows[1] = rows[1], rows[0]
    ok, bad, _ = verify_rows(rows)
    assert not ok
