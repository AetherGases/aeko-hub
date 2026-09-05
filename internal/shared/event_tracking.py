"""Associate requests and SDK runs with identifiers and configurable metric sinks.

Persistence is supplied by the application composition layer. Missing sinks
and persistence failures do not interrupt requests; sink failures are logged.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Callable

from bson import ObjectId

from internal.shared.logger import Module, log_failure


from internal.shared.constants import (
    CRASHED_STATUS,
    UNKNOWN_ENDPOINT,
    REQUEST_ID_HEADER,
    _HEADER_NAME,
)


@dataclass(frozen=True)
class Event:
    """One finished request, in the four fields `hub_metrics` stores."""

    id_request: str
    latency: str
    response_status: int
    endpoint: str


_id_request: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aeko_id_request", default=""
)


def bind_id_request(id_request: str) -> contextvars.Token:
    """Bind the request identifier to the current context and return a reset token."""

    return _id_request.set(id_request)


def unbind_id_request(token: contextvars.Token) -> None:
    """Restore the request identifier context using its reset token."""

    _id_request.reset(token)


def current_id_request() -> str:
    """Return the current request identifier, or an empty string outside a request."""

    return _id_request.get()


_sink: Callable[[Event], Any] | None = None


_aeko_sink: Callable[[Any], Any] | None = None


def set_event_sink(sink: Callable[[Event], Any] | None) -> None:
    """Register the request metric callback, or disable persistence with None."""

    global _sink
    _sink = sink


def set_aeko_metrics_sink(sink: Callable[[Any], Any] | None) -> None:
    """Register the SDK metric callback, or disable persistence with None."""

    global _aeko_sink
    _aeko_sink = sink


def record_aeko_metrics(metrics: Any) -> bool:
    """Submit SDK metrics to the sink and report success, logging and suppressing sink errors."""

    if metrics is None:
        return False

    sink = _aeko_sink
    if sink is None:
        return False

    try:
        sink(metrics)
    except Exception as exc:
        log_failure(
            Module.DATABASE,
            f"aeko_metrics.record gave up: {type(exc).__name__}: {exc}",
        )
        return False

    return True


def new_id_request() -> str:
    """Generate an ObjectId string shared by the response header and stored request metric."""

    return str(ObjectId())


def answer_with_id_request(message: dict, id_request: str) -> dict:
    """Replace any existing request identifier header with the current request identifier."""

    headers = [
        (name, value)
        for name, value in (message.get("headers") or [])
        if name.lower() != _HEADER_NAME
    ]
    headers.append((_HEADER_NAME, id_request.encode("ascii")))
    message["headers"] = headers
    return message


def endpoint_of(scope: dict) -> str:
    """Return the matched route template, falling back to the request path."""

    path = scope.get("path", UNKNOWN_ENDPOINT)
    return getattr(scope.get("route"), "path", None) or path


def record_event(event: Event) -> bool:
    """Submit a request event to the sink and report success, logging and suppressing sink errors."""

    sink = _sink
    if sink is None:
        return False

    try:
        sink(event)
    except Exception as exc:
        log_failure(
            Module.DATABASE,
            f"hub_metrics.record gave up: {type(exc).__name__}: {exc}",
        )
        return False

    return True
