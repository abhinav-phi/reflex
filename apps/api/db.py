"""DB engine/session helpers. Agent connections use the locked reflex_agent role."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from reflex.core.settings import get_settings


@lru_cache
def agent_engine():  # type: ignore[no-untyped-def]
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


@lru_cache
def eval_engine():  # type: ignore[no-untyped-def]
    return create_engine(get_settings().database_url_eval, pool_pre_ping=True)


@lru_cache
def admin_engine():  # type: ignore[no-untyped-def]
    return create_engine(get_settings().database_url_admin, pool_pre_ping=True)


@lru_cache
def agent_sessionmaker():  # type: ignore[no-untyped-def]
    return sessionmaker(bind=agent_engine(), expire_on_commit=False)


@lru_cache
def eval_sessionmaker():  # type: ignore[no-untyped-def]
    return sessionmaker(bind=eval_engine(), expire_on_commit=False)


def agent_session() -> Iterator[Session]:
    s = agent_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_redis():  # type: ignore[no-untyped-def]
    import redis

    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
