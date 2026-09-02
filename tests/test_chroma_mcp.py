"""Tests for the ChromaDB MCP client module.

`cmd/api/mcp/chroma_mcp.py` turns this project's own Chroma MCP server (see
`tests/test_chroma_mcp_server.py`) into a LangChain tool the application can
hand to Aeko. It stays free of any `aeko` import (see
`test_only_the_entry_point_imports_the_sdk` in `test_e2e.py`): it only
produces plain LangChain `Tool` objects; `cmd/api/main.py` is the one place
that wraps them as `AekoTool` for `AekoMessenger.set_tools()`.

Concerns, tested in isolation so no server is ever spawned:

* `_configure_mcp_client` — builds the stdio client config that spawns the
  server script with this interpreter, carrying the Chroma Cloud credentials
  in the child's environment. Pure, no I/O.
* `_query_gases_info` — the tool's `func`: fetches the MCP server's tools and
  runs `query_gases_info`. The MCP client is faked.
* `_parse_query` — normalises whatever the agent sends into `query_texts`.
* `get_gases_info_tools` — wraps that `func` as the LangChain `Tool` handed to
  the "Analista de Gases Verdes" agent.
"""

import sys

import pytest
from langchain_core.tools import Tool

from cmd.api.mcp import chroma_mcp, mcp_session

CLOUD_ENV = {
    "CHROMA_TENANT": "tenant-from-env",
    "CHROMA_DATABASE": "aeko-gases-vector-store",
    "CHROMA_API_KEY": "key-from-env",
}


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
    chroma_mcp.CHROMA_SESSION.close()
    yield
    chroma_mcp.CHROMA_SESSION.close()


@pytest.fixture
def cloud_env(monkeypatch):
    """The three variables the Chroma Cloud client type requires."""
    for name, value in CLOUD_ENV.items():
        monkeypatch.setenv(name, value)
    return CLOUD_ENV


def configured_child(monkeypatch, *args):
    monkeypatch.setattr(chroma_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    chroma_mcp._configure_mcp_client(*args)
    return RecordingMultiServerMCPClient.instances[-1].config["chroma"]


# ---------------------------------------------------------------------------
# _configure_mcp_client
# ---------------------------------------------------------------------------
def test_configure_mcp_client_spawns_the_projects_own_server_over_stdio(monkeypatch):
    config = configured_child(monkeypatch, "explicit-tenant", "explicit-database", "explicit-key")

    assert config["transport"] == "stdio"
    assert config["command"] == sys.executable
    assert config["args"] == [str(chroma_mcp.CHROMA_MCP_SERVER_SCRIPT)]


def test_the_configured_server_script_actually_exists():
    """Spawning by path fails at runtime, not at import, if this ever moves."""
    assert chroma_mcp.CHROMA_MCP_SERVER_SCRIPT.is_file()


def test_configure_mcp_client_hands_the_credentials_to_the_child_environment(monkeypatch):
    config = configured_child(monkeypatch, "explicit-tenant", "explicit-database", "explicit-key")

    assert config["env"]["CHROMA_TENANT"] == "explicit-tenant"
    assert config["env"]["CHROMA_DATABASE"] == "explicit-database"
    assert config["env"]["CHROMA_API_KEY"] == "explicit-key"


def test_configure_mcp_client_keeps_the_api_key_out_of_argv(monkeypatch):
    """A key in `args` would be readable in the process list of a shared host."""
    config = configured_child(monkeypatch, "explicit-tenant", "explicit-database", "explicit-key")

    assert "explicit-key" not in config["args"]


def test_configure_mcp_client_passes_the_model_cache_location_through(monkeypatch):
    """Without these the sentence-transformer weights are re-downloaded per spawn."""
    monkeypatch.setenv("HF_HOME", "/models/hf")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

    config = configured_child(monkeypatch, "explicit-tenant", "explicit-database", "explicit-key")

    assert config["env"]["HF_HOME"] == "/models/hf"
    assert config["env"]["PATH"] == "/usr/local/bin:/usr/bin"


def test_configure_mcp_client_omits_passthrough_variables_that_are_unset(monkeypatch):
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)

    config = configured_child(monkeypatch, "explicit-tenant", "explicit-database", "explicit-key")

    assert "SENTENCE_TRANSFORMERS_HOME" not in config["env"]


