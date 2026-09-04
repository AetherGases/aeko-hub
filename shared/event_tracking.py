"""One row per request, so the dashboard has something to read.

The block of `shared/request_log.py` explains a request to whoever is watching
the terminal *now*: it is written once, to stdout, and a restart takes it with
it. A dashboard asks the other kind of question — how many 500s this week, which
endpoint is the slow one — and no amount of formatting makes stdout answer that.
So every request also leaves an `Event`, and the `hub_metrics` domain stores it.

This is an addition, not a replacement: the log block is untouched, and a
process with no sink registered logs exactly as it did before.

The four fields are the ones the middleware already has in its hands, which is
why tracking costs a request nothing:

* `id_request` — the identifier of the request, and the `_id` its row is
  stored under. It goes back to the caller in the `x-request-id` response
  header, which is what turns a user saying "it was slow" into a row anyone can
  look up by primary key. It is always ours: a header the caller sent is not
  read, so nothing outside decides what is stored.
* `latency` — the very string the block's header shows, not a second
  measurement, so a row and the line it came from can never disagree.
* `response_status` — what was answered. A request that raised before
  answering is stored as `CRASHED_STATUS`, because that is what the client got.
* `endpoint` — the route *template*, resolved from the scope. `/user/{id}` is
  one row on a dashboard; `/user/12345` and `/user/999` are two rows that say
  nothing, and a path with an identifier in it has no upper bound.

**The identifier is readable while the request runs.** It is minted here, at
the top of the request, and the SDK needs the very same value: a run it reports
under an identifier of its own invention could never be lined up with the
request that made it. So it is bound to the context for as long as the request
lasts and read back through `current_id_request()` — nothing in between has to
carry it down, which is what keeps the handlers' signatures out of it.

**The sinks are injected.** `shared` is the base every package imports and it
imports none of them back, so this module has no idea `hub_metrics` exists: it
holds a function, and `cmd/api/main.py` — the composition root, and the only
place where a database handle exists — registers the one that writes. Without
a sink, `record_event` is a no-op, which is exactly what the test suite and any
process without Mongo want.

The one thing it does know about the storage is the shape of the identifier —
`bson.ObjectId`, because the header must carry the row's `_id` and the header
is written first. That is a dependency on the driver, not on a domain.

There are two of them, because there are two accounts of one request. The first
is the gateway's own — how long it took, what it answered — and `hub_metrics`
stores it. The second is what the SDK reports about the run inside it, which
only exists for the requests that made one, and `aeko_metrics` stores that. They
are separate sinks rather than one, because they are written at different
moments by different callers: the middleware closes every request, while only a
service that called the SDK has a run to report.

Nothing here may raise into a request. A row that cannot be written is a row
lost and a red line explaining it; it is never a request the user loses.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Callable

from bson import ObjectId

from shared.logger import Module, log_failure

# The status stored for a request that raised before sending a response. No
# status was ever set, and the server answers 500 to the client, so this is
# what the row must say for the dashboard to count it with the other 500s.
CRASHED_STATUS = 500

UNKNOWN_ENDPOINT = "?"

# The header every response carries the request's identifier back in. Lower
# case on the wire because that is what ASGI servers expect and what HTTP/2
# requires; HTTP header names are case-insensitive, so a caller reading
# `X-Request-Id` finds it either way.
REQUEST_ID_HEADER = "x-request-id"

_HEADER_NAME = REQUEST_ID_HEADER.encode("ascii")


@dataclass(frozen=True)
class Event:
    """One finished request, in the four fields `hub_metrics` stores.

    Deliberately not the `Metric` entity: `shared` does not know the domain.
    Translating one into the other is the composition root's job.
    """

    id_request: str
    latency: str
    response_status: int
    endpoint: str


# The identifier of the request being served in this context. Empty outside
# any request — start-up, a warm-up thread, a script driving a service
# directly — which is exactly what a run nobody is tracking should report.
#
# A ContextVar rather than a module global for the reason the request block
# uses one: two requests served by the same worker must never read each other's
# identifier. It is set by the middleware in the request's own task, so the
# operations underneath — including those handed to a worker thread, which
# `run_in_threadpool` copies the context into — read the one they belong to.
_id_request: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aeko_id_request", default=""
)


def bind_id_request(id_request: str) -> contextvars.Token:
    """Make `id_request` the identifier this context's work is tracked under."""

    return _id_request.set(id_request)


