"""Generator determinism (FR-002) + demo slice contract (Schema §13)."""

from reflex.eval.generator import (
    DEMO_HIGH_VALUE_PAISE,
    DEMO_N,
    DEMO_TOTAL_PAISE,
    generate_batch,
)


def test_same_seed_byte_identical():
    b1 = generate_batch(seed=42, n=200)
    b2 = generate_batch(seed=42, n=200)
    assert b1.fingerprint() == b2.fingerprint()


def test_different_seed_differs():
    a = generate_batch(seed=42, n=100)
    b = generate_batch(seed=1337, n=100)
    assert a.fingerprint() != b.fingerprint()


def test_demo_slice_contract():
    b = generate_batch(seed="demo-7", n=DEMO_N, demo=True)
    assert len(b.events) == DEMO_N
    total = sum(e.amount_paise for e in b.events)
    assert total == DEMO_TOTAL_PAISE, f"demo total {total} != {DEMO_TOTAL_PAISE}"
    assert any(e.amount_paise == DEMO_HIGH_VALUE_PAISE for e in b.events), "₹48,000 case missing"
    complaint_trajs = [e for e in b.events if e.force_complaint_reply_at is not None]
    assert len(complaint_trajs) == 1, "exactly one pre-seeded complaint trajectory"
    # byte-identical regeneration
    b2 = generate_batch(seed="demo-7", n=DEMO_N, demo=True)
    assert b.fingerprint() == b2.fingerprint()