def test_configure_mcp_client_falls_back_to_the_chroma_env_vars(monkeypatch, cloud_env):
    config = configured_child(monkeypatch)

    assert config["env"]["CHROMA_TENANT"] == "tenant-from-env"
    assert config["env"]["CHROMA_DATABASE"] == "aeko-gases-vector-store"
    assert config["env"]["CHROMA_API_KEY"] == "key-from-env"


@pytest.mark.parametrize("missing", ["CHROMA_TENANT", "CHROMA_DATABASE", "CHROMA_API_KEY"])
def test_configure_mcp_client_raises_naming_the_missing_variable(monkeypatch, cloud_env, missing):
    monkeypatch.setattr(chroma_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        chroma_mcp._configure_mcp_client()


# ---------------------------------------------------------------------------
# _query_gases_info — the collection, the embedding model and the result count
# all live on the server side; only the search text travels from here.
# ---------------------------------------------------------------------------
def test_query_gases_info_invokes_the_servers_query_tool_with_the_search_text(monkeypatch):
    query_tool = FakeMCPTool(
        "query_gases_info", result={"documents": [["metano pode virar biogas"]]}
    )
    monkeypatch.setattr(chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool]))

    result = chroma_mcp._query_gases_info("substituto para o metano")

    assert result == {"documents": [["metano pode virar biogas"]]}
    assert query_tool.calls == [{"query_texts": ["substituto para o metano"]}]


def test_query_gases_info_never_lets_the_agent_name_a_collection(monkeypatch):
    query_tool = FakeMCPTool("query_gases_info", result={})
    monkeypatch.setattr(chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool]))

    chroma_mcp._query_gases_info("qualquer coisa")

    assert set(query_tool.calls[-1]) == {"query_texts"}


def test_query_gases_info_raises_a_clear_error_when_the_server_has_no_query_tool(monkeypatch):
    other_tool = FakeMCPTool("something_else")
    monkeypatch.setattr(chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([other_tool]))

    with pytest.raises(LookupError, match="query_gases_info"):
        chroma_mcp._query_gases_info("qualquer coisa")


def test_query_gases_info_never_reaches_the_server_with_an_empty_query(monkeypatch):
    query_tool = FakeMCPTool("query_gases_info", result={})
    monkeypatch.setattr(chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool]))

    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._query_gases_info("   ")

    assert query_tool.calls == []


# ---------------------------------------------------------------------------
# _parse_query — the agent is asked for a search string, but it also sends a
# list; both become the `query_texts` the MCP tool takes. Vector search over
# nothing is meaningless, so empty input is rejected rather than passed on.
# ---------------------------------------------------------------------------
def test_parse_query_wraps_a_single_string():
    assert chroma_mcp._parse_query("gases de efeito estufa") == ["gases de efeito estufa"]


def test_parse_query_passes_a_list_of_strings_through():
    assert chroma_mcp._parse_query(["metano", "CO2"]) == ["metano", "CO2"]


def test_parse_query_drops_surrounding_whitespace():
    assert chroma_mcp._parse_query("  metano  ") == ["metano"]


@pytest.mark.parametrize("empty", [None, "", "   ", [], ["  "]])
def test_parse_query_rejects_empty_input(empty):
    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._parse_query(empty)


@pytest.mark.parametrize("bad", [42, {"query": "metano"}, ["metano", 7]])
def test_parse_query_rejects_anything_that_is_not_text(bad):
    with pytest.raises(ValueError, match="non-empty"):
        chroma_mcp._parse_query(bad)


# ---------------------------------------------------------------------------
# get_gases_info_tools — one tool, server-pinned.
# ---------------------------------------------------------------------------
def test_get_gases_info_tools_returns_a_single_query_tool():
    tools = chroma_mcp.get_gases_info_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "query_gases_info"
    assert tools[0].description


def test_get_gases_info_tools_entry_is_backed_by_query_gases_info(monkeypatch):
    query_tool = FakeMCPTool("query_gases_info", result="gases info results")
    monkeypatch.setattr(chroma_mcp, "_configure_mcp_client", lambda: FakeMCPClient([query_tool]))

    tool = chroma_mcp.get_gases_info_tools()[0]

    assert tool.func("trocas possiveis para o SF6") == "gases info results"
    assert query_tool.calls[-1] == {"query_texts": ["trocas possiveis para o SF6"]}
