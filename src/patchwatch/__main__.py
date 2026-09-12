"""PatchWatch CLI entrypoint.

``python -m patchwatch monitor --source fixture`` — acceptance criterion §12.1.
"""

from __future__ import annotations

import typer

from patchwatch import __version__
from patchwatch.config import get_settings

app = typer.Typer(
    name="patchwatch",
    help="League of Legends patch-change monitoring agent.",
    no_args_is_help=True,
)


@app.command()
def monitor(
    source: str = typer.Option("fixture", help="Source to monitor (fixture)."),
    versions: str | None = typer.Option(
        None,
        help="Comma-separated fixture patch versions to publish (e.g. '26.6,26.7'). Default: all.",
    ),
) -> None:
    """Run the monitor pipeline (detect → diff → classify → re-index)."""
    if source != "fixture":
        raise typer.BadParameter(f"unsupported source {source!r} (only 'fixture' for now)")

    from patchwatch.db.connection import get_engine
    from patchwatch.db.repositories import DocumentRepository
    from patchwatch.fixtures.snapshot import SnapshotFetcher
    from patchwatch.graph.graph import run_monitor
    from patchwatch.graph.nodes import GraphDeps

    version_set = {v.strip() for v in versions.split(",") if v.strip()} if versions else None
    deps = GraphDeps(
        fetcher=SnapshotFetcher(versions=version_set),
        repo=DocumentRepository(get_engine()),
    )
    result = run_monitor(deps, source=source)

    typer.echo(f"run_id={result['run_id']}")
    typer.echo(
        f"fetched={len(result['fetched'])} changed={len(result['deltas'])} "
        f"candidates={len(result['candidates'])} reindexed={result['reindexed']}"
    )
    for line in result["log"]:
        typer.echo(f"  {line}")
    for candidate in result["candidates"]:
        doc_ref = candidate.document_id or "(new)"
        typer.echo(
            f"  chunk[{candidate.chunk_index}] class={candidate.change_class} "
            f"similarity={candidate.similarity:.4f} doc={doc_ref}"
        )


@app.command()
def info() -> None:
    """Print effective configuration (no secrets)."""
    settings = get_settings()
    typer.echo(f"version={__version__}")
    typer.echo(f"database_url={settings.database_url}")
    typer.echo(f"embedding_model={settings.embedding_model} (dim {settings.embedding_dim})")
    typer.echo(f"llm_model={settings.llm_model}")


if __name__ == "__main__":
    app()
