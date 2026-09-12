"""OpenTelemetry tracing helpers — spans per node (no-op without SDK config)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

_TRACER = trace.get_tracer("patchwatch")


@contextmanager
def node_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Span per graph node/tool call; no-op unless an SDK is configured."""
    with _TRACER.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if span.is_recording():
                    span.set_attribute(key, str(value))
        yield span


def traced_node[**P, R](name: str, fn: Callable[P, R]) -> Callable[P, R]:
    """Wrap a graph node function in a span (signature preserved)."""

    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with node_span(f"node.{name}"):
            return fn(*args, **kwargs)

    return wrapped
