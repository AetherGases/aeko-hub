"""Turns the MongoDB MCP server into read-only LangChain tools.

This module never imports `aeko` — `cmd/api/main.py` is the single entry
point for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the
wrapping into an `AekoTool` happens there. What this module hands back is
plain LangChain `Tool` objects.

The MCP server (`mongodb-mcp-server`, run over stdio via `npx`) exposes
several tools; only `find` is used here, and the client is started in
read-only mode (`MDB_MCP_READ_ONLY`) — agents may query, never write, through
this integration. Two selections are exposed, each pinned in code to a single
collection the agent never chooses itself, mirroring how
`cmd/api/mcp/tavily_mcp.py` pins the FAQ agent's site map to one URL:

* `get_improvement_plan_tools()` — `find` scoped to `improvement_plan`, for
  agents that read or reason about improvement plans.
* `get_user_memory_tools()` — `find` scoped to `user_memory`, for agents that
  read a user's stored memories.
"""

import json
import os
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .mcp_session import PersistentMCPSession

from shared import Module, logged

MONGO_FIND_TOOL_NAME = "find"

MONGO_URI_ENV_VAR = "MONGO_URI"
DB_NAME_ENV_VAR = "DB_NAME"

# `mongodb-mcp-server` 2.x is multi-connection: every data tool takes a
# `connectionId`, and the connection the server builds from
# `MDB_MCP_CONNECTION_STRING` is registered under this fixed id. Omitting it
# makes the server answer "Invalid input: expected string, received undefined
# at connectionId" — an agent never picks the connection, this module does.
MONGO_CONNECTION_ID = "preconfigured"

# Pinned on purpose: `npx -y` resolves to whatever is latest, and 2.0 made
# `connectionId` required while 3.0 is already in prerelease. Unpinned, the
# server's tool schema changes underneath the application without warning.
MONGO_MCP_SERVER_PACKAGE = "mongodb-mcp-server@2.1.0"

IMPROVEMENT_PLAN_COLLECTION = "improvement_plan"
USER_MEMORY_COLLECTION = "user_memory"

FIND_IMPROVEMENT_PLAN_DESCRIPTION = (
    "Reads improvement plan documents from MongoDB. Input is a JSON object "
    "string used as the MongoDB filter (e.g. '{\"id_external_inventory\": 42}'), "
    "or an empty string to fetch every improvement plan. Read-only; always "
    "scoped to the improvement_plan collection."
)
FIND_USER_MEMORY_DESCRIPTION = (
    "Reads user memory documents from MongoDB. Input is a JSON object string "
    "used as the MongoDB filter (e.g. '{\"id_user\": \"u1\"}'), or an empty "
    "string to fetch every user memory. Read-only; always scoped to the "
    "user_memory collection."
)


def _configure_mcp_client(mongo_uri: str | None = None) -> MultiServerMCPClient:
    """Build the MCP client for the MongoDB server, run over stdio via `npx`."""

    if mongo_uri is None:
        mongo_uri = os.environ.get(MONGO_URI_ENV_VAR, "")

    if mongo_uri == "":
        raise RuntimeError(
            "MONGO_URI is not set. Please set it in the environment or pass it to _configure_mcp_client()."
        )

    return MultiServerMCPClient(
        {
            "mongodb": {
                "transport": "stdio",
                "command": "npx",
                "args": [
                    "-y",
                    MONGO_MCP_SERVER_PACKAGE,
                ],
                "env": {
                    "MDB_MCP_CONNECTION_STRING": mongo_uri,
                    "MDB_MCP_READ_ONLY": "true",
                },
            }
        }
    )


# One session for the whole process, so a query no longer pays two `npx`
# spawns (one to list the tools, one to call `find`) before it reaches Mongo.
MONGO_SESSION = PersistentMCPSession("mongodb", lambda: _configure_mcp_client())


def _call_mongo_tool(tool_name: str, **kwargs: Any) -> Any:
    """Synchronous bridge: one MCP tool call over the shared session."""

    return MONGO_SESSION.call_tool(tool_name, **kwargs)


def _database_name() -> str:
    """The database every `find` is scoped to, from the environment."""

    database = os.environ.get(DB_NAME_ENV_VAR, "")
    if database == "":
        raise RuntimeError("DB_NAME is not set. Please set it in the environment.")

    return database


def _parse_filter(filter_json: str | dict[str, Any] | None) -> dict[str, Any]:
    """Turn the agent's filter input into the object the `find` tool takes.

    Agents are asked for a JSON object string, but they also send a bare dict,
    `None`, or whitespace — all of which mean "no filter". Anything else is
    rejected with the text the agent actually sent, so it can correct itself
    instead of seeing a bare `JSONDecodeError`.
    """

    if filter_json is None:
        return {}

    if isinstance(filter_json, dict):
        return filter_json

    if filter_json.strip() == "":
        return {}

    try:
        parsed = json.loads(filter_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Filter must be a JSON object string or an empty string, got {filter_json!r}."
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Filter must be a JSON object string or an empty string, got {filter_json!r}."
        )

    return parsed


def _find_in_collection(collection: str, filter_json: str | dict[str, Any] | None = "") -> Any:
    return _call_mongo_tool(
        MONGO_FIND_TOOL_NAME,
        connectionId=MONGO_CONNECTION_ID,
        database=_database_name(),
        collection=collection,
        filter=_parse_filter(filter_json),
    )


@logged(Module.TOOL, "find_improvement_plan")
def _find_improvement_plan(filter_json: str | dict[str, Any] | None = "") -> Any:
    return _find_in_collection(IMPROVEMENT_PLAN_COLLECTION, filter_json)


@logged(Module.TOOL, "find_user_memory")
def _find_user_memory(filter_json: str | dict[str, Any] | None = "") -> Any:
    return _find_in_collection(USER_MEMORY_COLLECTION, filter_json)


def get_improvement_plan_tools() -> list[Tool]:
    """`find`, pinned to `improvement_plan`, for agents that read improvement plans."""

    return [
        Tool(
            name="find_improvement_plan",
            description=FIND_IMPROVEMENT_PLAN_DESCRIPTION,
            func=_find_improvement_plan,
        ),
    ]


def get_user_memory_tools() -> list[Tool]:
    """`find`, pinned to `user_memory`, for agents that read a user's memories."""

    return [
        Tool(
            name="find_user_memory",
            description=FIND_USER_MEMORY_DESCRIPTION,
            func=_find_user_memory,
        ),
    ]
