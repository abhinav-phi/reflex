"""Reflex — bounded, root-cause-diagnosing payment-recovery agent.

Razorpay AI Buildathon Track 03 (AI Revenue Recovery).
Six subsystems: Pulse · Brain · Shield · Hands · Ledger · Proof.
Governing principle: AI proposes, deterministic code disposes.

DO NOT DELETE this root package marker: pyproject.toml declares the bare
"reflex" distribution package, and `pip install -e .` fails to build without
this directory (CI backend job breaks at the install step).
"""

__version__ = "1.0.0"
