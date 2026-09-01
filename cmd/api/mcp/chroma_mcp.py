"""Turns the project's ChromaDB MCP server into a vector-search LangChain tool.

This module never imports `aeko` — `cmd/api/main.py` is the single entry
point for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the
wrapping into an `AekoTool` happens there. What this module hands back is
plain LangChain `Tool` objects.

Unlike the Tavily and MongoDB integrations, the server on the other end is one
this project owns (`cmd/api/mcp/chroma_mcp_server.py`) rather than a published
package pulled by `npx`. The official `chroma-mcp` was tried first and cannot
reach Chroma Cloud at all — its cloud client omits the port and dials 8000
instead of 443 — and embeds queries with a 384-dimension default that does not
match the 768-dimension multilingual model the `gases-info` corpus was
ingested with. That module's docstring carries the details.

The server pins the collection and the embedding model; this side only carries
credentials and the agent's search text.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

QUERY_GASES_INFO_TOOL_NAME = "query_gases_info"

CHROMA_TENANT_ENV_VAR = "CHROMA_TENANT"
CHROMA_DATABASE_ENV_VAR = "CHROMA_DATABASE"
CHROMA_API_KEY_ENV_VAR = "CHROMA_API_KEY"

# Spawned by path, with this very interpreter, so the child needs no
# `PYTHONPATH` and no console script on `PATH`.
CHROMA_MCP_SERVER_SCRIPT = Path(__file__).with_name("chroma_mcp_server.py")

# The MCP stdio client replaces the child's environment wholesale, so anything
# the server genuinely needs has to be named here. `HOME`/`USERPROFILE` and the
# Hugging Face cache variables matter more than they look: without them the
# sentence-transformer weights land somewhere new on every spawn and get
# downloaded again.
PASSTHROUGH_ENV_VARS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
)

# Belt and braces against the same failure the server's `log_level` guards: the
# MCP stdio client pipes the child's stderr and never drains it, so a chatty
# child deadlocks once the pipe buffer fills. These silence the progress bars
# at their source, whatever any library's logging level happens to be.
QUIET_CHILD_ENV = {
    "TQDM_DISABLE": "1",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
}

QUERY_GASES_INFO_DESCRIPTION = (
    "Searches the Aether greenhouse-gas knowledge base by meaning, not by "
    "keyword, to find information such as possible substitutions for a gas. "
    "Input is the question or topic to look up, in plain text (e.g. 'what can "
    "replace SF6 in switchgear'). Read-only; always scoped to the gases-info "
    "collection."
)


def _required_setting(value: str | None, env_var: str) -> str:
    """One Chroma Cloud setting, from the caller or the environment."""

    if value is None:
        value = os.environ.get(env_var, "")

    if value == "":
        raise RuntimeError(
            f"{env_var} is not set. Please set it in the environment or pass it to _configure_mcp_client()."
        )

    return value


def _server_environment(tenant: str, database: str, api_key: str) -> dict[str, str]:
    """Exactly what the server process gets: credentials plus what it needs to run."""

    environment = {
        CHROMA_TENANT_ENV_VAR: tenant,
        CHROMA_DATABASE_ENV_VAR: database,
        CHROMA_API_KEY_ENV_VAR: api_key,
        **QUIET_CHILD_ENV,
    }
    for name in PASSTHROUGH_ENV_VARS:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value

    return environment


def _configure_mcp_client(
    tenant: str | None = None,
    database: str | None = None,
    api_key: str | None = None,
) -> MultiServerMCPClient:
    """Build the MCP client for this project's Chroma server, run over stdio."""

    tenant = _required_setting(tenant, CHROMA_TENANT_ENV_VAR)
    database = _required_setting(database, CHROMA_DATABASE_ENV_VAR)
    api_key = _required_setting(api_key, CHROMA_API_KEY_ENV_VAR)

    return MultiServerMCPClient(
        {
            "chroma": {
                "transport": "stdio",
                "command": sys.executable,
                # Credentials travel in the environment below, never in argv,
                # which would put the API key in the process list of a shared
                # host.
                "args": [str(CHROMA_MCP_SERVER_SCRIPT)],
                "env": _server_environment(tenant, database, api_key),
            }
        }
    )


async def _run_chroma_tool(client: MultiServerMCPClient, tool_name: str, **kwargs: Any) -> Any:
    """Fetch the MCP server's tools and invoke the one named `tool_name`."""

    available_tools = await client.get_tools()
    for tool in available_tools:
        if tool.name == tool_name:
            return await tool.ainvoke(kwargs)

    known = ", ".join(sorted(tool.name for tool in available_tools))
    raise LookupError(
        f"'{tool_name}' is not exposed by the chroma MCP server. Available tools: {known}."
    )


def _call_chroma_tool(tool_name: str, **kwargs: Any) -> Any:
    """Synchronous bridge: builds a client and runs one MCP tool call."""

    client = _configure_mcp_client()
    return asyncio.run(_run_chroma_tool(client, tool_name, **kwargs))


def _parse_query(query: str | list[str] | None) -> list[str]:
    """Turn the agent's input into the `query_texts` the MCP tool takes.

    Agents are asked for a plain search string, but they also send a list of
    them. Both are accepted. Unlike a MongoDB filter, an absent query has no
    sensible default — a vector search over nothing is meaningless — so empty
    input is rejected here rather than reaching the server, with the text the
    agent actually sent so it can correct itself.
    """

    if isinstance(query, str):
        candidates = [query]
    elif isinstance(query, list):
        candidates = query
    else:
        candidates = []

    texts = [
        text.strip() for text in candidates if isinstance(text, str) and text.strip() != ""
    ]

    if len(texts) != len(candidates) or texts == []:
        raise ValueError(
            f"Query must be a non-empty search text, or a list of them, got {query!r}."
        )

    return texts


def _query_gases_info(query: str | list[str] | None = "") -> Any:
    """Semantic search over `gases-info`.

    The collection, the embedding model and `n_results` all live on the server
    side, so the agent can only choose what to search for.
    """

    return _call_chroma_tool(
        QUERY_GASES_INFO_TOOL_NAME,
        query_texts=_parse_query(query),
    )


def get_gases_info_tools() -> list[Tool]:
    """The `gases-info` vector search, for the green gas analyst."""

    return [
        Tool(
            name="query_gases_info",
            description=QUERY_GASES_INFO_DESCRIPTION,
            func=_query_gases_info,
        ),
    ]
