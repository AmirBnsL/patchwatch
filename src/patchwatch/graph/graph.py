"""Monitor graph assembly + run entrypoint.

Linear Phase A/B pipeline with conditional routing:

    ingest --(no delta)--> END
    ingest --(delta)--> version_diff -> change_class
    change_class --(all neutral)--> END
    change_class --(any buff/nerf/uncertain)--> contradict_detect -> impact_brief -> hitl_gate
    hitl_gate --(approved/auto)--> reindex -> END
    hitl_gate --(rejected)--> END

Checkpointed with ``MemorySaver`` (dev); Postgres saver replaces it in Phase C.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from patchwatch.graph.nodes import (
    GraphDeps,
    change_class,
    contradict_detect,
    hitl_gate,
    impact_brief,
    ingest,
    new_run_id,
    reindex,
    version_diff,
)
from patchwatch.graph.state import ACTIONABLE, MonitorState
from patchwatch.observability.runs import RunRecorder, RunTimer, new_trace_id
from patchwatch.observability.tracing import traced_node


def _route_after_ingest(state: MonitorState) -> str:
    return "version_diff" if state["deltas"] else END


def _route_after_gate(state: MonitorState) -> str:
    return "reindex" if state["approval"] in ("auto-approved", "approved") else END


def _route_after_classify(state: MonitorState) -> str:
    if any(candidate.change_class in ACTIONABLE for candidate in state["candidates"]):
        return "contradict_detect"
    return END


def build_graph(
    deps: GraphDeps,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[MonitorState, Any, Any, Any]:
    """Compile the monitor graph (MemorySaver by default; Postgres saver in prod)."""
    graph = StateGraph(MonitorState)
    graph.add_node("ingest", traced_node("ingest", lambda state: ingest(state, deps)))
    graph.add_node(
        "version_diff", traced_node("version_diff", lambda state: version_diff(state, deps))
    )
    graph.add_node(
        "change_class", traced_node("change_class", lambda state: change_class(state, deps))
    )
    graph.add_node(
        "contradict_detect",
        traced_node("contradict_detect", lambda state: contradict_detect(state, deps)),
    )
    graph.add_node(
        "impact_brief", traced_node("impact_brief", lambda state: impact_brief(state, deps))
    )
    graph.add_node("hitl_gate", traced_node("hitl_gate", lambda state: hitl_gate(state, deps)))
    graph.add_node("reindex", traced_node("reindex", lambda state: reindex(state, deps)))

    graph.add_edge(START, "ingest")
    graph.add_conditional_edges(
        "ingest", _route_after_ingest, {"version_diff": "version_diff", END: END}
    )
    graph.add_edge("version_diff", "change_class")
    graph.add_conditional_edges(
        "change_class", _route_after_classify, {"contradict_detect": "contradict_detect", END: END}
    )
    graph.add_edge("contradict_detect", "impact_brief")
    graph.add_edge("impact_brief", "hitl_gate")
    graph.add_conditional_edges("hitl_gate", _route_after_gate, {"reindex": "reindex", END: END})
    graph.add_edge("reindex", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_monitor(
    deps: GraphDeps,
    source: str,
    run_id: str | None = None,
    patch_from: str | None = None,
    patch_to: str | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    recorder: RunRecorder | None = None,
) -> dict[str, Any]:
    """Run one monitor pass; records runs/changes/briefings when a recorder is wired."""
    run_id = run_id or new_run_id()
    trace_id = new_trace_id()
    timer = RunTimer()
    timer.start()
    if recorder is not None:
        recorder.start_run(run_id, trace_id)
    graph = build_graph(deps, checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    initial: MonitorState = {
        "run_id": run_id,
        "source": source,
        "patch_from": patch_from,
        "patch_to": patch_to,
        "fetched": [],
        "deltas": [],
        "candidates": [],
        "contradictions": [],
        "briefs": [],
        "approval": "",
        "reindexed": False,
        "log": [],
    }
    result = cast(dict[str, Any], graph.invoke(initial, config))
    if recorder is not None:
        status = "gated" if result.get("__interrupt__") else None
        recorder.record_results(run_id, result, timer.elapsed_ms(), status=status)
    return result
