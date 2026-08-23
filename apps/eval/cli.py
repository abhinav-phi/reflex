"""Proof CLI: reflex-eval <smoke|run> — smoke is non-official, run enforces the tag."""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(prog="reflex-eval")
    parser.add_argument("command", choices=["smoke", "run"])
    parser.add_argument("--n", type=int, default=None, help="override episodes per batch")
    args = parser.parse_args()

    from reflex.eval.runner import run_protocol_sync

    if args.command == "smoke":
        summary = run_protocol_sync(
            quick=True,
            config_override={"n": args.n} if args.n else None,
        )
    else:
        summary = run_protocol_sync(config_override={"n": args.n} if args.n else None)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
