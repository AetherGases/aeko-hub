"""One operation, one record — the granularity the rest of the package exists for.

A log per step of a Mongo query or an MCP handshake would be more lines and
less information: what a reader wants from a slow request is which operations
ran, in what order, and how long each one took. So an operation is recorded
once, when it ends, with its outcome and its duration.

Where that record goes depends on whether a request is open:

* Inside a request, it joins the list that request closes with — one block per
  request, in place of uvicorn's access line (see `shared/request_log.py`).
  Two users talking to the API at once produce two blocks, not two interleaved
  streams of lines.
* Outside one — start-up, MCP warm-up, shutdown — it is written immediately,
  because there is nothing coming later to carry it.

Two ways in, the same record out:

* `operation(...)` as a context manager, where the boundary is a block —
  opening an MCP session, warming a server up.
* `logged(...)` as a decorator, where the boundary is the function — every
  repository method, every tool `func`.

Neither swallows anything: the exception is recorded and re-raised untouched,
so the error handling already written above these calls keeps working exactly
as it did.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from shared.logger import Module, elapsed_since, log_failure, log_success
from shared.request_log import Record, collect


def _subject(name: str, detail: str) -> str:
    return f"{name} {detail}".strip()


def _finish(module: Module | str, subject: str, started: float, error: str) -> None:
    """Hand the finished operation to the open request, or write it now."""

    name = module.value if isinstance(module, Module) else str(module)
    record = Record(
        module=name,
        subject=subject,
        elapsed=elapsed_since(started),
        error=error,
    )

    if collect(record):
        return

    log = log_failure if record.failed else log_success
    log(module, record.description())


@contextmanager
def operation(
    module: Module | str,
    name: str,
    detail: str = "",
) -> Iterator[None]:
    """Record the end of the block: blue if it returned, red if it raised."""

    subject = _subject(name, detail)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        _finish(module, subject, started, f"{type(exc).__name__}: {exc}")
        raise

    _finish(module, subject, started, "")


def logged(
    module: Module | str,
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """`operation` around a whole function.

    `name` names the operation as a reader of the logs would ask for it —
    `session.save_message`, not `save_message` — and falls back to the
    function's own name when there is nothing to disambiguate.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        subject = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with operation(module, subject):
                return func(*args, **kwargs)

        return wrapper

    return decorate
