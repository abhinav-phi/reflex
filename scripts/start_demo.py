"""Start the 5-minute demo slice (AppFlow §13): 214 eps / ₹2,41,000 / seed demo-7 / ×100.

Launches the reflex arm + b1 twin through the LIVE API so counters compare arms.
Requires the runtime stack: uvicorn + workers (make up).
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("REFLEX_API", "http://localhost:8899")


def main() -> int:
    login = httpx.post(
        f"{BASE}/api/auth/login",
        json={"email": "operator@reflex.dev", "password": "reflex-demo"},
        timeout=30,
    )
    if login.status_code != 200:
        print("login failed:", login.text)
        return 1
    token = login.json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    r = httpx.post(
        f"{BASE}/api/replay/start",
        json={"n": 214, "seed": "demo-7", "arm": "reflex", "speed": 100.0, "demo": True},
        headers=h,
        timeout=60,
    )
    if r.status_code != 200:
        print("replay start failed:", r.text)
        return 1
    print("demo slice started:", r.json())
    print("dashboard → http://localhost:5173/dashboard")

    # wait for feed completion (×100 ⇒ ~36h sim ≈ 21 min real; stream live meanwhile)
    deadline = time.time() + 60 * 90
    while time.time() < deadline:
        time.sleep(15)
        m = httpx.get(f"{BASE}/api/metrics/live", headers=h, timeout=30).json()
        print(
            f"failed ₹{m['failed_today_paise']/100:,.0f} · reflex ₹{m['recovered_reflex_paise']/100:,.0f}"
            f" · naive ₹{m['recovered_b1_paise']/100:,.0f} · mode {m['mode']}",
            flush=True,
        )
        if m.get("episodes_open", 1) == 0:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
