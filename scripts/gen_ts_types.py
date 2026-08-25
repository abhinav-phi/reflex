"""Generate TS types from Pydantic schemas (Rules §8.2: single source of truth)."""

from __future__ import annotations

from pathlib import Path

from reflex.core import schemas as S

OUT = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "lib" / "api.generated.ts"

PRIMITIVES = {"int": "number", "float": "number", "str": "string", "bool": "boolean"}


def pydantic_to_ts() -> str:
    lines = ["// GENERATED from packages/core/schemas.py — do not hand-edit (Rules §8.2).", ""]
    for name, model in vars(S).items():
        if not (isinstance(model, type) and hasattr(model, "model_fields")):
            continue
        if name in ("BaseModel",):
            continue
        lines.append(f"export interface {name} {{")
        for fname, f in model.model_fields.items():
            ann = str(f.annotation)
            ts = "unknown"
            for k, v in PRIMITIVES.items():
                if k in ann:
                    ts = v
                    break
            if "Literal" in ann or "str" in ann:
                ts = "string"
            if "datetime" in ann:
                ts = "string"
            if "List[" in ann or "list[" in ann:
                inner = "unknown"
                ts = f"{inner}[]"
            optional = not f.is_required()
            lines.append(f"  {fname}{'' if not optional else '?'}: {ts};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT.write_text(pydantic_to_ts(), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
