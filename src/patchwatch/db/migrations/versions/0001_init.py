"""Initial schema: versioned corpus + monitor/state tables (SPEC §5).

Revision ID: 0001
Revises:
Create Date: 2026-08-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE documents (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source        TEXT NOT NULL,          -- 'ddragon' | 'patch-notes' | 'fixture'
            external_id   TEXT,                   -- upstream doc id/url
            title         TEXT,
            version       TEXT,                   -- e.g. 'v2' or '2026-03-14'
            content_hash  TEXT NOT NULL,          -- sha256 of normalized source text
            fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (source, external_id, version)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE chunks (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id   UUID REFERENCES documents(id),
            chunk_index   INT,
            content       TEXT NOT NULL,
            embedding     vector(1536),           -- pinned to Settings.embedding_dim
            valid_from    TIMESTAMPTZ NOT NULL,   -- when this version became authoritative
            valid_to      TIMESTAMPTZ,            -- NULL = current
            source_hash   TEXT,                   -- chunk-level content hash
            UNIQUE (document_id, chunk_index, valid_from)
        )
        """
    )
    op.execute("CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)")

    op.execute(
        """
        CREATE TABLE runs (
            id               UUID PRIMARY KEY,
            started_at       TIMESTAMPTZ,
            finished_at      TIMESTAMPTZ,
            status           TEXT,                -- running | succeeded | failed | gated
            token_cost_cents NUMERIC,
            latency_ms       INTEGER,
            trace_id         TEXT
        )
        """
    )

    op.execute(
        """
        CREATE TABLE detected_changes (
            id            UUID PRIMARY KEY,
            run_id        UUID REFERENCES runs(id),
            document_id   UUID REFERENCES documents(id),
            old_version   TEXT,
            new_version   TEXT,
            diff_preview  TEXT,
            change_class  TEXT,                   -- meaningful | cosmetic
            severity      TEXT,                   -- low | medium | high | critical
            contradiction BOOLEAN,                -- old vs new disagree
            citation      JSONB,                  -- {chunk_ids, text spans}
            status        TEXT                    -- pending | approved | rejected
        )
        """
    )

    op.execute(
        """
        CREATE TABLE briefings (
            id             UUID PRIMARY KEY,
            run_id         UUID REFERENCES runs(id),
            change_id      UUID REFERENCES detected_changes(id),
            summary        TEXT,
            impact_points  JSONB,
            grounded_in    JSONB,                 -- retrieved chunk ids for audit
            requires_human BOOLEAN
        )
        """
    )

    op.execute(
        """
        CREATE TABLE eval_runs (
            id             UUID PRIMARY KEY,
            suite          TEXT,
            model          TEXT,
            prompt_version TEXT,
            metrics        JSONB,                 -- {precision, recall, faithfulness, ...}
            baseline       UUID,                  -- prior eval run id for regression diff
            created_at     TIMESTAMPTZ
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS eval_runs, briefings, detected_changes, runs, chunks, documents"
    )
    op.execute("DROP EXTENSION IF EXISTS vector")
