"""An MCP server exposing one read-only vector search over `gases-info`.

This is the one MCP server the project owns rather than integrates. The
official `chroma-mcp` cannot do this job, for two reasons found by reading its
0.2.6 source:

* Its cloud client is built as `HttpClient(host="api.trychroma.com", ssl=True,
  ...)` with no `port`, and `HttpClient` defaults to `port=8000` while Chroma
  Cloud answers on 443 — it never reaches the API at all. Its `http` client
  type is no escape either: that path never forwards tenant/database.
* `chroma_query_documents` calls `get_collection()` without an embedding
  function, so queries are embedded with Chroma's 384-dimension default. The
  `gases-info` collection was ingested with a 768-dimension multilingual
  model, chosen for a Portuguese corpus, and the server has no way to name it.

So this module talks to Chroma Cloud through `CloudClient` (which knows the
right port) and embeds queries with the very model the ingestion used, in the
same cosine space. It is deliberately standalone — it imports nothing from
this repository, so `cmd/api/mcp/chroma_mcp.py` can spawn it as a plain script
without arranging a `PYTHONPATH` for the child process.

Read-only by construction: the only tool exposed is a query.
"""

import os
from typing import Any

from chromadb import CloudClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server.fastmcp import FastMCP

CHROMA_TENANT_ENV_VAR = "CHROMA_TENANT"
CHROMA_DATABASE_ENV_VAR = "CHROMA_DATABASE"
CHROMA_API_KEY_ENV_VAR = "CHROMA_API_KEY"

GASES_INFO_COLLECTION = "gases-info"

# The model the corpus was ingested with. Changing it silently invalidates
# every stored vector: the collection is 768-dimension, and a query embedded
# by any other model either fails on dimension or ranks by nothing.
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

DEFAULT_RESULT_COUNT = 5

# Embeddings are never sent back: the agent reads text, and the vectors would
# be megabytes of numbers it cannot use.
QUERY_INCLUDE = ["documents", "metadatas", "distances"]

# `log_level` is load-bearing, not cosmetic. FastMCP's constructor calls
# `configure_logging()`, which installs a `RichHandler` writing to stderr and
# sets the root logger — so at the default INFO every chromadb and httpx call
# is narrated there, and sentence-transformers turns its tqdm progress bar on
# whenever its effective level is INFO or lower.
#
# That matters because the MCP stdio client pipes this process's stderr and
# never drains it (`mcp/client/stdio/__init__.py` starts a `stdout_reader` and
# a `stdin_writer`, and no reader for stderr). Once the pipe buffer fills —
# some kilobytes — the next write blocks forever and the server freezes
# mid-request. At INFO, loading the model alone emitted about 20 KB and hung
# every single call.
mcp = FastMCP("aeko-chroma", log_level="WARNING")

_collection = None


def _required_setting(env_var: str) -> str:
    """One Chroma Cloud setting, from the environment the parent process set."""

    value = os.environ.get(env_var, "")
    if value == "":
        raise RuntimeError(f"{env_var} is not set in the MCP server's environment.")

    return value


def _embedding_function() -> SentenceTransformerEmbeddingFunction:
    """The ingestion's own model, so query and corpus share a vector space."""

    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def _build_client() -> Any:
    """`CloudClient`, not `HttpClient`: it carries the cloud port and auth."""

    return CloudClient(
        tenant=_required_setting(CHROMA_TENANT_ENV_VAR),
        database=_required_setting(CHROMA_DATABASE_ENV_VAR),
        api_key=_required_setting(CHROMA_API_KEY_ENV_VAR),
    )


def _get_collection() -> Any:
    """The pinned collection, resolved once per server process.

    Loading the sentence-transformer weights costs seconds and hundreds of
    megabytes, so the handle is cached: one spawn pays it once, however many
    queries the agent then runs.
    """

    global _collection
    if _collection is None:
        _collection = _build_client().get_collection(
            GASES_INFO_COLLECTION,
            embedding_function=_embedding_function(),
        )

    return _collection


# Deliberately synchronous. Everything below it blocks — loading the model
# costs tens of seconds, and the query is a plain HTTP round trip — and FastMCP
# awaits an `async def` tool directly on the event loop, which would leave the
# server unable to read stdin or answer anything until it finished. Declared
# `def`, FastMCP runs it on a worker thread and the loop stays responsive.
@mcp.tool()
def query_gases_info(
    query_texts: list[str],
    n_results: int = DEFAULT_RESULT_COUNT,
) -> dict:
    """Search the Aether greenhouse-gas knowledge base by meaning.

    Args:
        query_texts: The questions or topics to look up, in plain text.
        n_results: How many passages to return per query.
    """

    return _get_collection().query(
        query_texts=query_texts,
        n_results=n_results,
        include=QUERY_INCLUDE,
    )


def main() -> None:
    """Entry point: serve over stdio, which is how the API spawns this."""

    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
