"""Postgres checkpoint backend for HITL resume (SPEC §6.3 / §13)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver

from patchwatch.config import get_settings


def checkpoint_conn_string() -> str:
    """psycopg (non-SQLAlchemy-dialect) URL for the checkpoint saver."""
    return get_settings().database_url.replace("+psycopg", "")


@contextmanager
def postgres_checkpointer() -> Iterator[BaseCheckpointSaver[Any]]:
    """Yield a set-up Postgres checkpointer (creates checkpoint tables once)."""
    with PostgresSaver.from_conn_string(checkpoint_conn_string()) as checkpointer:
        checkpointer.setup()
        yield checkpointer
