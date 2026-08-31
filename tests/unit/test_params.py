"""require_uuid boundary validation: malformed ids must 422, valid ones pass.

Kept as pure unit tests on purpose: client-fixture API tests spin embedded
worker lifecycles whose background threads can race the load gate (a stray
late ingest shifted the burst test's episode count by exactly one), so these
checks deliberately avoid spinning the app.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from reflex.api.params import require_uuid


def test_malformed_id_raises_422() -> None:
    for bad in ("not-a-uuid", "", "1", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"):
        with pytest.raises(HTTPException) as exc:
            require_uuid(bad, "episode_id")
        assert exc.value.status_code == 422
        assert "episode_id" in str(exc.value.detail)


def test_valid_id_passes_through_unchanged() -> None:
    good = str(uuid4())
    assert require_uuid(good, "episode_id") == good
    # hyphen-less canonical form is still a valid UUID
    assert require_uuid(good.replace("-", ""), "id") == good.replace("-", "")


def test_non_string_input_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        require_uuid(12345, "id")  # type: ignore[arg-type]
    assert exc.value.status_code == 422
