"""Money helpers. All money in the system is integer paise (Rules §5.1).

Formatting to ₹ happens client-side only; this module exists for server-side
logging/exports which must still render Indian digit grouping honestly.
"""

from __future__ import annotations

Paise = int  # branded alias; never floats (Rules §5.1)


def format_inr(paise: Paise) -> str:
    """₹2,41,000 — Indian digit grouping, sign-safe."""
    negative = paise < 0
    rupees = abs(paise) // 100
    p = abs(paise) % 100
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join([*groups, tail])
    out = f"₹{s}"
    if p:
        out += f".{p:02d}"
    return f"-{out}" if negative else out
