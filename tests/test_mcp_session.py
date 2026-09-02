"""Tests for the MCP session shared by every tool call.

`cmd/api/mcp/mcp_session.py` exists because `MultiServerMCPClient` opens a new
session — and therefore spawns the server again — for every single tool call.
Measured against the real Chroma server that cost 103 seconds for a query whose
search takes two, so the session is opened once and kept open.

No real server is ever spawned here: the client, its session and the tools on
it are all faked, and `load_mcp_tools` is replaced because the genuine one
would try to speak MCP to a fake session.

What is worth pinning down:

* the session is opened once, however many calls go through it;
* a call that never answers raises instead of hanging — the failure this whole
  module was written to remove;
* a session that has died is rebuilt rather than being handed to the caller;
* closing ends the server process, which otherwise outlives the application
  still holding the model it loaded.
"""

import asyncio
import threading
import time

import pytest

from cmd.api.mcp import mcp_session
from cmd.api.mcp.mcp_session import MCPSessionError, PersistentMCPSession


class FakeTool:
    """One tool as `load_mcp_tools` would hand it over."""

    def __init__(self, name, result=None, fails_with=None, hangs=False):
        self.name = name
        self.result = result
        self.fails_with = fails_with
        self.hangs = hangs
        self.calls = []

    async def ainvoke(self, kwargs):
        self.calls.append(kwargs)
        if self.hangs:
            await asyncio.sleep(30)
        if self.fails_with is not None:
            raise self.fails_with
        return self.result


class FakeSession:
    def __init__(self, tools):
        self.tools = tools


class FakeClient:
    """`MultiServerMCPClient`, whose `session()` is an async context manager."""

    def __init__(self, tools, fails_to_open=None, fails_to_close=None, hangs_on_close=False):
        self.tools = tools
        self.fails_to_open = fails_to_open
        self.fails_to_close = fails_to_close
        self.hangs_on_close = hangs_on_close
        self.server_names = []
        self.opened = 0
        self.closed = 0

    def session(self, server_name):
        self.server_names.append(server_name)
        return FakeSessionContext(self)


class FakeSessionContext:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        if self._client.fails_to_open is not None:
            raise self._client.fails_to_open
        self._client.opened += 1
        return FakeSession(self._client.tools)

    async def __aexit__(self, *exc_info):
        self._client.closed += 1
        if self._client.hangs_on_close:
            await asyncio.sleep(30)
        if self._client.fails_to_close is not None:
            raise self._client.fails_to_close
        return False


@pytest.fixture(autouse=True)
def fake_tool_loading(monkeypatch):
    """The real `load_mcp_tools` would send MCP messages to a fake session."""

    async def load_tools(session, **kwargs):
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)


def build_session(*clients, **kwargs):
    """A session over a queue of clients — one per time it has to reopen."""

    remaining = list(clients)
    built = []

    def build_client():
        client = remaining.pop(0) if remaining else built[-1]
        built.append(client)
        return client

    session = PersistentMCPSession("fake-server", build_client, **kwargs)
    session.built = built
    return session


@pytest.fixture
def closing():
    """Every session in this module is closed, pass or fail."""
    sessions = []
    yield sessions.append
    for session in sessions:
        session.close()


# ---------------------------------------------------------------------------
# One session, reused
# ---------------------------------------------------------------------------
def test_the_session_is_opened_once_and_reused_by_every_call(closing):
    """The whole point: the server is spawned once, not once per call."""
    tool = FakeTool("search", result="ok")
    client = FakeClient([tool])
    session = build_session(client)
    closing(session)

    session.call_tool("search", query="a")
    session.call_tool("search", query="b")

    assert client.opened == 1
    assert tool.calls == [{"query": "a"}, {"query": "b"}]


def test_call_tool_returns_what_the_tool_returned(closing):
    client = FakeClient([FakeTool("search", result={"documents": [["biogas"]]})])
    session = build_session(client)
    closing(session)

    assert session.call_tool("search", query="metano") == {"documents": [["biogas"]]}


