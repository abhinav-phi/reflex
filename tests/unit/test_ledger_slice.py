"""Slice verification semantics: _check_slice_rows checks each row against
its OWN global predecessor (the replay driver interleaves episodes, so a
single-seeded walk falsely fails at slice boundaries)."""

from __future__ import annotations

from reflex.ledger.chain import (
    GENESIS_PREV,
    InMemoryLedger,
    _check_slice_rows,
    compute_hash,
    compute_hash_text,
)


def _rows_with_global(led: InMemoryLedger) -> list[dict]:
    """Attach global_prev_hash/global_prev_seq to ledger rows, mimicking the
    LATERAL join in verify_episode_slice."""
    out: list[dict] = []
    ordered = sorted(led.rows, key=lambda r: int(r["seq"]))
    for i, r in enumerate(ordered):
        d = dict(r)
        d["event_text"] = None  # force the canonical-dict fallback path
        if i == 0:
            d["global_prev_hash"] = None
            d["global_prev_seq"] = None
        else:
            d["global_prev_hash"] = ordered[i - 1]["hash"]
            d["global_prev_seq"] = ordered[i - 1]["seq"]
        out.append(d)
    return out


def test_interleaved_slice_valid():
    """Two episodes alternating in the global chain: each slice verifies."""
    led = InMemoryLedger()
    for i in range(6):
        led.append(episode_id="a" if i % 2 == 0 else "b", event={"i": i})
    a_rows = [r for r in _rows_with_global(led) if r["episode_id"] == "a"]
    b_rows = [r for r in _rows_with_global(led) if r["episode_id"] == "b"]
    ok, bad, checked = _check_slice_rows(a_rows)
    assert ok and bad is None and checked == 3
    ok, bad, checked = _check_slice_rows(b_rows)
    assert ok and bad is None and checked == 3


def test_slice_tampered_event_detected():
    led = InMemoryLedger()
    for i in range(4):
        led.append(episode_id="a", event={"i": i})
    rows = _rows_with_global(led)
    rows[1]["event"]["i"] = 999  # payload tamper keeps hash stale
    ok, bad, _ = _check_slice_rows(rows)
    assert not ok and bad == int(rows[1]["seq"])


def test_slice_tampered_hash_detected():
    led = InMemoryLedger()
    for i in range(4):
        led.append(episode_id="a", event={"i": i})
    rows = _rows_with_global(led)
    rows[2]["hash"] = "f" * 64
    ok, bad, _ = _check_slice_rows(rows)
    assert not ok and bad == int(rows[2]["seq"])


def test_slice_broken_linkage_to_global_predecessor_detected():
    """A row whose prev_hash no longer matches its global predecessor
    (e.g. an earlier row was tampered/restamped inconsistently)."""
    led = InMemoryLedger()
    led.append(episode_id="a", event={"i": 0})  # seq 1, genesis link
    led.append(episode_id="b", event={"i": 1})  # seq 2
    led.append(episode_id="a", event={"i": 2})  # seq 3, links to seq 2
    rows = _rows_with_global(led)
    a_rows = [r for r in rows if r["episode_id"] == "a"]
    # The chain's first row must link to genesis; pretend seq 1 was restamped
    # so its stored prev_hash no longer equals genesis.
    a_rows[0]["prev_hash"] = "e" * 64
    ok, bad, _ = _check_slice_rows(a_rows)
    assert not ok and bad == int(a_rows[0]["seq"])


def test_slice_first_row_genesis_link():
    led = InMemoryLedger()
    led.append(episode_id="a", event={"i": 0})
    rows = _rows_with_global(led)
    assert rows[0]["prev_hash"] == GENESIS_PREV
    ok, _, checked = _check_slice_rows(rows)
    assert ok and checked == 1


def test_slice_hash_rule_matches_text_rule():
    """The self-consistency check must use the same rule as append: over the
    STORED event text when present (jsonb-normalized), else the dict."""
    led = InMemoryLedger()
    led.append(episode_id="a", event={"b": 2, "a": 1})
    rows = _rows_with_global(led)
    r = rows[0]
    # canonical-dict path agrees with the stored hash
    assert compute_hash(int(r["seq"]), str(r["prev_hash"]), r["event"]) == r["hash"]
    # text path: a row whose hash was derived from its event_text verifies
    import json

    from reflex.ledger.chain import canonical_event

    text = canonical_event(r["event"]).decode("utf-8")
    assert text == json.dumps(r["event"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    h = compute_hash_text(int(r["seq"]), str(r["prev_hash"]), text)
    ok, _, _ = _check_slice_rows([dict(r, event_text=text, hash=h)])
    assert ok
    # and a stale hash under that text fails
    ok2, bad2, _ = _check_slice_rows([dict(r, event_text=text, hash="a" * 64)])
    assert not ok2 and bad2 == int(r["seq"])