def unbind_id_request(token: contextvars.Token) -> None:
    """Restore whatever identifier was current before `bind_id_request`."""

    _id_request.reset(token)


def current_id_request() -> str:
    """The identifier of the request being served, or empty outside one.

    This is what the SDK is handed at every call: it reads no database and
    cannot derive one, and a run reported under an invented identifier is a run
    nobody can line up with the request that paid for it.
    """

    return _id_request.get()


# `None` means nothing is tracking, which is the state every process starts in.
_sink: Callable[[Event], Any] | None = None

# The second one: what the SDK reported about the run inside a request. Only
# the requests that called the SDK have one, and it arrives as the SDK's own
# object — read by the composition root, never by anything here.
_aeko_sink: Callable[[Any], Any] | None = None


def set_event_sink(sink: Callable[[Event], Any] | None) -> None:
    """Register — or, with `None`, take back off — the function that persists.

    Called from the lifespan rather than at import, because the sink needs a
    database handle and that only exists once the application has started.
    """

    global _sink
    _sink = sink


def set_aeko_metrics_sink(sink: Callable[[Any], Any] | None) -> None:
    """Register — or, with `None`, take back off — the function that persists
    what the SDK reported about a run.

    A second registration rather than a second job for the one above: the two
    rows are written at different moments, by different callers, about
    different things.
    """

    global _aeko_sink
    _aeko_sink = sink


def record_aeko_metrics(metrics: Any) -> bool:
    """Hand the SDK's account of one run to the sink, if there is one.

    `metrics` is whatever the SDK handed back — this module never reads a field
    of it, which is what lets `shared` stay as ignorant of the SDK as it is of
    the domains. `None` is normal and records nothing: an error raised before a
    run started carries no tracking at all.

    Answers whether it was taken, and swallows whatever the sink raises. A row
    describing a run is never worth the run itself.
    """

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
    """The identifier of one request, and the `_id` its row will be stored under.

    An `ObjectId`, not a UUID, and minted here rather than left to the
    database: what the caller is answered with has to *be* the `_id` of the row
    in `hub_metrics`, and the response goes out long before that row is
    written. The two can only be the same value if this side chooses it.

    That is not a trick — it is how MongoDB already works. The driver, not the
    server, generates `_id` for every insert that arrives without one, so
    generating it a few milliseconds earlier costs nothing and asks nothing of
    Mongo. The alternative would be writing the row before answering, which
    puts a blocking database call in front of every response.
    """

    return str(ObjectId())


def answer_with_id_request(message: dict, id_request: str) -> dict:
    """Put the request's identifier on the response that is going out.

    Without it the identifier would exist only in Mongo, and a caller holding a
    slow response would have no way of naming it to whoever reads the rows.

    Any header of this name the application set itself is dropped rather than
    added to: the identifier is minted by this middleware and there is exactly
    one of it, so two values would only be a question about which one is real.
    """

    headers = [
        (name, value)
        for name, value in (message.get("headers") or [])
        if name.lower() != _HEADER_NAME
    ]
    headers.append((_HEADER_NAME, id_request.encode("ascii")))
    message["headers"] = headers
    return message


def endpoint_of(scope: dict) -> str:
    """The route template this request matched, or the path when none did.

    The route that answered is left in the scope by the routing itself, which
    is the only place that knows it: walking the application's own routes is
    not an alternative, because `include_router` keeps them nested rather than
    flat. A request that matched nothing — a 404 — keeps its path, which is the
    only thing it has.
    """

    path = scope.get("path", UNKNOWN_ENDPOINT)
    return getattr(scope.get("route"), "path", None) or path


def record_event(event: Event) -> bool:
    """Hand the event to the sink, if there is one.

    Answers whether it was taken, and swallows whatever the sink raises: a
    dashboard row is never worth the request that produced it. The failure is
    said out loud — the repository underneath has already logged its own error,
    and this line adds the part it cannot know, which is that the row was
    dropped.
    """

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
