"""Turns the Tavily MCP server into LangChain tools.

This module never imports `aeko` — `cmd/api/main.py` is the single entry
point for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the
wrapping into an `AekoTool` happens there. What this module hands back is
plain LangChain `Tool` objects.

The MCP server (`tavily-mcp`, run over stdio via `npx`) exposes several
tools — `tavily_search`, `tavily_extract`, `tavily_map`, `tavily_crawl` and
`tavily_research` (the tool names it reports at runtime, with underscores,
not the hyphenated spelling its own docs use). Two selections are exposed:

* `get_tavily_search_tools()` — `tavily_search` + `tavily_research`, general
  web research for agents that need information outside their own knowledge.
* `get_tavily_site_map_tool()` — `tavily_map` pinned to the Aether website
  (`AETHER_WEB_SITE_URL`): the agent supplies no URL, so it can only ever map
  that one site.
"""

import asyncio
import os
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

TAVILY_SEARCH_TOOL_NAME = "tavily_search"
TAVILY_RESEARCH_TOOL_NAME = "tavily_research"
TAVILY_MAP_TOOL_NAME = "tavily_map"

AETHER_WEB_SITE_URL_ENV_VAR = "AETHER_WEB_SITE_URL"

# Pinned on purpose, same reasoning as `cmd/api/mcp/mongo_mcp.py`: `@latest`
# lets `npx` swap the server's tool schema underneath the application between
# two runs, which is exactly how the MongoDB integration broke (its `find`
# gained a required `connectionId` in a major bump nobody asked for).
TAVILY_MCP_SERVER_PACKAGE = "tavily-mcp@0.2.22"

TAVILY_SEARCH_DESCRIPTION = (
    "Searches the web via Tavily for current information the agent's own "
    "knowledge does not cover. Input is a search query string."
)
TAVILY_RESEARCH_DESCRIPTION = (
    "Runs a deeper Tavily research pass over a topic, gathering more context "
    "than a plain search. Input is a research query string."
)
TAVILY_MAP_DESCRIPTION = (
    "Maps the Aether website's structure via Tavily to help answer FAQ "
    "questions about it. Takes no meaningful input; the site is fixed."
)


def _configure_mcp_client(tavily_api_key: str | None = None) -> MultiServerMCPClient:
    """Build the MCP client for the Tavily server, run over stdio via `npx`."""

    if tavily_api_key is None:
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "")

    if tavily_api_key == "":
        raise RuntimeError(
            "TAVILY_API_KEY is not set. Please set it in the environment or pass it to _configure_mcp_client()."
        )

    return MultiServerMCPClient(
        {
            "tavily": {
                "transport": "stdio",
                "command": "npx",
                "args": [
                    "-y",
                    TAVILY_MCP_SERVER_PACKAGE,
                ],
                "env": {
                    "TAVILY_API_KEY": tavily_api_key,
                },
            }
        }
    )


async def _run_tavily_tool(client: MultiServerMCPClient, tool_name: str, **kwargs: Any) -> Any:
    """Fetch the MCP server's tools and invoke the one named `tool_name`."""

    available_tools = await client.get_tools()
    for tool in available_tools:
        if tool.name == tool_name:
            return await tool.ainvoke(kwargs)

    known = ", ".join(sorted(tool.name for tool in available_tools))
    raise LookupError(
        f"'{tool_name}' is not exposed by the tavily MCP server. Available tools: {known}."
    )


def _call_tavily_tool(tool_name: str, **kwargs: Any) -> Any:
    """Synchronous bridge: builds a client and runs one MCP tool call."""

    client = _configure_mcp_client()
    return asyncio.run(_run_tavily_tool(client, tool_name, **kwargs))


def _tavily_search(query: str) -> Any:
    return _call_tavily_tool(TAVILY_SEARCH_TOOL_NAME, query=query)


def _tavily_research(query: str) -> Any:
    return _call_tavily_tool(TAVILY_RESEARCH_TOOL_NAME, query=query)


def _tavily_map_aether_site(_input: str = "") -> Any:
    """Maps only the Aether website — the URL is fixed via env, not agent input."""

    site_url = os.environ.get(AETHER_WEB_SITE_URL_ENV_VAR, "")
    return _call_tavily_tool(TAVILY_MAP_TOOL_NAME, url=site_url)


def get_tavily_search_tools() -> list[Tool]:
    """`tavily_search` and `tavily_research`, for agents doing general web research."""

    return [
        Tool(name="tavily_search", description=TAVILY_SEARCH_DESCRIPTION, func=_tavily_search),
        Tool(name="tavily_research", description=TAVILY_RESEARCH_DESCRIPTION, func=_tavily_research),
    ]


def get_tavily_site_map_tool() -> list[Tool]:
    """`tavily_map`, pinned to the Aether website, for the FAQ agent."""

    return [
        Tool(name="tavily_map", description=TAVILY_MAP_DESCRIPTION, func=_tavily_map_aether_site),
    ]
