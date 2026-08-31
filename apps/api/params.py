"""Shared path/query parameter validation for API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException


def require_uuid(value: str, field: str = "id") -> str:
    """422 on malformed identifiers instead of an unhandled 500 from the DB cast.

    Path/query ids reach SQL as `CAST(:x AS uuid)`; a malformed value raises a
    DataError deep in the handler. Validate at the boundary so clients get a
    proper 422 (well-formed-but-missing still 404s downstream).
    """
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=422, detail=f"invalid {field}: must be a UUID"
        ) from None
    return value
