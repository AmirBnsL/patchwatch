"""PatchWatch CLI entrypoint.

``python -m patchwatch monitor --source fixture`` — the frozen mini-corpus demo.
``python -m patchwatch monitor --source ddragon --patch 16.18.1`` — real frozen
Data Dragon patches (bootstrap oldest first, then step forward).
``python -m patchwatch resume <run_id> --decision approved`` — HITL resume.
"""

from __future__ import annotations

from collections.abc import Iterator
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
        f"candidates={len(result['candidates'])} briefs={len(result['briefs'])} "
        f"approval={result['approval']} reindexed={result['reindexed']}"
    )
    for line in result["log"]:
        typer.echo(f"  {line}")
    for candidate in result["candidates"]:
        if candidate.kind == "numeric":
            typer.echo(
                f"  {candidate.field}: {candidate.old_text} -> {candidate.new_text} "
                f"[{candidate.change_class}]"
            )
    for brief in result["briefs"]:
        typer.echo(f"  brief: {brief.summary}")


def _recorder_and_checkpointer(
    recording: bool = True,
) -> Iterator[tuple[Any, Any]]:
    """Build (recorder, checkpointer) — Postgres checkpointer when reachable."""
    from langgraph.checkpoint.memory import MemorySaver

    from patchwatch.db.connection import get_engine
    from patchwatch.db.repositories import DocumentRepository
    from patchwatch.observability.runs import RunRecorder

    recorder = RunRecorder(DocumentRepository(get_engine())) if recording else None
    try:
        from patchwatch.graph.checkpointing import postgres_checkpointer

        with postgres_checkpointer() as checkpointer:
            yield recorder, checkpointer
        return
    except Exception:  # noqa: BLE001 - fall back to memory checkpointing
        yield recorder, MemorySaver()


@app.command()
def monitor(
    source: str = typer.Option("fixture", help="Source to monitor (fixture | ddragon)."),
    versions: str | None = typer.Option(
        None, help="fixture only: comma-separated patch versions to publish."
    ),
    patch: str | None = typer.Option(
        None, help="ddragon only: frozen patch version to ingest (e.g. 16.18.1)."
    ),
    no_record: bool = typer.Option(False, help="Skip run persistence (debug)."),
) -> None:
    """Run the monitor pipeline (detect → diff → classify → brief → gate → reindex)."""
    for recorder, checkpointer in _recorder_and_checkpointer(recording=not no_record):
        from patchwatch.graph.graph import run_monitor
        from patchwatch.graph.nodes import GraphDeps

        if source == "fixture":
            from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, SnapshotFetcher

            version_set = (
                {v.strip() for v in versions.split(",") if v.strip()} if versions else None
            )
            deps = GraphDeps(
                fetcher=SnapshotFetcher(versions=version_set),
                repo=_deps_repo(recorder),
                brief_generator=_brief_generator(),
                pool=_pool(),
            )
            result = run_monitor(
                deps, source=FIXTURE_SOURCE, checkpointer=checkpointer, recorder=recorder
            )
        elif source == "ddragon":
            from patchwatch.fixtures.manifest import load_manifest
            from patchwatch.ingest.frozen import (
                DDAGON_SOURCE,
                FrozenCorpusFetcher,
                FrozenDigestLoader,
            )

            if patch is None:
                raise typer.BadParameter("--patch is required for --source ddragon")
            manifest = load_manifest()
            if patch not in manifest.versions:
                raise typer.BadParameter(
                    f"patch {patch!r} not frozen (corpus: {manifest.versions})"
                )
            index = manifest.versions.index(patch)
            patch_from = manifest.versions[index - 1] if index > 0 else None
            deps = GraphDeps(
                fetcher=FrozenCorpusFetcher(patch),
                repo=_deps_repo(recorder),
                digest_loader=FrozenDigestLoader(),
                brief_generator=_brief_generator(),
                pool=_pool(),
            )
            result = run_monitor(
                deps,
                source=DDAGON_SOURCE,
                patch_from=patch_from,
                patch_to=patch,
                checkpointer=checkpointer,
                recorder=recorder,
            )
            typer.echo(f"patch window: {patch_from or '(bootstrap)'} -> {patch}")
        else:
            raise typer.BadParameter(f"unsupported source {source!r} (fixture | ddragon)")

        _print_summary(result)


@app.command()
def resume(
    run_id: str = typer.Argument(help="The gated run's id (thread id)."),
    decision: str = typer.Option(..., help="approved | rejected"),
) -> None:
    """Resume a HITL-gated run from its Postgres checkpoint."""
    if decision not in ("approved", "rejected"):
        raise typer.BadParameter("decision must be 'approved' or 'rejected'")
    from langgraph.types import Command

    from patchwatch.graph.graph import build_graph
    from patchwatch.graph.nodes import GraphDeps

    for _recorder, checkpointer in _recorder_and_checkpointer(recording=False):
        deps = GraphDeps(
            fetcher=_noop_fetcher(),
            repo=_deps_repo(None),
            brief_generator=_brief_generator(),
            pool=_pool(),
        )
        graph = build_graph(deps, checkpointer)
        result = graph.invoke(Command(resume=decision), {"configurable": {"thread_id": run_id}})
        _print_summary(result)


def _deps_repo(recorder: object) -> Any:
    from patchwatch.db.connection import get_engine
    from patchwatch.db.repositories import DocumentRepository

    return DocumentRepository(get_engine())


def _brief_generator() -> Any:
    from patchwatch.graph.brief import TemplateBriefGenerator

    return TemplateBriefGenerator()


def _pool() -> Any:
    from patchwatch.fixtures.pool import DEFAULT_POOL

    return DEFAULT_POOL


def _noop_fetcher() -> Any:
    from patchwatch.fixtures.snapshot import FIXTURE_SOURCE, SnapshotDocument

    class _Empty:
        def fetch(self, source: str) -> list[SnapshotDocument]:
            if source != FIXTURE_SOURCE:
                raise ValueError(f"unsupported source: {source!r}")
            return []  # resume never re-fetches; state comes from the checkpoint

    return _Empty()


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
