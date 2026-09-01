"""Tests for the Tavily MCP integration.

`cmd/api/mcp/tavily_mcp.py` turns the Tavily MCP server into LangChain tools the
application can hand to Aeko. It stays free of any `aeko` import (see
`test_only_the_entry_point_imports_the_sdk` in `test_e2e.py`): it only
produces plain LangChain `Tool` objects; `cmd/api/main.py` is the one place
that wraps them as `AekoTool` for `AekoMessenger.set_tools()`.

Concerns, tested in isolation so a real `npx`/Tavily server is never needed:

* `_configure_mcp_client` — builds the stdio client config. Pure, no I/O.
* `_tavily_search` / `_tavily_research` / `_tavily_map_aether_site` — each
  tool's `func`: fetches the MCP server's tools and runs the named one. The
  MCP client is faked.
* `get_tavily_search_tools` / `get_tavily_site_map_tool` — wrap those `func`s
  as the LangChain `Tool` objects handed out to agents.
"""

import pytest
from langchain_core.tools import Tool

from cmd.api.mcp import tavily_mcp


class FakeMCPTool:
    """Stands in for a tool `MultiServerMCPClient.get_tools()` would return."""

    def __init__(self, name, result=None):
        self.name = name
        self.description = f"fake {name}"
        self.result = result
        self.calls = []

    async def ainvoke(self, kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeMCPClient:
    def __init__(self, tools):
        self._tools = tools

    async def get_tools(self):
        return self._tools


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


# ---------------------------------------------------------------------------
# _configure_mcp_client
# ---------------------------------------------------------------------------
def test_configure_mcp_client_wires_tavily_over_stdio_with_the_given_key(monkeypatch):
    monkeypatch.setattr(tavily_mcp,"MultiServerMCPClient", RecordingMultiServerMCPClient)

    tavily_mcp._configure_mcp_client("secret-key")

    config = RecordingMultiServerMCPClient.instances[-1].config["tavily"]
    assert config["transport"] == "stdio"
    assert config["command"] == "npx"
    assert config["args"] == ["-y", "tavily-mcp@0.2.22"]
    assert config["env"] == {"TAVILY_API_KEY": "secret-key"}


def test_configure_mcp_client_falls_back_to_the_tavily_api_key_env_var(monkeypatch):
    monkeypatch.setattr(tavily_mcp,"MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")

    tavily_mcp._configure_mcp_client()

    config = RecordingMultiServerMCPClient.instances[-1].config["tavily"]
    assert config["env"]["TAVILY_API_KEY"] == "from-env"


def test_configure_mcp_client_raises_when_no_tavily_api_key_is_available(monkeypatch):
    monkeypatch.setattr(tavily_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        tavily_mcp._configure_mcp_client("")


# ---------------------------------------------------------------------------
# _tavily_search / _tavily_research — real MCP tool names use underscores,
# not the hyphenated spelling the project's own docs use.
# ---------------------------------------------------------------------------
def test_tavily_search_invokes_the_mcp_search_tool_with_the_query(monkeypatch):
    search_tool = FakeMCPTool("tavily_search", result={"answer": "42"})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([search_tool]))

    result = tavily_mcp._tavily_search("What is the answer?")

    assert result == {"answer": "42"}
    assert search_tool.calls == [{"query": "What is the answer?"}]


def test_tavily_research_invokes_the_mcp_research_tool_with_the_query(monkeypatch):
    research_tool = FakeMCPTool("tavily_research", result={"summary": "deep dive"})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([research_tool]))

    result = tavily_mcp._tavily_research("scope 3 emissions benchmarks")

    assert result == {"summary": "deep dive"}
    assert research_tool.calls == [{"query": "scope 3 emissions benchmarks"}]


def test_tavily_search_raises_a_clear_error_when_the_server_has_no_search_tool(monkeypatch):
    other_tool = FakeMCPTool("tavily_extract")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([other_tool]))

    with pytest.raises(LookupError, match="tavily_search"):
        tavily_mcp._tavily_search("anything")


# ---------------------------------------------------------------------------
# _tavily_map_aether_site — the site is fixed via env, never chosen by the agent.
# ---------------------------------------------------------------------------
def test_tavily_map_maps_the_site_from_the_env_var(monkeypatch):
    map_tool = FakeMCPTool("tavily_map", result={"pages": ["/faq"]})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv(tavily_mcp.AETHER_WEB_SITE_URL_ENV_VAR, "https://aether.example.com")

    result = tavily_mcp._tavily_map_aether_site()

    assert result == {"pages": ["/faq"]}
    assert map_tool.calls == [{"url": "https://aether.example.com"}]


def test_tavily_map_ignores_whatever_input_the_agent_passes(monkeypatch):
    map_tool = FakeMCPTool("tavily_map", result="ok")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv(tavily_mcp.AETHER_WEB_SITE_URL_ENV_VAR, "https://aether.example.com")

    tavily_mcp._tavily_map_aether_site("some unrelated agent input")

    assert map_tool.calls == [{"url": "https://aether.example.com"}]


# ---------------------------------------------------------------------------
# get_tavily_search_tools — search + research, for the general research agents.
# ---------------------------------------------------------------------------
def test_get_tavily_search_tools_returns_search_and_research():
    tools = tavily_mcp.get_tavily_search_tools()

    assert [tool.name for tool in tools] == ["tavily_search", "tavily_research"]
    assert all(isinstance(tool, Tool) for tool in tools)
    assert all(tool.description for tool in tools)


def test_get_tavily_search_tools_search_entry_is_backed_by_tavily_search(monkeypatch):
    search_tool = FakeMCPTool("tavily_search", result="search results")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([search_tool]))

    tool = next(t for t in tavily_mcp.get_tavily_search_tools() if t.name == "tavily_search")

    assert tool.func("query") == "search results"


def test_get_tavily_search_tools_research_entry_is_backed_by_tavily_research(monkeypatch):
    research_tool = FakeMCPTool("tavily_research", result="research results")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([research_tool]))

    tool = next(t for t in tavily_mcp.get_tavily_search_tools() if t.name == "tavily_research")

    assert tool.func("query") == "research results"


# ---------------------------------------------------------------------------
# get_tavily_site_map_tool — a single, site-pinned tool for FAQ.
# ---------------------------------------------------------------------------
def test_get_tavily_site_map_tool_returns_a_single_map_tool():
    tools = tavily_mcp.get_tavily_site_map_tool()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "tavily_map"
    assert tools[0].description


def test_get_tavily_site_map_tool_is_backed_by_the_pinned_site(monkeypatch):
    map_tool = FakeMCPTool("tavily_map", result={"pages": ["/"]})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv(tavily_mcp.AETHER_WEB_SITE_URL_ENV_VAR, "https://aether.example.com")

    tool = tavily_mcp.get_tavily_site_map_tool()[0]
    result = tool.func("")

    assert result == {"pages": ["/"]}
    assert map_tool.calls == [{"url": "https://aether.example.com"}]
