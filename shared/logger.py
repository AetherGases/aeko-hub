"""One log line, one shape, for everything this application does to the outside.

Every request closes with a line saying what it was and how long it took —
uvicorn's access line, replaced by this application's own (see
`shared/request_log.py`). What that line cannot say is *why* a request took
eleven seconds, because the work is not in the handler: it is in a Mongo query,
an MCP server that had to be woken up, or a Climatiq call that timed out. So
the request line carries those underneath it, and this module is the shape they
all share.

The shape is fixed::

    [aeko-hub] [<module>] [<datetime>] <description>

`<module>` is one of the five in `Module`, deliberately a small closed set
rather than the Python module path: these lines are read by grouping them, and
a field with one value per source file cannot be grouped. What the operation
actually was travels in the description, which is where a name like
`session.get_session` or `chroma.query_gases_info` belongs.

Colour is meaning, not decoration: blue is an operation that finished, red is
one that raised. It is written only when the stream is a terminal, because an
escape code in a log file is noise that survives into whatever aggregates it —
`AEKO_LOG_COLOR` forces the decision either way when the guess is wrong.

The timestamp is UTC. Local time in a log is unreadable the moment a second
machine writes to it.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

APP_NAME = "aeko-hub"

# Seconds are the resolution: the duration of the operation is in the
# description, so the timestamp only has to place it.
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

COLOR_ENV_VAR = "AEKO_LOG_COLOR"

BLUE = "\033[34m"
RED = "\033[31m"
RESET = "\033[0m"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class Module(str, Enum):
    """The four kinds of work worth a line of its own, and the request holding them.

    A `str` enum so a caller may pass either the member or its value, and so
    the value lands in the log without a conversion at every call site.
    """

    DATABASE = "database"
    MCP = "mcp"
    TOOL = "tool"
    INTEGRATION = "integration"

    # The one module that is not a kind of work but a container for it: a
    # `request` line carries the operations of the other four underneath it
    # (see `shared/request_log.py`), and replaces uvicorn's access line.
    REQUEST = "request"

    def __str__(self) -> str:
        return self.value


def _stream() -> Any:
    """`sys.stdout`, resolved now rather than held.

    Held, it would be the stdout of whoever imported this module first, which
    is neither what pytest replaces nor what a process redirects.
    """

    return sys.stdout


def color_enabled(stream: Any = None) -> bool:
    """Whether to write escape codes to `stream`."""

    override = os.environ.get(COLOR_ENV_VAR, "").strip().lower()
    if override in TRUE_VALUES:
        return True
    if override in FALSE_VALUES:
        return False

    if stream is None:
        stream = _stream()

    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        # A stream that refuses the question is not a terminal worth the risk.
        return False


def format_entry(
    module: Module | str,
    description: str,
    *,
    moment: datetime | None = None,
) -> str:
    """The line itself, without colour — the one place the shape is written."""

    name = module.value if isinstance(module, Module) else str(module)
    stamp = (moment or datetime.now(timezone.utc)).strftime(TIMESTAMP_FORMAT)
    return f"[{APP_NAME}] [{name}] [{stamp}] {description}"


def elapsed_since(started: float) -> str:
    """Milliseconds, one decimal — the unit every duration here lands in.

    Shared by the operation line and the request header so the two can be
    compared without converting one of them in your head.
    """

    return f"{(time.perf_counter() - started) * 1000:.1f}ms"


def paint(text: str, color: str, stream: Any = None) -> str:
    """`text` wrapped in `color`, when the stream takes escape codes.

    Separate from `write` because a request block is many lines in two
    colours — the header by the request's outcome, each entry by its own — so
    the colouring happens per line and the writing happens once.
    """

    if not color_enabled(stream):
        return text
    return f"{color}{text}{RESET}"


def write(text: str) -> None:
    """One write to stdout, whatever the text is.

    One, not one per line: a request block that reached the terminal in pieces
    would interleave with the block of every other request in flight. The
    newline is appended rather than left to `print`, which writes it separately
    and would make every block two writes instead of one.
    """

    stream = _stream()
    stream.write(text + "\n")
    # `flush` because these lines exist to explain a process that may be about
    # to die: a buffered explanation of a crash is no explanation at all.
    stream.flush()


def _emit(module: Module | str, description: str, color: str) -> None:
    write(paint(format_entry(module, description), color))


def log_success(module: Module | str, description: str) -> None:
    """An operation that finished. Blue."""

    _emit(module, description, BLUE)


def log_failure(module: Module | str, description: str) -> None:
    """An operation that raised. Red."""

    _emit(module, description, RED)
