"""Integration tests against the compose Postgres (pgvector + migrations).

Skipped automatically when Postgres is not reachable. Run with:
    docker compose up -d
    uv run pytest -m integration
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from patchwatch.config import get_settings

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "documents",
    "chunks",
    "runs",
    "detected_changes",
    "briefings",
    "eval_runs",
}


@pytest.fixture(scope="module")
def engine() -> Engine:
    db = create_engine(get_settings().database_url)
    try:
        with db.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised when DB is down
        pytest.skip(f"Postgres not reachable: {exc}")
    return db


def test_migrations_applied(engine: Engine) -> None:
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
    assert tables >= EXPECTED_TABLES


def test_chunks_vector_column_and_hnsw(engine: Engine) -> None:
    with engine.connect() as conn:
        udt = conn.execute(
            text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'chunks' AND column_name = 'embedding'"
            )
        ).scalar_one()
        indexdefs = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'chunks'")
        ).scalars()
    assert udt == "vector"
    assert any("hnsw" in idx and "vector_cosine_ops" in idx for idx in indexdefs)


def test_documents_unique(engine: Engine) -> None:
    with engine.connect() as conn:
        constraints = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'documents'::regclass"
            )
        ).scalars()
    assert any("UNIQUE (source, external_id, version)" in c for c in constraints)
