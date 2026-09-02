"""Tests for the MongoDB MCP integration.

`cmd/api/mcp/mongo_mcp.py` turns the MongoDB MCP server into LangChain tools
the application can hand to Aeko. It stays free of any `aeko` import (see
`test_only_the_entry_point_imports_the_sdk` in `test_e2e.py`): it only
produces plain LangChain `Tool` objects; `cmd/api/main.py` is the one place
that wraps them as `AekoTool` for `AekoMessenger.set_tools()`.

Concerns, tested in isolation so a real `npx`/MongoDB MCP server is never
needed:

* `_configure_mcp_client` — builds the stdio client config, read-only, from
  `MONGO_URI`. Pure, no I/O.
* `_find_improvement_plan` / `_find_user_memory` — each tool's `func`: fetches
  the MCP server's tools and runs `find` against a collection fixed in code,
  never chosen by the agent. The MCP client is faked.
* `get_improvement_plan_tools` / `get_user_memory_tools` — wrap those `func`s
  as the LangChain `Tool` objects handed out to agents.
"""

import pytest
from langchain_core.tools import Tool

from cmd.api.mcp import mongo_mcp, mcp_session


class FakeMCPTool:
    """Stands in for a tool the MCP session would expose."""

    def __init__(self, name, result=None):
        self.name = name
        self.description = f"fake {name}"
        self.result = result
        self.calls = []

    async def ainvoke(self, kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeMCPSession:
    """The `ClientSession` the persistent session opens once and reuses."""

    def __init__(self, tools):
        self.tools = tools


class FakeSessionContext:
    """`MultiServerMCPClient.session()` is an async context manager."""

    def __init__(self, tools):
        self.session = FakeMCPSession(tools)
        self.exited = False

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        self.exited = True
        return False


class FakeMCPClient:
    """Stands in for `MultiServerMCPClient`, whose session is now kept open.

    The tools are no longer fetched per call: the session is opened once and
    every later call reuses it, so what a test hands over is the session the
    server would have given.
    """

    def __init__(self, tools):
        self._tools = tools
        self.server_name = None
        self.contexts = []

    def session(self, server_name):
        self.server_name = server_name
        context = FakeSessionContext(self._tools)
        self.contexts.append(context)
        return context


class RecordingMultiServerMCPClient:
    """Stands in for `langchain_mcp_adapters`' client, recording its config."""

    instances = []

    def __init__(self, config):
        self.config = config
        RecordingMultiServerMCPClient.instances.append(self)


@pytest.fixture(autouse=True)
def reset_recorder():
    RecordingMultiServerMCPClient.instances = []
    yield


@pytest.fixture(autouse=True)
def fresh_mcp_session(monkeypatch):
    """No MCP session survives a test.

    The real session is cached for the life of the process, which is the point
    of it — but that would also leak one test's fake server into the next, so
    it is closed on both sides of every test. `load_mcp_tools` is replaced
    because the genuine one would speak MCP to the fake session.
    """

    async def load_tools(session, **kwargs):
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)
    mongo_mcp.MONGO_SESSION.close()
    yield
    mongo_mcp.MONGO_SESSION.close()


# ---------------------------------------------------------------------------
# _configure_mcp_client
# ---------------------------------------------------------------------------
def test_configure_mcp_client_wires_mongodb_over_stdio_read_only_with_the_given_uri(monkeypatch):
    monkeypatch.setattr(mongo_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)

    mongo_mcp._configure_mcp_client("mongodb://explicit-host:27017")

    config = RecordingMultiServerMCPClient.instances[-1].config["mongodb"]
    assert config["transport"] == "stdio"
    assert config["command"] == "npx"
    assert config["args"] == ["-y", "mongodb-mcp-server@2.1.0"]
    assert config["env"] == {
        "MDB_MCP_CONNECTION_STRING": "mongodb://explicit-host:27017",
        "MDB_MCP_READ_ONLY": "true",
    }


