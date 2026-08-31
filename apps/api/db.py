"""DB engine/session helpers. Agent connections use the locked reflex_agent role."""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from reflex.core.settings import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _resolve_cloud_db(url: str, env_key: str) -> str:
    """`localhost:15432` is only the baked-in docker-compose dev default.

    Compose and CI always set DATABASE_URL* explicitly, so any run that reaches
    that host WITHOUT env vars (Railway/Render/Antideploy zero-config) has no
    Postgres there — hand it the bundled SQLite instead of dialing a refusal.
    """
    if "localhost:15432" in url and not os.environ.get(env_key):
        return "sqlite:///./reflex-cloud.db"
    return url


@lru_cache
def agent_engine():  # type: ignore[no-untyped-def]
    url = _resolve_cloud_db(get_settings().database_url, "DATABASE_URL")
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
    # connect_timeout: a transiently unreachable Postgres must fail in seconds,
    # not hang startup past the platform healthcheck.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10,
                         connect_args={"connect_timeout": 10})


@lru_cache
def eval_engine():  # type: ignore[no-untyped-def]
    # Proof runs up to 8 parallel arm-transactions on this engine; each holds
    # one connection for the whole arm — the pool must cover the worker count.
    url = _resolve_cloud_db(get_settings().database_url_eval, "DATABASE_URL_EVAL")
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    if "sqlite" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=6,
        pool_timeout=60,
        connect_args={"connect_timeout": 10},
    )


@lru_cache
def admin_engine():  # type: ignore[no-untyped-def]
    url = _resolve_cloud_db(get_settings().database_url_admin, "DATABASE_URL_ADMIN")
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    if "sqlite" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


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


_FAKE_REDIS_SINGLETON: object | None = None


def get_redis():  # type: ignore[no-untyped-def]
    import os

    import redis

    # If the platform did not provide a REDIS_URL (e.g. Antideploy), use the
    # in-memory fake instead of pointing a real client at a dead localhost:6379.
    if not os.environ.get("REDIS_URL"):
        global _FAKE_REDIS_SINGLETON
        if _FAKE_REDIS_SINGLETON is None:
            _FAKE_REDIS_SINGLETON = _make_fake_redis()
        return _FAKE_REDIS_SINGLETON  # type: ignore[return-value]

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
                return _make_fake_redis()  # type: ignore[return-value]
    return redis.Redis.from_url(url, decode_responses=True)


def _make_fake_redis():  # type: ignore[no-untyped-def]
    """In-memory fake that mimics Redis for counters/pubsub/streams (cloud deploys).

    Antideploy runs a single API container with no Redis broker and no separate
    worker processes, so the worker loops run as threads inside the API (see
    main.py embedded_workers). Those loops need the Redis Streams API
    (xgroup_create/xreadgroup/xack/xdel) plus the plain key ops below.
    """

    class _FakeRedis:
        def __init__(self):
            self._data = {}
            self._streams: dict[str, list] = {}  # name -> [(msg_id, fields)]
            self._groups: dict[tuple, dict] = {}  # (name, group) -> {consumer: set(msg_ids)}
            self._seq = 0

        def get(self, k):
            return self._data.get(k)

        def set(self, k, v, *a, **kw):
            self._data[k] = str(v) if isinstance(v, bytes) else v

        def setex(self, k, ttl, v):
            self._data[k] = str(v)

        def delete(self, *keys):
            for k in keys:
                self._data.pop(k, None)
                self._streams.pop(k, None)
            return len(keys)

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

        # ---- Redis Streams (embedded workers) ---------------------------------
        def xadd(self, stream, fields, *a, **kw):
            self._seq += 1
            self._streams.setdefault(stream, []).append((f"{self._seq}-0", fields))
            return f"{self._seq}-0"

        def xgroup_create(self, stream, group, id="0", mkstream=True):  # type: ignore[no-untyped-def]
            key = (stream, group)
            if key not in self._groups:
                self._groups[key] = {}
            return True

        def xreadgroup(self, group, consumer, streams, count=None, block=0):  # type: ignore[no-untyped-def]
            out = []
            for stream, _marker in (streams or {}).items():
                entries = self._streams.get(stream, [])
                pending = self._groups.setdefault((stream, group), {}).setdefault(consumer, set())
                unread = [(mid, f) for mid, f in entries if mid not in pending]
                picked = unread[: (count or 10)]
                for mid, _ in picked:
                    pending.add(mid)
                if picked:
                    out.append((stream, picked))
            return out

        def xack(self, stream, group, *ids):
            pend = self._groups.setdefault((stream, group), {}).setdefault("_ack", set())
            for mid in ids:
                pend.add(mid)
            # drop acked entries from every consumer's pending set
            for consumers in self._groups.get((stream, group), {}).values():
                consumers.difference_update(ids)
            return len(ids)

        def xdel(self, stream, *ids):
            entries = self._streams.get(stream, [])
            self._streams[stream] = [e for e in entries if e[0] not in ids]
            return len(ids)

        def get_connection(self, *a, **kw):
            raise Exception("fake")

    return _FakeRedis()