def test_the_session_is_opened_under_the_configured_server_name(closing):
    """The name has to match the key in the client's connection config."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.call_tool("search")

    assert client.server_names == ["fake-server"]


def test_start_opens_the_session_without_calling_anything(closing):
    """What the application calls at start-up, to pay the cold start there."""
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.start()

    assert client.opened == 1


def test_the_client_is_built_only_when_the_session_opens(closing):
    """A missing credential must still be reported by the call that needs it."""
    built = []

    def build_client():
        built.append(1)
        raise RuntimeError("TAVILY_API_KEY is not set.")

    session = PersistentMCPSession("fake-server", build_client)
    closing(session)

    assert built == []
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        session.call_tool("search")


# ---------------------------------------------------------------------------
# Failures the agent has to be able to read
# ---------------------------------------------------------------------------
def test_an_unknown_tool_names_the_ones_the_server_does_expose(closing):
    client = FakeClient([FakeTool("tavily_map"), FakeTool("tavily_search")])
    session = build_session(client)
    closing(session)

    with pytest.raises(LookupError, match="tavily_map, tavily_search"):
        session.call_tool("tavily_crawl")


def test_a_server_that_never_comes_up_says_so(closing):
    client = FakeClient([], fails_to_open=OSError("npx not found"))
    session = build_session(client)
    closing(session)

    with pytest.raises(MCPSessionError, match="npx not found"):
        session.call_tool("search")


def test_a_call_that_never_answers_raises_instead_of_hanging(closing):
    """The failure this module exists to remove: no answer, and no error."""
    client = FakeClient([FakeTool("search", hangs=True)])
    session = build_session(client, call_timeout=0.1)
    closing(session)

    with pytest.raises(MCPSessionError, match="did not answer within"):
        session.call_tool("search")


def test_a_call_that_kept_failing_reports_the_last_error(closing):
    broken = FakeClient([FakeTool("search", fails_with=ConnectionError("pipe closed"))])
    session = build_session(broken, broken)
    closing(session)

    with pytest.raises(MCPSessionError, match="pipe closed"):
        session.call_tool("search")


# ---------------------------------------------------------------------------
# A dead session is rebuilt, not handed to the caller
# ---------------------------------------------------------------------------
def test_a_failed_call_is_retried_once_on_a_fresh_session(closing):
    """The server can be killed from outside at any moment."""
    dead = FakeClient([FakeTool("search", fails_with=ConnectionError("pipe closed"))])
    healthy = FakeClient([FakeTool("search", result="ok")])
    session = build_session(dead, healthy)
    closing(session)

    assert session.call_tool("search") == "ok"
    assert dead.opened == 1 and healthy.opened == 1


def test_a_dropped_session_is_replaced_on_the_next_call(closing):
    """After a timeout the session is gone; the next call starts a new server."""
    stuck = FakeClient([FakeTool("search", hangs=True)])
    healthy = FakeClient([FakeTool("search", result="ok")])
    session = build_session(stuck, healthy, call_timeout=0.1)
    closing(session)

    with pytest.raises(MCPSessionError):
        session.call_tool("search")

    assert session.call_tool("search") == "ok"


def test_running_on_a_session_closed_underneath_reports_it(closing):
    """Another thread may close the session between resolving and running."""
    session = build_session(FakeClient([FakeTool("search", result="ok")]))
    closing(session)
    session.start()
    session.close()

    coroutine = asyncio.sleep(0)
    try:
        with pytest.raises(ConnectionError, match="closed"):
            session._run(coroutine)
    finally:
        coroutine.close()


# ---------------------------------------------------------------------------
# Closing — the server process must not outlive the application
# ---------------------------------------------------------------------------
def test_closing_leaves_the_session_and_the_server_behind():
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    session.start()

    session.close()

    assert client.closed == 1


def test_closing_survives_a_server_that_fails_on_the_way_out():
    """Shutdown must not be derailed by a child that is already broken."""
    client = FakeClient([FakeTool("search", result="ok")], fails_to_close=OSError("broken pipe"))
    session = build_session(client)
    session.start()

    session.close()  # must not raise

    assert client.closed == 1


def test_closing_gives_up_on_a_server_that_will_not_shut_down():
    """Shutdown must finish even when the child ignores it."""
    client = FakeClient([FakeTool("search", result="ok")], hangs_on_close=True)
    session = build_session(client, close_timeout=0.1)
    session.start()

    started = time.monotonic()
    session.close()

    assert time.monotonic() - started < 5


def test_closing_a_session_that_was_never_opened_does_nothing():
    session = build_session(FakeClient([]))

    session.close()  # must not raise


def test_closing_stops_the_thread_the_session_ran_on():
    """A leaked loop thread would keep the child process alive with it."""
    session = build_session(FakeClient([FakeTool("search", result="ok")]))
    session.start()
    names = {thread.name for thread in threading.enumerate()}
    assert "mcp-fake-server" in names

    session.close()

    for _ in range(50):
        if "mcp-fake-server" not in {thread.name for thread in threading.enumerate()}:
            return
        threading.Event().wait(0.1)

    raise AssertionError("the session's loop thread outlived close()")


def test_a_closed_session_opens_a_new_one_when_called_again(closing):
    client = FakeClient([FakeTool("search", result="ok")])
    session = build_session(client)
    closing(session)

    session.start()
    session.close()
    session.call_tool("search")

    assert client.opened == 2
