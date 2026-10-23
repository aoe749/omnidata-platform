"""One SQLAlchemy engine (= one connection pool) per database engine.

Engines are created lazily and exactly once per process. ``pool_pre_ping``
transparently replaces connections dropped by a server restart, and
``pool_recycle`` keeps them younger than typical firewall idle timeouts.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class DatabaseRegistry:
    """The three pools, passed explicitly to services (easy to fake in tests)."""

    mssql: Engine
    postgres: Engine
    mysql: Engine

    def dispose(self) -> None:
        for engine in (self.mssql, self.postgres, self.mysql):
            engine.dispose()


def _build_engine(url: URL, settings: Settings) -> Engine:
    return create_engine(
        url,
        pool_size=settings.pool_size,
        max_overflow=settings.pool_max_overflow,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
    )


@lru_cache
def get_registry() -> DatabaseRegistry:
    settings = get_settings()
    return DatabaseRegistry(
        mssql=_build_engine(settings.mssql_url, settings),
        postgres=_build_engine(settings.postgres_url, settings),
        mysql=_build_engine(settings.mysql_url, settings),
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transaction boundary: commit on success, roll back on any exception."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
