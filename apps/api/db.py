"""DB engine/session helpers. Agent connections use the locked reflex_agent role."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from reflex.core.settings import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def agent_engine():  # type: ignore[no-untyped-def]
    url = get_settings().database_url
    # Only fallback to SQLite if host is exactly postgres/localhost (local compose) and not resolvable on Antideploy Node build
    # Don't fallback for Neon/cloud hosts (e.g., ep-...neon.tech) which contain postgres in scheme but host is resolvable
    if "sqlite" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    try:
        import socket

        host = url.split("@")[-1].split("/")[0].split(":")[0] if "@" in url else ""
        # Only check local docker hosts, not cloud hosts
        if host in ("postgres", "localhost", "127.0.0.1"):
            socket.getaddrinfo(host, 5432, timeout=1)
    except Exception:
        return create_engine("sqlite:///./reflex-cloud.db", connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


@lru_cache
def eval_engine():  # type: ignore[no-untyped-def]
    # Proof runs up to 8 parallel arm-transactions on this engine; each holds
    # one connection for the whole arm — the pool must cover the worker count.
    return create_engine(
        get_settings().database_url_eval,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=6,
        pool_timeout=60,
    )


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

    url = get_settings().redis_url
    # Antideploy Node build has no redis:6379 host - fallback to in-memory fake for demo
    if "redis" in url:
        try:
            import socket

            host = url.split("@")[-1].split("/")[0].split(":")[0].split(",")[0] if "@" in url else url.split("://")[-1].split(":")[0].split("/")[0]
            # host is like redis or localhost
            if host in ("redis", "localhost", "127.0.0.1"):
                socket.getaddrinfo(host, 6379, timeout=1)
        except Exception:
            # Return in-memory fake that mimics Redis for counters/pubsub
            class _FakeRedis:
                def __init__(self):
                    self._data = {}
                    self._pub = []

                def get(self, k):
                    return self._data.get(k)

                def set(self, k, v, *a, **kw):
                    self._data[k] = str(v) if isinstance(v, bytes) else v

                def setex(self, k, ttl, v):
                    self._data[k] = str(v)

                def incr(self, k):
                    self._data[k] = str(int(self._data.get(k, "0")) + 1)
                    return int(self._data[k])

                def publish(self, *a, **kw):
                    return 0

                def pubsub(self):
                    class _Pub:
                        def subscribe(self, *a, **kw):
                            pass

                        def get_message(self, *a, **kw):
                            return None

                        def close(self):
                            pass

                    return _Pub()

                def xadd(self, *a, **kw):
                    return "0-0"

                def get_connection(self, *a, **kw):
                    raise Exception("fake")

            return _FakeRedis()  # type: ignore[return-value]
    return redis.Redis.from_url(url, decode_responses=True)
