"""Proof CLI: reflex-eval <smoke|run> — smoke is non-official, run enforces the tag."""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(prog="reflex-eval")
    parser.add_argument("command", choices=["smoke", "run"])
    parser.add_argument("--n", type=int, default=None, help="override episodes per batch")
    parser.add_argument(
        "--seeds", type=str, default=None,
        help="comma-separated seed list override, e.g. --seeds 42 (chunked/resumable official runs)",
    )
    parser.add_argument(
        "--parallel", type=int, default=None,
        help="override concurrent arm workers (official runs default to 1: serial arms avoid cross-arm deadlocks)",
    )
    args = parser.parse_args()

    from reflex.eval.runner import run_protocol_sync

    override: dict = {}
    if args.n:
        override["n"] = args.n
    if args.parallel:
        override["parallel"] = args.parallel
    if args.seeds:
        override["seeds"] = [int(x) for x in args.seeds.split(",")]

    if args.command == "smoke":
        summary = run_protocol_sync(quick=True, config_override=override or None)
    else:
        summary = run_protocol_sync(config_override=override or None)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
