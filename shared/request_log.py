"""One block per request, in place of uvicorn's access line.

The per-operation lines of `shared/operation.py` say what the application did;
what they cannot say, once two users are talking to the API at once, is *whose*
work each line was. Interleaved on one terminal they stop being readable
exactly when there is enough traffic to need reading.

So a request collects its operations instead of narrating them, and closes with
one block::

    [aeko-hub] [request] [2026-09-03T10:41:36Z] POST /aether-api/v1/ai/user/session/message -> 200 in 4823.1ms (5 operations)
        [database] user.get_user          succeeded in   12.4ms
        [database] user.get_user_memories succeeded in    8.1ms
        [tool]     tavily_search          succeeded in 1204.0ms
        [mcp]      tavily.tavily_search   succeeded in 1201.7ms
        [database] session.save_message   succeeded in   15.2ms

The header is the access line this replaces, and the list is the answer to the
question the access line always raises: 4.8 seconds spent where. Colour follows
the same rule in both halves and is applied per line — the header by the
request's outcome, each entry by its own — so a 200 that had a tool call fail
and be retried is a blue header over one red entry, which is the finding.

Three things this module is careful about:

* **The path, never the query string.** A query string carries whatever the
  caller put in it, and a log is the wrong place for it.
* **One write.** Concurrent requests each build their own block and emit it
  whole, so two blocks cannot interleave line by line.
* **Nothing is lost outside a request.** Start-up, MCP warm-up and shutdown run
  with no request open, and there `operation()` keeps writing its line
  immediately, exactly as before.

Closing a request is also where it is *tracked*: the same measurement that
becomes the header is handed to `shared/event_tracking.py`, which is what a
dashboard reads once this block has scrolled off the terminal. The block itself
is unchanged by it — with no sink registered, tracking does nothing at all.

The cost of collecting is that nothing is printed until the request ends, so a
request still in flight is a request you cannot see. `AEKO_LOG_STREAM=true`
gives up the block and goes back to a line per operation, which is the setting
to reach for when a request is hanging rather than failing.
"""

from __future__ import annotations

import contextvars
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from shared.event_tracking import (
    CRASHED_STATUS,
    Event,
    answer_with_id_request,
    bind_id_request,
    endpoint_of,
    new_id_request,
    record_event,
    unbind_id_request,
)
from shared.logger import (
    BLUE,
    RED,
    TRUE_VALUES,
    Module,
    elapsed_since,
    format_entry,
    paint,
    write,
)

STREAM_ENV_VAR = "AEKO_LOG_STREAM"

# uvicorn's, not FastAPI's: the access line comes from this logger, and
# silencing it is what keeps the two from saying the same thing twice.
UVICORN_ACCESS_LOGGER = "uvicorn.access"

INDENT = "    "

# A response that is not a success is a request worth finding, and 400 is where
# that starts: a 422 from a malformed agent payload is as much a failure to
# explain as a 500.
FAILING_STATUS = 400


@dataclass(frozen=True)
class Record:
    """One finished operation, kept until the request it belongs to ends."""

    module: str
    subject: str
    elapsed: str
    error: str = ""

    @property
    def failed(self) -> bool:
        return self.error != ""

    def description(self) -> str:
        """The line this operation would have written on its own."""

        if self.failed:
            return f"{self.subject} failed after {self.elapsed}: {self.error}"
        return f"{self.subject} succeeded in {self.elapsed}"


# `None` means no request is open, which is a different thing from a request
# that has run no operations yet — the first writes immediately, the second
# collects.
_records: contextvars.ContextVar[list[Record] | None] = contextvars.ContextVar(
    "aeko_request_records", default=None
)


def streaming() -> bool:
    """Whether to give up the block and write a line per operation."""

    return os.environ.get(STREAM_ENV_VAR, "").strip().lower() in TRUE_VALUES


def collect(record: Record) -> bool:
    """Add `record` to the open request, if there is one.

    Answers whether it was taken, because the caller's fallback is to write the
    line itself — which is what every operation outside a request does.
    """

    records = _records.get()
    if records is None:
        return False

    records.append(record)
    return True


def _widths(records: list[Record]) -> tuple[int, int]:
    """The two columns that make the list scannable rather than ragged."""

    module = max(len(f"[{record.module}]") for record in records)
    subject = max(len(record.subject) for record in records)
    return module, subject


