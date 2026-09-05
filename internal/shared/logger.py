"""Format and write application logs to stdout with UTC timestamps.

Entries use [aeko-hub] [module] [datetime] followed by the description. Success
and failure colors depend on terminal support or the AEKO_LOG_COLOR override.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

APP_NAME = "aeko-hub"


TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


BLUE = "\033[34m"
RED = "\033[31m"
RESET = "\033[0m"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class Module(str, Enum):
    """Log categories for database, MCP, tool, integration, and request operations."""

    DATABASE = "database"
    MCP = "mcp"
    TOOL = "tool"
    INTEGRATION = "integration"

    REQUEST = "request"

    def __str__(self) -> str:
        return self.value


def _stream() -> Any:
    """Resolve the current stdout stream so redirection is respected."""

    return sys.stdout


def color_enabled(stream: Any = None) -> bool:
    """Return whether ANSI colors are enabled by the environment or terminal detection."""

    override = os.environ.get('AEKO_LOG_COLOR', "").strip().lower()
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
        return False


def format_entry(
    module: Module | str,
    description: str,
    *,
    moment: datetime | None = None,
) -> str:
    """Format a log entry with the application name, module, and UTC timestamp."""

    name = module.value if isinstance(module, Module) else str(module)
    stamp = (moment or datetime.now(timezone.utc)).strftime(TIMESTAMP_FORMAT)
    return f"[{APP_NAME}] [{name}] [{stamp}] {description}"


def elapsed_since(started: float) -> str:
    """Return elapsed milliseconds formatted to one decimal place."""

    return f"{(time.perf_counter() - started) * 1000:.1f}ms"


def paint(text: str, color: str, stream: Any = None) -> str:
    """Wrap text in an ANSI color when color output is enabled."""

    if not color_enabled(stream):
        return text
    return f"{color}{text}{RESET}"


def write(text: str) -> None:
    """Write text and a newline to stdout in one call, then flush the stream."""

    stream = _stream()
    stream.write(text + "\n")

    stream.flush()


def _emit(module: Module | str, description: str, color: str) -> None:
    write(paint(format_entry(module, description), color))


def log_success(module: Module | str, description: str) -> None:
    """Write a successful operation using the configured success color."""

    _emit(module, description, BLUE)


def log_failure(module: Module | str, description: str) -> None:
    """Write a failed operation using the configured failure color."""

    _emit(module, description, RED)
