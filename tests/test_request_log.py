"""Tests for the block a request closes with, in place of uvicorn's access line.

`test_logger.py` covers the shape of one line and `test_observability.py` covers
that the application still produces them. This module covers what happens to
those lines once a request is open: they are collected rather than written, and
the request closes with a header and the list of what it did.

What is worth pinning down:

* the collecting itself — inside a request an operation joins a list, outside
  one it is written immediately, and nothing in between;
* the block: header, alignment, and colour applied per line, so a 200 over a
  failed-and-retried call reads as a blue header over a red entry;
* isolation — two requests in flight must produce two blocks, not one mixed
  one, which is the whole reason this module exists;
* that a raising request still leaves a block before the exception goes up;
* `AEKO_LOG_STREAM`, the way back to a line per operation when a request is
  hanging rather than failing and the block would never be reached.
"""

import asyncio
import re
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared import request_log
from shared.logger import BLUE, COLOR_ENV_VAR, RED, Module
from shared.operation import operation
from shared.request_log import (
    INDENT,
    Record,
    RequestLogMiddleware,
    collect,
    emit,
    header,
    render,
    silence_uvicorn_access_log,
    streaming,
)

HEADER = re.compile(r"^\[aeko-hub\] \[request\] \[[^\]]+\] (?P<description>.*)$")

OK = Record(module="database", subject="user.get_user", elapsed="12.4ms")
SLOW = Record(module="mcp", subject="tavily.tavily_search", elapsed="1204.0ms")
BAD = Record(
    module="tool",
    subject="calculator",
    elapsed="0.3ms",
    error="ValueError: '2 +' could not be calculated",
)