def render(records: list[Record]) -> list[str]:
    """The list under the header: one indented, aligned, coloured line each.

    `succeeded in` and `failed after` are the same width, so the durations line
    up in one column without either outcome being padded into the other.
    """

    if not records:
        return []

    module_width, subject_width = _widths(records)
    elapsed_width = max(len(record.elapsed) for record in records)

    lines = []
    for record in records:
        tag = f"[{record.module}]".ljust(module_width)
        subject = record.subject.ljust(subject_width)
        outcome = "failed after" if record.failed else "succeeded in"
        line = f"{INDENT}{tag} {subject} {outcome} {record.elapsed:>{elapsed_width}}"
        if record.failed:
            line = f"{line}: {record.error}"
        lines.append(paint(line, RED if record.failed else BLUE))

    return lines


def _counted(records: list[Record] | None) -> str:
    """How many operations the block is about, when it is about any."""

    if records is None:
        # Streaming: the lines went out one by one and counting them here would
        # promise a list that is not underneath.
        return ""
    if len(records) == 1:
        return " (1 operation)"
    return f" ({len(records)} operations)"


def header(
    method: str,
    path: str,
    status: int | None,
    elapsed: str,
    records: list[Record] | None,
    error: str = "",
) -> str:
    """The access line this module replaces, with the count of what is below it."""

    shown = status if status is not None else "-"
    line = f"{method} {path} -> {shown} in {elapsed}{_counted(records)}"
    if error:
        # No status was ever sent: the exception is the outcome. The separator
        # is ASCII on purpose — this line is written to whatever encoding the
        # console happens to have, and a Windows cp1252 stdout turns an em dash
        # into a replacement character or refuses it outright.
        line = f"{line} | raised {error}"
    return line


def emit(
    method: str,
    path: str,
    status: int | None,
    elapsed: str,
    records: list[Record] | None,
    error: str = "",
) -> None:
    """Write the whole block — header and list — in a single write."""

    failed = error != "" or status is None or status >= FAILING_STATUS
    line = format_entry(Module.REQUEST, header(method, path, status, elapsed, records, error))
    block = [paint(line, RED if failed else BLUE), *render(records or [])]
    write("\n".join(block))


def silence_uvicorn_access_log() -> None:
    """Stop uvicorn narrating the same request a second time.

    Called from the lifespan rather than at import: uvicorn configures logging
    through `dictConfig`, which clears `disabled` on every logger it names, so
    the only safe moment is after the server has finished starting.
    """

    logging.getLogger(UVICORN_ACCESS_LOGGER).disabled = True


class RequestLogMiddleware:
    """Pure ASGI, deliberately not `BaseHTTPMiddleware`.

    `BaseHTTPMiddleware` runs the application in a task of its own, which puts
    a copy of the context between this middleware and the operations it is
    trying to collect. Plain ASGI runs in the caller's task, so the list set
    below is the very list every `operation()` under it appends to.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    def _close(
        self,
        scope: dict,
        method: str,
        path: str,
        status: int | None,
        started: float,
        records: list[Record] | None,
        id_request: str,
        error: str = "",
    ) -> None:
        """Track the request, then write its block.

        In that order, and while the context is still open, so the write the
        sink performs is one of the operations the block lists rather than a
        stray line after it. The duration is measured once and shared, so the
        stored row and the header above it can never disagree.
        """

        elapsed = elapsed_since(started)
        record_event(
            Event(
                id_request=id_request,
                latency=elapsed,
                response_status=status if status is not None else CRASHED_STATUS,
                endpoint=endpoint_of(scope),
            )
        )
        emit(method, path, status, elapsed, records, error)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            # Lifespan and websockets are not requests and have no block.
            await self.app(scope, receive, send)
            return

        records: list[Record] | None = None if streaming() else []
        token = _records.set(records)
        started = time.perf_counter()
        status: dict[str, Any] = {"code": None}
        # Minted before the request runs, so a row exists for it whatever
        # happens underneath — including an exception that never answers.
        id_request = new_id_request()
        # And bound for as long as it lasts, so the SDK can be handed the very
        # identifier this request is tracked under instead of inventing one.
        id_token = bind_id_request(id_request)

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                # The one moment the headers are still ours to add to, and it
                # happens for every response — a 500 is the one a caller most
                # needs the identifier of.
                answer_with_id_request(message, id_request)
            await send(message)

        method = scope.get("method", "?")
        # The path alone: a query string carries whatever the caller put in it.
        path = scope.get("path", "?")

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            self._close(
                scope,
                method,
                path,
                status["code"],
                started,
                records,
                id_request,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            self._close(scope, method, path, status["code"], started, records, id_request)
        finally:
            unbind_id_request(id_token)
            _records.reset(token)

