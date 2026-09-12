"""PatchWatch CLI entrypoint.

``python -m patchwatch monitor --source fixture`` — the frozen mini-corpus demo.
``python -m patchwatch monitor --source ddragon --patch 16.18.1`` — real frozen
Data Dragon patches (bootstrap oldest first, then step forward).
"""

from __future__ import annotations

from typing import Any

import typer

from patchwatch import __version__
from patchwatch.config import get_settings

app = typer.Typer(
    name="patchwatch",
    help="League of Legends patch-change monitoring agent.",
    no_args_is_help=True,
)


def _print_summary(result: dict[str, Any]) -> None:
    typer.echo(f"run_id={result['run_id']}")
    typer.echo(
        f"fetched={len(result['fetched'])} changed={len(result['deltas'])} "
        f"candidates={len(result['candidates'])} reindexed={result['reindexed']}"
    )
    for line in result["log"]:
        typer.echo(f"  {line}")
    for candidate in result["candidates"]:
        doc_ref = candidate.document_id or "(new)"
        if candidate.kind == "numeric":
            typer.echo(
                f"  {candidate.field}: {candidate.old_text} -> {candidate.new_text} "
                f"[{candidate.change_class}] doc={doc_ref}"
            )
        else:
            typer.echo(
                f"  chunk[{candidate.chunk_index}] class={candidate.change_class} "
                f"similarity={candidate.similarity:.4f} doc={doc_ref}"
            )


@app.command()
def monitor(
    source: str = typer.Option("fixture", help="Source to monitor (fixture | ddragon)."),
    versions: str | None = typer.Option(
        None, help="fixture only: comma-separated patch versions to publish."
    ),
    patch: str | None = typer.Option(
        None, help="ddragon only: frozen patch version to ingest (e.g. 16.18.1)."
    ),
) -> None:
    """Run the monitor pipeline (detect → diff → classify → re-index)."""
    from patchwatch.db.connection import get_engine
    from patchwatch.db.repositories import DocumentRepository
    from patchwatch.graph.graph import run_monitor
    from patchwatch.graph.nodes import GraphDeps

    if source == "fixture":
        from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, SnapshotFetcher

        version_set = {v.strip() for v in versions.split(",") if v.strip()} if versions else None
        deps = GraphDeps(
            fetcher=SnapshotFetcher(versions=version_set),
            repo=DocumentRepository(get_engine()),
        )
        result = run_monitor(deps, source=FIXTURE_SOURCE)
    elif source == "ddragon":
        from patchwatch.fixtures.manifest import load_manifest
        from patchwatch.ingest.frozen import DDAGON_SOURCE, FrozenCorpusFetcher, FrozenDigestLoader

        if patch is None:
            raise typer.BadParameter("--patch is required for --source ddragon")
        manifest = load_manifest()
        if patch not in manifest.versions:
            raise typer.BadParameter(f"patch {patch!r} not frozen (corpus: {manifest.versions})")
        index = manifest.versions.index(patch)
        patch_from = manifest.versions[index - 1] if index > 0 else None
        deps = GraphDeps(
            fetcher=FrozenCorpusFetcher(patch),
            repo=DocumentRepository(get_engine()),
            digest_loader=FrozenDigestLoader(),
        )
        result = run_monitor(deps, source=DDAGON_SOURCE, patch_from=patch_from, patch_to=patch)
        typer.echo(f"patch window: {patch_from or '(bootstrap)'} -> {patch}")
    else:
        raise typer.BadParameter(f"unsupported source {source!r} (fixture | ddragon)")

    _print_summary(result)


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
