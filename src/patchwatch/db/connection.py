"""SQLAlchemy engine for the Postgres/pgvector database."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from patchwatch.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the (cached) application engine, created from Settings."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def dispose_engine() -> None:
    """Dispose the cached engine (used by tests to reset state)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
