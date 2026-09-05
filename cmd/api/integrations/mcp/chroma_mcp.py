"""Expose greenhouse-gas vector searches through a persistent Chroma MCP session.

The child process receives credentials and model cache settings through its
environment. Progress bars are disabled to avoid filling the stderr pipe.
"""

import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import Tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .mcp_session import PersistentMCPSession

from internal.shared import Module, logged

QUERY_GASES_INFO_TOOL_NAME = "query_gases_info"


CHROMA_MCP_SERVER_SCRIPT = Path(__file__).with_name("chroma_mcp_server.py")


PASSTHROUGH_ENV_VARS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "SENTENCE_TRANSFORMERS_HOME",
)


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
    """Resolve a required Chroma Cloud setting and reject an empty value."""

    if value is None:
        value = os.environ.get(env_var, "")

    if value == "":
        raise RuntimeError(
            f"{env_var} is not set. Please set it in the environment or pass it to _configure_mcp_client()."
        )

    return value


def _server_environment(tenant: str, database: str, api_key: str) -> dict[str, str]:
    """Build the child environment with credentials, cache paths, and quiet progress settings."""

    environment = {
        'CHROMA_TENANT': tenant,
        'CHROMA_DATABASE': database,
        'CHROMA_API_KEY': api_key,
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
    """Build the configured stdio MCP client, validating required credentials."""

    tenant = _required_setting(tenant, 'CHROMA_TENANT')
    database = _required_setting(database, 'CHROMA_DATABASE')
    api_key = _required_setting(api_key, 'CHROMA_API_KEY')

    return MultiServerMCPClient(
        {
            "chroma": {
                "transport": "stdio",
                "command": sys.executable,

                "args": [str(CHROMA_MCP_SERVER_SCRIPT)],
                "env": _server_environment(tenant, database, api_key),
            }
        }
    )


CHROMA_SESSION = PersistentMCPSession("chroma", lambda: _configure_mcp_client())


def _call_chroma_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke a Chroma tool synchronously through the shared MCP session."""

    return CHROMA_SESSION.call_tool(tool_name, **kwargs)


def _parse_query(query: str | list[str] | None) -> list[str]:
    """Normalize a search string or list to nonempty query texts, rejecting invalid entries."""

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


@logged(Module.TOOL, "query_gases_info")
def _query_gases_info(query: str | list[str] | None = "") -> Any:
    """Search the pinned greenhouse-gas collection with validated query texts."""

    return _call_chroma_tool(
        QUERY_GASES_INFO_TOOL_NAME,
        query_texts=_parse_query(query),
    )


def get_gases_info_tools() -> list[Tool]:
    """Return the greenhouse-gas knowledge base search tool."""

    return [
        Tool(
            name="query_gases_info",
            description=QUERY_GASES_INFO_DESCRIPTION,
            func=_query_gases_info,
        ),
    ]
