"""Verify tavily mcp behavior and error handling."""

import pytest
from langchain_core.tools import Tool

from cmd.api.integrations.mcp import mcp_session
from cmd.api.integrations.mcp import tavily_mcp


class FakeMCPTool:
    """Stands in for a tool the MCP session would expose."""

    def __init__(self, name, result=None):
        self.name = name
        self.description = f"fake {name}"
        self.result = result
        self.calls = []

    async def ainvoke(self, kwargs):
        """Record an asynchronous tool invocation and return its scripted response."""
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
    """Simulate a persistent MultiServerMCPClient session."""

    def __init__(self, tools):
        self._tools = tools
        self.server_name = None
        self.contexts = []

    def session(self, server_name):
        """Provide a simulated MCP session context."""
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
    """Reset the MCP call recorder before each test."""
    RecordingMultiServerMCPClient.instances = []
    yield


@pytest.fixture(autouse=True)
def fresh_mcp_session(monkeypatch):
    """Replace the shared MCP session with an isolated session for the test."""

    async def load_tools(session, **kwargs):
        """Return scripted tools for MCP session discovery."""
        return session.tools

    monkeypatch.setattr(mcp_session, "load_mcp_tools", load_tools)
    tavily_mcp.TAVILY_SESSION.close()
    yield
    tavily_mcp.TAVILY_SESSION.close()


def test_configure_mcp_client_wires_tavily_over_stdio_with_the_given_key(monkeypatch):
    """Verify that configure mcp client wires tavily over stdio with the given key."""
    monkeypatch.setattr(tavily_mcp,"MultiServerMCPClient", RecordingMultiServerMCPClient)

    tavily_mcp._configure_mcp_client("secret-key")

    config = RecordingMultiServerMCPClient.instances[-1].config["tavily"]
    assert config["transport"] == "stdio"
    assert config["command"] == "npx"
    assert config["args"] == ["-y", "tavily-mcp@0.2.22"]
    assert config["env"] == {"TAVILY_API_KEY": "secret-key"}


def test_configure_mcp_client_falls_back_to_the_tavily_api_key_env_var(monkeypatch):
    """Verify that configure mcp client falls back to the tavily api key env var."""
    monkeypatch.setattr(tavily_mcp,"MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")

    tavily_mcp._configure_mcp_client()

    config = RecordingMultiServerMCPClient.instances[-1].config["tavily"]
    assert config["env"]["TAVILY_API_KEY"] == "from-env"


def test_configure_mcp_client_raises_when_no_tavily_api_key_is_available(monkeypatch):
    """Verify that configure mcp client raises when no tavily api key is available."""
    monkeypatch.setattr(tavily_mcp, "MultiServerMCPClient", RecordingMultiServerMCPClient)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        tavily_mcp._configure_mcp_client("")


def test_tavily_search_invokes_the_mcp_search_tool_with_the_query(monkeypatch):
    """Verify that tavily search invokes the mcp search tool with the query."""
    search_tool = FakeMCPTool("tavily_search", result={"answer": "42"})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([search_tool]))

    result = tavily_mcp._tavily_search("What is the answer?")

    assert result == {"answer": "42"}
    assert search_tool.calls == [{"query": "What is the answer?"}]


def test_tavily_research_invokes_the_mcp_research_tool_with_the_query(monkeypatch):
    """Verify that tavily research invokes the mcp research tool with the query."""
    research_tool = FakeMCPTool("tavily_research", result={"summary": "deep dive"})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([research_tool]))

    result = tavily_mcp._tavily_research("scope 3 emissions benchmarks")

    assert result == {"summary": "deep dive"}
    assert research_tool.calls == [{"query": "scope 3 emissions benchmarks"}]


def test_tavily_search_raises_a_clear_error_when_the_server_has_no_search_tool(monkeypatch):
    """Verify that tavily search raises a clear error when the server has no search tool."""
    other_tool = FakeMCPTool("tavily_extract")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([other_tool]))

    with pytest.raises(LookupError, match="tavily_search"):
        tavily_mcp._tavily_search("anything")


def test_tavily_map_maps_the_site_from_the_env_var(monkeypatch):
    """Verify that tavily map maps the site from the env var."""
    map_tool = FakeMCPTool("tavily_map", result={"pages": ["/faq"]})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv('AETHER_WEB_SITE_URL', "https://aether.example.com")

    result = tavily_mcp._tavily_map_aether_site()

    assert result == {"pages": ["/faq"]}
    assert map_tool.calls == [{"url": "https://aether.example.com"}]


def test_tavily_map_ignores_whatever_input_the_agent_passes(monkeypatch):
    """Verify that tavily map ignores whatever input the agent passes."""
    map_tool = FakeMCPTool("tavily_map", result="ok")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv('AETHER_WEB_SITE_URL', "https://aether.example.com")

    tavily_mcp._tavily_map_aether_site("some unrelated agent input")

    assert map_tool.calls == [{"url": "https://aether.example.com"}]


def test_get_tavily_search_tools_returns_search_and_research():
    """Verify that get tavily search tools returns search and research."""
    tools = tavily_mcp.get_tavily_search_tools()

    assert [tool.name for tool in tools] == ["tavily_search", "tavily_research"]
    assert all(isinstance(tool, Tool) for tool in tools)
    assert all(tool.description for tool in tools)


def test_get_tavily_search_tools_search_entry_is_backed_by_tavily_search(monkeypatch):
    """Verify that get tavily search tools search entry is backed by tavily search."""
    search_tool = FakeMCPTool("tavily_search", result="search results")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([search_tool]))

    tool = next(t for t in tavily_mcp.get_tavily_search_tools() if t.name == "tavily_search")

    assert tool.func("query") == "search results"


def test_get_tavily_search_tools_research_entry_is_backed_by_tavily_research(monkeypatch):
    """Verify that get tavily search tools research entry is backed by tavily research."""
    research_tool = FakeMCPTool("tavily_research", result="research results")
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([research_tool]))

    tool = next(t for t in tavily_mcp.get_tavily_search_tools() if t.name == "tavily_research")

    assert tool.func("query") == "research results"


def test_get_tavily_site_map_tool_returns_a_single_map_tool():
    """Verify that get tavily site map tool returns a single map tool."""
    tools = tavily_mcp.get_tavily_site_map_tool()

    assert len(tools) == 1
    assert isinstance(tools[0], Tool)
    assert tools[0].name == "tavily_map"
    assert tools[0].description


def test_get_tavily_site_map_tool_is_backed_by_the_pinned_site(monkeypatch):
    """Verify that get tavily site map tool is backed by the pinned site."""
    map_tool = FakeMCPTool("tavily_map", result={"pages": ["/"]})
    monkeypatch.setattr(tavily_mcp,"_configure_mcp_client", lambda: FakeMCPClient([map_tool]))
    monkeypatch.setenv('AETHER_WEB_SITE_URL', "https://aether.example.com")

    tool = tavily_mcp.get_tavily_site_map_tool()[0]
    result = tool.func("")

    assert result == {"pages": ["/"]}
    assert map_tool.calls == [{"url": "https://aether.example.com"}]
