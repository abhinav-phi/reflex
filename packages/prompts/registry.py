"""Versioned prompt registry (Rules §2.7: prompts are versioned artifacts).

Every LLM call records prompt_hash (sha256 of template text) in runtime.llm_calls.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# name → current version file. Changing a prompt requires an eval-suite run in the PR.
PROMPTS: dict[str, str] = {
    "diagnosis": "diagnosis_v3.txt",
    "message": "message_v1.txt",
    "reply_classify": "reply_classify_v2.txt",  # v2: confidence output (TASK-054)
}


@lru_cache(maxsize=None)
def load(name: str) -> str:
    fname = PROMPTS.get(name)
    if fname is None:
        raise KeyError(f"unknown prompt: {name}")
    return (_TEMPLATES_DIR / fname).read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    return hashlib.sha256(load(name).encode("utf-8")).hexdigest()[:16]


def version_of(name: str) -> str:
    return PROMPTS[name].rsplit(".", 1)[0]


def render(name: str, **kwargs: Any) -> str:
    return load(name).format(**kwargs)


def wrap_data(untrusted: Any) -> str:
    """Wrap untrusted text as data-not-instructions (TechSpec §7)."""
    if isinstance(untrusted, dict):
        import json

        body = json.dumps(untrusted, ensure_ascii=False)
    else:
        body = str(untrusted)
    return f"<data>{body}</data>"
