"""Expose Tavily search, research, and a site map restricted to the configured URL."""

import os
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .mcp_session import PersistentMCPSession

from internal.shared import Module, logged

from cmd.api.integrations.mcp.constants import (
    TAVILY_SEARCH_TOOL_NAME,
    TAVILY_RESEARCH_TOOL_NAME,
    TAVILY_MAP_TOOL_NAME,
    TAVILY_MCP_SERVER_PACKAGE,
    TAVILY_SEARCH_DESCRIPTION,
    TAVILY_RESEARCH_DESCRIPTION,
    TAVILY_MAP_DESCRIPTION,
)


def _configure_mcp_client(tavily_api_key: str | None = None) -> MultiServerMCPClient:
    """Build the configured stdio MCP client, validating required credentials."""

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


TAVILY_SESSION = PersistentMCPSession("tavily", lambda: _configure_mcp_client())


def _call_tavily_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke a Tavily tool synchronously through the shared MCP session."""

    return TAVILY_SESSION.call_tool(tool_name, **kwargs)


@logged(Module.TOOL, "tavily_search")
def _tavily_search(query: str) -> Any:
    return _call_tavily_tool(TAVILY_SEARCH_TOOL_NAME, query=query)


@logged(Module.TOOL, "tavily_research")
def _tavily_research(query: str) -> Any:
    return _call_tavily_tool(TAVILY_RESEARCH_TOOL_NAME, query=query)


@logged(Module.TOOL, "tavily_map")
def _tavily_map_aether_site(_input: str = "") -> Any:
    """Map the Aether URL from the environment without accepting an agent-supplied URL."""

    site_url = os.environ.get('AETHER_WEB_SITE_URL', "")
    return _call_tavily_tool(TAVILY_MAP_TOOL_NAME, url=site_url)


def get_tavily_search_tools() -> list[Tool]:
    """Return Tavily web search and research tools."""

    return [
        Tool(name="tavily_search", description=TAVILY_SEARCH_DESCRIPTION, func=_tavily_search),
        Tool(name="tavily_research", description=TAVILY_RESEARCH_DESCRIPTION, func=_tavily_research),
    ]


def get_tavily_site_map_tool() -> list[Tool]:
    """Return a Tavily site-map tool restricted to the configured Aether URL."""

    return [
        Tool(name="tavily_map", description=TAVILY_MAP_DESCRIPTION, func=_tavily_map_aether_site),
    ]
