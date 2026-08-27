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
    # Normalize to psycopg2 driver for CI and cloud (both have psycopg2-binary, psycopg scheme may not be available)
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    # Only fallback to SQLite for Antideploy Node builds where postgres host is not resolvable;
    # don't fallback for localhost in CI (CI's postgres is on localhost and should be used)
    if "sqlite" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    import socket

    host = url.split("@")[-1].split("/")[0].split(":")[0] if "@" in url else ""
    # Only check the Docker Compose service name `postgres`, not localhost (CI uses localhost)
    if host == "postgres":
        try:
            # getaddrinfo() has no timeout kwarg — passing one raises TypeError,
            # which used to trigger the SQLite fallback even when Postgres was up.
            socket.setdefaulttimeout(1.0)
            socket.getaddrinfo(host, 5432)
            socket.setdefaulttimeout(None)
        except socket.gaierror:
            return create_engine("sqlite:///./reflex-cloud.db", connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


@lru_cache
def eval_engine():  # type: ignore[no-untyped-def]
    # Proof runs up to 8 parallel arm-transactions on this engine; each holds
    # one connection for the whole arm — the pool must cover the worker count.
    url = get_settings().database_url_eval
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=6,
        pool_timeout=60,
    )


@lru_cache
def admin_engine():  # type: ignore[no-untyped-def]
    url = get_settings().database_url_admin
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_pre_ping=True)


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
        import socket

        host = url.split("@")[-1].split("/")[0].split(":")[0].split(",")[0] if "@" in url else url.split("://")[-1].split(":")[0].split("/")[0]
        # host is like redis or localhost
        if host in ("redis", "localhost", "127.0.0.1"):
            try:
                # getaddrinfo() has no timeout kwarg — passing one TypeError'd
                # and the broad except sent every container to the in-memory fake.
                socket.setdefaulttimeout(1.0)
                socket.getaddrinfo(host, 6379)
                socket.setdefaulttimeout(None)
            except socket.gaierror:
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
