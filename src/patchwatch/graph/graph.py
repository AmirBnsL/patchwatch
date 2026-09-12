"""Monitor graph assembly + run entrypoint.

Linear Phase A pipeline with conditional routing:

    ingest --(no delta)--> END
    ingest --(delta)--> version_diff -> change_class
    change_class --(all neutral)--> END
    change_class --(any buff/nerf/uncertain)--> reindex -> END

Checkpointed with ``MemorySaver`` (dev); Postgres saver replaces it in Phase C.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from patchwatch.graph.nodes import (
    GraphDeps,
    change_class,
    ingest,
    new_run_id,
    reindex,
    version_diff,
)
from patchwatch.graph.state import ACTIONABLE, MonitorState


def _route_after_ingest(state: MonitorState) -> str:
    return "version_diff" if state["deltas"] else END


def _route_after_classify(state: MonitorState) -> str:
    if any(candidate.change_class in ACTIONABLE for candidate in state["candidates"]):
        return "reindex"
    return END


def build_graph(deps: GraphDeps) -> CompiledStateGraph[MonitorState, Any, Any, Any]:
    """Compile the monitor graph with an in-memory checkpointer."""
    graph = StateGraph(MonitorState)
    graph.add_node("ingest", lambda state: ingest(state, deps))
    graph.add_node("version_diff", lambda state: version_diff(state, deps))
    graph.add_node("change_class", lambda state: change_class(state, deps))
    graph.add_node("reindex", lambda state: reindex(state, deps))

    graph.add_edge(START, "ingest")
    graph.add_conditional_edges(
        "ingest", _route_after_ingest, {"version_diff": "version_diff", END: END}
    )
    graph.add_edge("version_diff", "change_class")
    graph.add_conditional_edges(
        "change_class", _route_after_classify, {"reindex": "reindex", END: END}
    )
    graph.add_edge("reindex", END)

    return graph.compile(checkpointer=MemorySaver())


def run_monitor(
    deps: GraphDeps,
    source: str,
    run_id: str | None = None,
    patch_from: str | None = None,
    patch_to: str | None = None,
) -> dict[str, Any]:
    """Run one monitor pass; returns the final state (for summaries/eval)."""
    run_id = run_id or new_run_id()
    graph = build_graph(deps)
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    initial: MonitorState = {
        "run_id": run_id,
        "source": source,
        "patch_from": patch_from,
        "patch_to": patch_to,
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "reindexed": False,
        "log": [],
    }
    return cast(dict[str, Any], graph.invoke(initial, config))
