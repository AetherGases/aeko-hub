"""Tests for the `shared` package: the log line every other module leaves behind.

`shared/logger.py` owns the shape — `[aeko-hub] [<module>] [<datetime>]
<description>` — and the colour, and `shared/operation.py` owns the granularity:
one line per operation, written when it ends, carrying its outcome and its
duration. Nothing here duplicates FastAPI's own access line; what these cover
is the work a request does *outside* the handler, which is the part that
explains a slow or failed request.

Concerns:

* `format_entry` — the shape itself, pinned in one place so a change to it is
  a change to this test and not a hunt through the application.
* `color_enabled` — when escape codes are written. Blue and red are meaning,
  so the rule matters: a terminal gets them, a redirected file does not, and
  `AEKO_LOG_COLOR` overrides the guess in both directions.
* `log_success` / `log_failure` — that the two outcomes are actually two
  colours, and that the stream is resolved at call time (otherwise pytest's
  capture never sees a line).
* `operation` / `logged` — the duration, the outcome, and the promise these
  make to every call site that already handles its own errors: the exception
  is logged and re-raised untouched.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import shared
from shared.logger import (
    APP_NAME,
    BLUE,
    COLOR_ENV_VAR,
    RED,
    RESET,
    Module,
    color_enabled,
    format_entry,
    log_failure,
    log_success,
)
from shared.operation import logged, operation

MOMENT = datetime(2026, 9, 3, 10, 15, 30, tzinfo=timezone.utc)

# `[aeko-hub] [database] [2026-09-03T10:15:30Z] <description>`
LINE = re.compile(
    r"^\[aeko-hub\] \[(?P<module>\w+)\] "
    r"\[(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\] "
    r"(?P<description>.*)$"
)

DURATION = re.compile(r"\d+\.\d+ms")


@pytest.fixture(autouse=True)
def no_color_override(monkeypatch):
    """A local `AEKO_LOG_COLOR` must not decide these tests."""
    monkeypatch.delenv(COLOR_ENV_VAR, raising=False)


class Stream:
    """A stdout double that answers `isatty` however the test needs it to."""

    def __init__(self, tty=False):
        self.tty = tty
        self.written = []

    def isatty(self):
        return self.tty

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.written)


def only_line(captured):
    """The single line the log wrote, without its newline."""
    lines = [line for line in captured.out.splitlines() if line]
    assert len(lines) == 1, captured.out
    return lines[0]


# ---------------------------------------------------------------------------
# format_entry
# ---------------------------------------------------------------------------
def test_format_entry_writes_the_agreed_shape():
    entry = format_entry(Module.DATABASE, "session.get_session ok", moment=MOMENT)
    assert entry == f"[{APP_NAME}] [database] [2026-09-03T10:15:30Z] session.get_session ok"


def test_format_entry_names_the_application_in_every_line():
    assert format_entry(Module.TOOL, "calculator", moment=MOMENT).startswith("[aeko-hub] ")


@pytest.mark.parametrize(
    "module, expected",
    [
        (Module.DATABASE, "database"),
        (Module.MCP, "mcp"),
        (Module.TOOL, "tool"),
        (Module.INTEGRATION, "integration"),
    ],
)
def test_format_entry_writes_the_module_value_not_its_member_name(module, expected):
    """`str(Module.MCP)` must not leak `Module.MCP` into a log line."""
    assert LINE.match(format_entry(module, "x", moment=MOMENT))["module"] == expected


def test_format_entry_accepts_a_plain_string_module():
    """The enum is the vocabulary, not a gate: a caller may spell it out."""
    assert LINE.match(format_entry("database", "x", moment=MOMENT))["module"] == "database"


def test_format_entry_stamps_utc_rather_than_local_time():
    noon = datetime(2026, 9, 3, 15, 0, 0, tzinfo=timezone.utc)
    assert "T15:00:00Z" in format_entry(Module.MCP, "x", moment=noon)


def test_format_entry_stamps_now_when_no_moment_is_given():
    entry = format_entry(Module.MCP, "x")
    stamp = LINE.match(entry)["stamp"]
    assert stamp == datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_format_entry_keeps_the_description_verbatim():
    """Whatever the caller says about the operation travels unedited."""
    description = "chroma.query_gases_info failed after 3.2ms: LookupError: no such tool"
    assert format_entry(Module.MCP, description, moment=MOMENT).endswith(description)


# ---------------------------------------------------------------------------
# color_enabled
# ---------------------------------------------------------------------------
def test_color_is_written_to_a_terminal():
    assert color_enabled(Stream(tty=True)) is True


def test_color_is_withheld_from_a_redirected_stream():
    """An escape code in a log file survives into whatever aggregates it."""
    assert color_enabled(Stream(tty=False)) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_color_override_turns_it_on_for_a_file(monkeypatch, value):
    monkeypatch.setenv(COLOR_ENV_VAR, value)
    assert color_enabled(Stream(tty=False)) is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
def test_color_override_turns_it_off_for_a_terminal(monkeypatch, value):
    monkeypatch.setenv(COLOR_ENV_VAR, value)
    assert color_enabled(Stream(tty=True)) is False


def test_an_unreadable_override_falls_back_to_asking_the_stream(monkeypatch):
    monkeypatch.setenv(COLOR_ENV_VAR, "maybe")
    assert color_enabled(Stream(tty=True)) is True
    assert color_enabled(Stream(tty=False)) is False


def test_a_stream_without_isatty_is_not_a_terminal():
    class Bare:
        def write(self, text):
            pass

    assert color_enabled(Bare()) is False


def test_a_stream_that_refuses_the_question_is_not_a_terminal():
    class Hostile:
        def isatty(self):
            raise ValueError("closed")

    assert color_enabled(Hostile()) is False


def test_color_asks_the_current_stdout_when_no_stream_is_given(monkeypatch):
    monkeypatch.setattr(sys, "stdout", Stream(tty=True))
    assert color_enabled() is True


# ---------------------------------------------------------------------------
# log_success / log_failure
# ---------------------------------------------------------------------------
def test_success_writes_one_line_in_the_agreed_shape(capsys):
    log_success(Module.DATABASE, "user.get_user succeeded in 1.0ms")
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "database"
    assert line["description"] == "user.get_user succeeded in 1.0ms"


def test_failure_writes_one_line_in_the_agreed_shape(capsys):
    log_failure(Module.MCP, "chroma.start failed after 2.0ms: MCPSessionError: no server")
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "mcp"
    assert line["description"].startswith("chroma.start failed after ")


def test_nothing_is_written_to_stderr(capsys):
    """stdout only: the MCP child processes pipe stderr and never drain it."""
    log_failure(Module.MCP, "chroma.start failed")
    assert capsys.readouterr().err == ""


def test_success_is_blue_on_a_terminal(monkeypatch):
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    log_success(Module.DATABASE, "ok")
    assert stream.text.startswith(BLUE)
    assert stream.text.rstrip("\n").endswith(RESET)


def test_failure_is_red_on_a_terminal(monkeypatch):
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)
    log_failure(Module.DATABASE, "boom")
    assert stream.text.startswith(RED)
    assert stream.text.rstrip("\n").endswith(RESET)


def test_the_two_outcomes_do_not_share_a_color():
    assert BLUE != RED


def test_no_escape_codes_reach_a_redirected_stream(capsys):
    log_success(Module.TOOL, "calculator succeeded in 0.1ms")
    log_failure(Module.TOOL, "calculator failed after 0.1ms")
    assert "\033" not in capsys.readouterr().out


def test_the_stream_is_resolved_at_call_time(monkeypatch):
    """Held at import, it would be the stdout of whoever imported first."""
    first, second = Stream(), Stream()
    monkeypatch.setattr(sys, "stdout", first)
    log_success(Module.MCP, "one")
    monkeypatch.setattr(sys, "stdout", second)
    log_success(Module.MCP, "two")
    assert "one" in first.text and "two" not in first.text
    assert "two" in second.text


# ---------------------------------------------------------------------------
# operation
# ---------------------------------------------------------------------------
def test_operation_logs_once_when_the_block_ends(capsys):
    with operation(Module.DATABASE, "session.get_session"):
        pass
    line = LINE.match(only_line(capsys.readouterr()))
    assert line["module"] == "database"
    assert line["description"].startswith("session.get_session succeeded in ")


def test_operation_reports_how_long_the_work_took(capsys):
    with operation(Module.MCP, "chroma.query_gases_info"):
        pass
    assert DURATION.search(capsys.readouterr().out)


def test_operation_says_nothing_before_the_block_ends(capsys):
    with operation(Module.MCP, "chroma.start"):
        assert capsys.readouterr().out == ""


def test_operation_names_the_error_when_the_block_raises(capsys):
    with pytest.raises(RuntimeError):
        with operation(Module.DATABASE, "session.save_message"):
            raise RuntimeError("connection refused")

    description = LINE.match(only_line(capsys.readouterr()))["description"]
    assert description.startswith("session.save_message failed after ")
    assert description.endswith(": RuntimeError: connection refused")


def test_operation_re_raises_the_original_exception():
    """Every call site here already handles its own errors; logging is not handling."""
    original = ValueError("User with id_external_user 7 not found.")
    with pytest.raises(ValueError) as raised:
        with operation(Module.DATABASE, "user.get_user"):
            raise original
    assert raised.value is original


def test_operation_is_red_on_failure_and_blue_on_success(monkeypatch):
    stream = Stream(tty=True)
    monkeypatch.setattr(sys, "stdout", stream)

    with operation(Module.TOOL, "calculator"):
        pass
    with pytest.raises(ValueError):
        with operation(Module.TOOL, "calculator"):
            raise ValueError("nope")

    written = stream.text.splitlines()
    assert written[0].startswith(BLUE)
    assert written[1].startswith(RED)


def test_operation_appends_the_detail_to_the_name(capsys):
    with operation(Module.MCP, "tavily.start", "over stdio via npx"):
        pass
    assert "tavily.start over stdio via npx succeeded in " in capsys.readouterr().out


def test_operation_without_detail_leaves_no_double_space(capsys):
    with operation(Module.MCP, "tavily.start"):
        pass
    assert "tavily.start  " not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# logged
# ---------------------------------------------------------------------------
def test_logged_returns_what_the_function_returned(capsys):
    @logged(Module.TOOL, "calculator")
    def calculate(expression):
        return "4"

    assert calculate("2 + 2") == "4"
    assert "calculator succeeded in " in capsys.readouterr().out


def test_logged_falls_back_to_the_function_name(capsys):
    @logged(Module.TOOL)
    def calculate():
        return None

    calculate()
    assert "calculate succeeded in " in capsys.readouterr().out


def test_logged_keeps_the_function_recognisable():
    """The repositories and tools are reached by name from tests and from LangChain."""

    @logged(Module.DATABASE, "user.get_user")
    def get_user(self, id_external_user):
        """Docstring that must survive."""
        return None

    assert get_user.__name__ == "get_user"
    assert get_user.__doc__ == "Docstring that must survive."


def test_logged_passes_every_argument_through():
    seen = {}

    @logged(Module.DATABASE, "session.save_message")
    def save(id_session, message=None):
        seen.update(id_session=id_session, message=message)
        return "saved"

    assert save("s-1", message="m") == "saved"
    assert seen == {"id_session": "s-1", "message": "m"}


def test_logged_reports_and_re_raises(capsys):
    @logged(Module.INTEGRATION, "climatiq.search")
    def search():
        raise RuntimeError("Climatiq returned 502")

    with pytest.raises(RuntimeError):
        search()

    description = LINE.match(only_line(capsys.readouterr()))["description"]
    assert description.startswith("climatiq.search failed after ")
    assert description.endswith(": RuntimeError: Climatiq returned 502")


# ---------------------------------------------------------------------------
# the package boundary
# ---------------------------------------------------------------------------
def test_shared_never_imports_the_sdk():
    """Same rule as every module outside `cmd/api/main.py`."""
    package = Path(shared.__file__).parent
    modules = sorted(package.glob("*.py"))
    assert modules, "the shared package has no modules to check"

    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "import aeko" not in source, module.name
        assert "from aeko" not in source, module.name