def test_configure_mcp_client_falls_back_to_the_mongo_uri_env_var(monkeypatch):
    monkeypatch.setattr(mongo_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.setenv("MONGO_URI", "mongodb://from-env:27017")

    mongo_mcp._configure_mcp_client()

    config = RecordingMultiServerMCPClient.instances[-1].config["mongodb"]
    assert config["env"]["MDB_MCP_CONNECTION_STRING"] == "mongodb://from-env:27017"


def test_configure_mcp_client_raises_when_no_mongo_uri_is_available(monkeypatch):
    monkeypatch.setattr(mongo_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.delenv("MONGO_URI", raising=False)

    with pytest.raises(RuntimeError, match="MONGO_URI"):
        mongo_mcp._configure_mcp_client("")


# ---------------------------------------------------------------------------
# _find_improvement_plan / _find_user_memory — collection is fixed in code,
# never chosen by the agent; only the filter travels as input.
# ---------------------------------------------------------------------------
def test_find_improvement_plan_invokes_find_scoped_to_the_improvement_plan_collection(monkeypatch):
    find_tool = FakeMCPTool("find", result=[{"defined_problem": "flaring"}])
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    result = mongo_mcp._find_improvement_plan('{"id_external_inventory": 42}')

    assert result == [{"defined_problem": "flaring"}]
    assert find_tool.calls == [
        {
            "connectionId": "preconfigured",
            "database": "aeko_test",
            "collection": "improvement_plan",
            "filter": {"id_external_inventory": 42},
        }
    ]


def test_find_improvement_plan_defaults_to_an_empty_filter(monkeypatch):
    find_tool = FakeMCPTool("find", result=[])
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    mongo_mcp._find_improvement_plan()

    assert find_tool.calls == [
        {
            "connectionId": "preconfigured",
            "database": "aeko_test",
            "collection": "improvement_plan",
            "filter": {},
        }
    ]


def test_find_user_memory_invokes_find_scoped_to_the_user_memory_collection(monkeypatch):
    find_tool = FakeMCPTool("find", result=[{"field": "preferred_language"}])
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    result = mongo_mcp._find_user_memory('{"id_user": "u1"}')

    assert result == [{"field": "preferred_language"}]
    assert find_tool.calls == [
        {
            "connectionId": "preconfigured",
            "database": "aeko_test",
            "collection": "user_memory",
            "filter": {"id_user": "u1"},
        }
    ]


def test_find_raises_a_clear_error_when_the_server_has_no_find_tool(monkeypatch):
    other_tool = FakeMCPTool("aggregate")
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([other_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    with pytest.raises(LookupError, match="find"):
        mongo_mcp._find_improvement_plan()


def test_find_raises_when_no_database_name_is_configured(monkeypatch):
    find_tool = FakeMCPTool("find", result=[])
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.delenv("DB_NAME", raising=False)

    with pytest.raises(RuntimeError, match="DB_NAME"):
        mongo_mcp._find_improvement_plan()

    assert find_tool.calls == []


# ---------------------------------------------------------------------------
# _parse_filter — agents send a JSON object string, but not always: a bare
# dict, None and whitespace all mean "no filter"; anything else is rejected
# with the text the agent sent instead of a bare JSONDecodeError.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("empty", [None, "", "   ", {}])
def test_parse_filter_treats_empty_input_as_no_filter(empty):
    assert mongo_mcp._parse_filter(empty) == {}


def test_parse_filter_reads_a_json_object_string():
    assert mongo_mcp._parse_filter('{"id_user": "u1"}') == {"id_user": "u1"}


def test_parse_filter_passes_a_dict_through():
    assert mongo_mcp._parse_filter({"id_user": "u1"}) == {"id_user": "u1"}


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]", '"a string"'])
def test_parse_filter_rejects_anything_that_is_not_a_json_object(bad):
    with pytest.raises(ValueError, match="JSON object string"):
        mongo_mcp._parse_filter(bad)


# ---------------------------------------------------------------------------
# get_improvement_plan_tools / get_user_memory_tools — one tool each,
# collection-pinned.
# ---------------------------------------------------------------------------
def test_get_improvement_plan_tools_returns_a_single_find_tool():
    tools = mongo_mcp.get_improvement_plan_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "find_improvement_plan"
    assert tools[0].description


def test_get_improvement_plan_tools_entry_is_backed_by_find_improvement_plan(monkeypatch):
    find_tool = FakeMCPTool("find", result="improvement plan results")
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    tool = mongo_mcp.get_improvement_plan_tools()[0]

    assert tool.func("{}") == "improvement plan results"


def test_get_user_memory_tools_returns_a_single_find_tool():
    tools = mongo_mcp.get_user_memory_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "find_user_memory"
    assert tools[0].description


def test_get_user_memory_tools_entry_is_backed_by_find_user_memory(monkeypatch):
    find_tool = FakeMCPTool("find", result="user memory results")
    monkeypatch.setattr(mongo_mcp, "_configure_mcp_client", lambda: FakeMCPClient([find_tool]))
    monkeypatch.setenv("DB_NAME", "aeko_test")

    tool = mongo_mcp.get_user_memory_tools()[0]

    assert tool.func("{}") == "user memory results"
