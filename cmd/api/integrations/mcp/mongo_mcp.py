"""Expose read-only MongoDB searches for improvement plans and user memories.

The server connection, database, and collections are selected by the API.
"""

import json
import os
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .mcp_session import PersistentMCPSession

from internal.shared import Module, logged

MONGO_FIND_TOOL_NAME = "find"


MONGO_CONNECTION_ID = "preconfigured"


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
    """Build the configured stdio MCP client, validating required credentials."""

    if mongo_uri is None:
        mongo_uri = os.environ.get('MONGO_URI', "")

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


MONGO_SESSION = PersistentMCPSession("mongodb", lambda: _configure_mcp_client())


def _call_mongo_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke a MongoDB tool synchronously through the shared MCP session."""

    return MONGO_SESSION.call_tool(tool_name, **kwargs)


def _database_name() -> str:
    """Read the MongoDB database name from the environment and reject an empty value."""

    database = os.environ.get('DB_NAME', "")
    if database == "":
        raise RuntimeError("DB_NAME is not set. Please set it in the environment.")

    return database


def _parse_filter(filter_json: str | dict[str, Any] | None) -> dict[str, Any]:
    """Accept a dictionary or JSON object filter, treating None and blank text as an empty filter."""

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
    """Return a read-only MongoDB search tool restricted to improvement plans."""

    return [
        Tool(
            name="find_improvement_plan",
            description=FIND_IMPROVEMENT_PLAN_DESCRIPTION,
            func=_find_improvement_plan,
        ),
    ]


def get_user_memory_tools() -> list[Tool]:
    """Return a read-only MongoDB search tool restricted to user memories."""

    return [
        Tool(
            name="find_user_memory",
            description=FIND_USER_MEMORY_DESCRIPTION,
            func=_find_user_memory,
        ),
    ]