@pytest.fixture(autouse=True)
def plain_output(monkeypatch):
    """No colour and no streaming unless the test asks for them."""
    monkeypatch.delenv(COLOR_ENV_VAR, raising=False)
    monkeypatch.delenv(request_log.STREAM_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def no_request_open():
    """The contextvar is process-wide; no test may inherit another's request."""
    token = request_log._records.set(None)
    yield
    request_log._records.reset(token)


class Stream:
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


def blocks(capsys):
    """The captured output split into blocks, one per header line."""
    found = []
    for line in capsys.readouterr().out.splitlines():
        if HEADER.match(line):
            found.append([line])
        elif found:
            found[-1].append(line)
    return found


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------
def test_a_record_describes_itself_the_way_it_would_have_been_written():
    assert OK.description() == "user.get_user succeeded in 12.4ms"


def test_a_failed_record_carries_the_error_into_its_description():
    assert BAD.description() == (
        "calculator failed after 0.3ms: ValueError: '2 +' could not be calculated"
    )


def test_only_a_record_with_an_error_counts_as_failed():
    assert OK.failed is False
    assert BAD.failed is True


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------
def test_nothing_is_collected_when_no_request_is_open():
    assert collect(OK) is False


def test_an_open_request_takes_the_record(no_request_open):
    records = []
    request_log._records.set(records)

    assert collect(OK) is True
    assert records == [OK]


def test_an_operation_outside_a_request_is_written_immediately(capsys):
    with operation(Module.DATABASE, "user.get_user"):
        pass

    assert "user.get_user succeeded in " in capsys.readouterr().out


def test_an_operation_inside_a_request_writes_nothing_yet(capsys):
    records = []
    request_log._records.set(records)

    with operation(Module.DATABASE, "user.get_user"):
        pass

    assert capsys.readouterr().out == ""
    assert records[0].subject == "user.get_user"
    assert records[0].module == "database"


def test_a_failing_operation_inside_a_request_is_collected_too(capsys):
    records = []
    request_log._records.set(records)

    with pytest.raises(RuntimeError):
        with operation(Module.DATABASE, "session.save_message"):
            raise RuntimeError("connection refused")

    assert capsys.readouterr().out == ""
    assert records[0].error == "RuntimeError: connection refused"


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def test_a_request_that_ran_nothing_renders_no_list():
    assert render([]) == []


def test_every_entry_is_indented_under_the_header():
    assert all(line.startswith(INDENT) for line in render([OK, SLOW]))


def test_the_module_and_subject_columns_are_aligned():
    """Ragged columns are why a list of eleven operations is not read."""
    first, second = render([OK, SLOW])

    assert first.index("succeeded in") == second.index("succeeded in")


def test_the_durations_line_up_in_one_column():
    """Right-aligned, so the digits end together and the slow one stands out."""
    first, second = render([OK, SLOW])

    assert first.endswith("  12.4ms")
    assert second.endswith("1204.0ms")
    assert len(first) == len(second)


def test_a_failed_entry_names_its_error():
    (line,) = render([BAD])

    assert line.endswith("failed after 0.3ms: ValueError: '2 +' could not be calculated")


def test_both_outcomes_keep_the_duration_in_the_same_column():
    """`succeeded in` and `failed after` are the same width, so nothing shifts."""
    first, second = render([OK, BAD])

    assert first.index("succeeded in") == second.index("failed after")


def test_each_entry_is_coloured_by_its_own_outcome(monkeypatch):
    monkeypatch.setenv(COLOR_ENV_VAR, "1")
    good, bad = render([OK, BAD])

    assert good.startswith(BLUE)
    assert bad.startswith(RED)


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
def test_the_header_replaces_the_access_line():
    assert header("POST", "/aether-api/v1/ai/user/session/message", 200, "4823.1ms", [OK, SLOW]) == (
        "POST /aether-api/v1/ai/user/session/message -> 200 in 4823.1ms (2 operations)"
    )


def test_one_operation_is_counted_in_the_singular():
    assert header("GET", "/x", 200, "1.0ms", [OK]).endswith("(1 operation)")


def test_a_request_that_ran_nothing_says_so():
    assert header("GET", "/x", 404, "1.0ms", []).endswith("(0 operations)")


def test_streaming_promises_no_list():
    """The lines already went out; a count would point at nothing."""
    assert header("GET", "/x", 200, "1.0ms", None) == "GET /x -> 200 in 1.0ms"


def test_a_request_that_never_answered_shows_no_status():
    line = header("GET", "/x", None, "1.0ms", [], "RuntimeError: boom")

    assert line.startswith("GET /x -> - in 1.0ms")
    assert line.endswith("raised RuntimeError: boom")


def test_the_block_stays_within_ascii():
    """It is written to whatever encoding the console has; cp1252 is one of them."""
    line = header("GET", "/x", None, "1.0ms", [OK, BAD], "RuntimeError: boom")
    block = [line, *render([OK, BAD])]

    "\n".join(block).encode("cp1252")


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------
def test_the_block_is_the_header_followed_by_the_list(capsys):
    emit("GET", "/x", 200, "5.0ms", [OK, SLOW])

    (block,) = blocks(capsys)
    assert len(block) == 3
    assert HEADER.match(block[0])["description"].startswith("GET /x -> 200 in 5.0ms")
    assert "user.get_user" in block[1]
    assert "tavily.tavily_search" in block[2]


def test_the_whole_block_reaches_the_stream_in_one_write(monkeypatch):
    """Two requests in flight must not interleave line by line."""
    stream = Stream()
    monkeypatch.setattr(sys, "stdout", stream)

    emit("GET", "/x", 200, "5.0ms", [OK, SLOW])

    assert len(stream.written) == 1


def test_a_successful_request_has_a_blue_header(monkeypatch, capsys):
    monkeypatch.setenv(COLOR_ENV_VAR, "1")
    emit("GET", "/x", 200, "5.0ms", [OK])

    assert capsys.readouterr().out.startswith(BLUE)


@pytest.mark.parametrize("status", [400, 404, 422, 500, 502])
def test_a_request_that_did_not_succeed_has_a_red_header(monkeypatch, capsys, status):
    monkeypatch.setenv(COLOR_ENV_VAR, "1")
    emit("GET", "/x", status, "5.0ms", [])

    assert capsys.readouterr().out.startswith(RED)


def test_a_failed_entry_under_a_successful_request_keeps_both_colours(monkeypatch, capsys):
    """The finding: a 200 whose tool call failed and was retried."""
    monkeypatch.setenv(COLOR_ENV_VAR, "1")
    emit("GET", "/x", 200, "5.0ms", [BAD, OK])

    header_line, failed, succeeded = capsys.readouterr().out.splitlines()
    assert header_line.startswith(BLUE)
    assert failed.startswith(RED)
    assert succeeded.startswith(BLUE)


# ---------------------------------------------------------------------------
# the middleware
# ---------------------------------------------------------------------------
def build_app(operations=(), status=200, raises=None):
    """A minimal ASGI application that runs `operations` and answers `status`."""

    async def app(scope, receive, send):
        for module, name in operations:
            with operation(module, name):
                pass
            # Let a concurrent request run between two operations, which is
            # exactly the interleaving the block has to survive.
            await asyncio.sleep(0)

        if raises is not None:
            raise raises

        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


async def call(app, method="GET", path="/x"):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        return None

    scope = {"type": "http", "method": method, "path": path, "query_string": b""}
    await app(scope, receive, send)


def test_a_request_closes_with_one_block(capsys):
    app = RequestLogMiddleware(
        build_app([(Module.DATABASE, "user.get_user"), (Module.TOOL, "calculator")])
    )

    asyncio.run(call(app, "POST", "/aether-api/v1/ai/user/session/message"))

    (block,) = blocks(capsys)
    assert HEADER.match(block[0])["description"] == (
        "POST /aether-api/v1/ai/user/session/message -> 200 in "
        + HEADER.match(block[0])["description"].split(" in ")[1]
    )
    assert "(2 operations)" in block[0]
    assert [line.strip().split()[0] for line in block[1:]] == ["[database]", "[tool]"]


def test_the_operations_are_not_also_written_on_their_own(capsys):
    app = RequestLogMiddleware(build_app([(Module.DATABASE, "user.get_user")]))

    asyncio.run(call(app))

    (block,) = blocks(capsys)
    assert len(block) == 2


def test_two_requests_in_flight_do_not_mix(capsys):
    """The reason the block exists at all."""
    first = RequestLogMiddleware(
        build_app([(Module.DATABASE, "user.get_user"), (Module.DATABASE, "user.get_user_memories")])
    )
    second = RequestLogMiddleware(
        build_app([(Module.TOOL, "calculator"), (Module.TOOL, "calculate_roi")])
    )

    async def both():
        await asyncio.gather(call(first, path="/one"), call(second, path="/two"))

    asyncio.run(both())

    one, two = sorted(blocks(capsys), key=lambda block: block[0])
    assert "/one" in one[0]
    assert all("[database]" in line for line in one[1:])
    assert "/two" in two[0]
    assert all("[tool]" in line for line in two[1:])


def test_a_request_that_ran_nothing_still_closes(capsys):
    asyncio.run(call(RequestLogMiddleware(build_app())))

    (block,) = blocks(capsys)
    assert len(block) == 1
    assert "(0 operations)" in block[0]


def test_a_raising_request_leaves_its_block_before_the_exception_goes_up(capsys):
    app = RequestLogMiddleware(
        build_app([(Module.DATABASE, "user.get_user")], raises=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError):
        asyncio.run(call(app))

    (block,) = blocks(capsys)
    assert "-> - in " in block[0]
    assert block[0].endswith("raised RuntimeError: boom")
    assert "user.get_user" in block[1]


def test_the_query_string_never_reaches_the_log(capsys):
    """It carries whatever the caller put in it."""

    async def call_with_query(app):
        async def receive():
            return {"type": "http.request"}

        async def send(message):
            return None

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/report",
            "query_string": b"token=secret&email=someone@example.com",
        }
        await app(scope, receive, send)

    asyncio.run(call_with_query(RequestLogMiddleware(build_app())))

    output = capsys.readouterr().out
    assert "/report" in output
    assert "secret" not in output
    assert "example.com" not in output


def test_a_lifespan_message_is_not_a_request(capsys):
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    async def run():
        await RequestLogMiddleware(app)({"type": "lifespan"}, None, None)

    asyncio.run(run())

    assert seen == ["lifespan"]
    assert blocks(capsys) == []


def test_the_request_context_is_closed_when_the_request_ends():
    """A leaked buffer would collect the next request's operations, or worse."""
    asyncio.run(call(RequestLogMiddleware(build_app())))

    assert request_log._records.get() is None


# ---------------------------------------------------------------------------
# AEKO_LOG_STREAM
# ---------------------------------------------------------------------------
def test_streaming_is_off_unless_asked_for():
    assert streaming() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_streaming_is_turned_on_by_the_environment(monkeypatch, value):
    monkeypatch.setenv(request_log.STREAM_ENV_VAR, value)
    assert streaming() is True


def test_streaming_writes_each_operation_as_it_finishes(monkeypatch, capsys):
    """The setting to reach for when a request is hanging rather than failing."""
    monkeypatch.setenv(request_log.STREAM_ENV_VAR, "true")
    app = RequestLogMiddleware(build_app([(Module.DATABASE, "user.get_user")]))

    asyncio.run(call(app))

    output = capsys.readouterr().out.splitlines()
    assert output[0].endswith("user.get_user succeeded in " + output[0].split(" in ")[-1])
    assert "[database]" in output[0]
    assert HEADER.match(output[1])


def test_streaming_still_closes_the_request_with_a_header(monkeypatch, capsys):
    monkeypatch.setenv(request_log.STREAM_ENV_VAR, "true")

    asyncio.run(call(RequestLogMiddleware(build_app()), "GET", "/x"))

    (block,) = blocks(capsys)
    assert HEADER.match(block[0])["description"].startswith("GET /x -> 200 in ")
    assert "operations)" not in block[0]


# ---------------------------------------------------------------------------
# uvicorn's access line, and the wiring
# ---------------------------------------------------------------------------
def test_the_uvicorn_access_logger_is_silenced():
    import logging

    logger = logging.getLogger(request_log.UVICORN_ACCESS_LOGGER)
    logger.disabled = False
    try:
        silence_uvicorn_access_log()
        assert logger.disabled is True
    finally:
        logger.disabled = False


def test_the_application_installs_the_middleware(api_main):
    assert RequestLogMiddleware in [
        middleware.cls for middleware in api_main.app.user_middleware
    ]


def test_the_lifespan_silences_uvicorn(api_main, monkeypatch):
    silenced = []
    monkeypatch.setattr(api_main, "silence_uvicorn_access_log", lambda: silenced.append(True))

    with TestClient(api_main.app):
        pass

    assert silenced == [True]


def test_the_real_application_closes_a_request_with_a_block(api_main, capsys):
    """End to end, through the real middleware stack."""
    with TestClient(api_main.app) as client:
        capsys.readouterr()
        client.get("/no-such-endpoint")

    (block,) = blocks(capsys)
    assert HEADER.match(block[0])["description"].startswith("GET /no-such-endpoint -> 404 in ")


def test_a_route_reaches_the_block_from_the_threadpool(api_main, capsys):
    """Sync routes run in a worker thread; anyio copies the context to it."""
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/sync")
    def handler():
        with operation(Module.DATABASE, "user.get_user"):
            pass
        return {"ok": True}

    with TestClient(app) as client:
        capsys.readouterr()
        client.get("/sync")

    (block,) = blocks(capsys)
    assert "(1 operation)" in block[0]
    assert "user.get_user" in block[1]
