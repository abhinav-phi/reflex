"""Load gate (TechSpec §18): 5k burst with 40% dupes — zero dup episodes."""

import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from reflex.api.db import eval_sessionmaker
from reflex.api.ingest_service import ingest_event
from reflex.core.enums import EventSource
from reflex.eval.seed import ensure_reference_data


@pytest.mark.load
@pytest.mark.integration
def test_burst_5k_with_dupes(clean_db):  # type: ignore[no-untyped-def]
    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        base = datetime.now(timezone.utc).replace(microsecond=0)

        def norm(i: int) -> dict:
            return {
                "provider_event_id": f"burst_{i}",
                "event": "payment.failed",
                "rail": "upi",
                "code_raw": "NSF - insufficient funds in account",
                "amount_paise": 19900,
                "occurred_at": base,
                "raw_payload": {"simulated": True},
                "customer_ref": f"idx:{i % 500}",
            }

        t0 = time.perf_counter()
        latencies = []
        for i in range(5000):
            idx = i % 3000 if i >= 3000 else i  # last 2000 are 66% dupes
            t1 = time.perf_counter()
            ingest_event(s, source=EventSource.REPLAY, normalized=norm(idx), now_sim=base)
            latencies.append(time.perf_counter() - t1)
        wall = time.perf_counter() - t0
        s.commit()

        eps = s.execute(text("SELECT count(*) FROM runtime.episodes")).scalar()
        events = s.execute(text("SELECT count(*) FROM runtime.payment_events")).scalar()
        assert events == 3000 and eps == 3000  # zero duplicate episodes

        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        print(f"wall={wall:.2f}s p95={p95*1000:.1f}ms")
        assert p95 < 0.8, f"ingestion p95 {p95*1000:.1f}ms exceeds 800ms budget"
    finally:
        s.close()
