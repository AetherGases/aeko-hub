"""Serve read-only searches over the gases-info collection in Chroma Cloud.

Queries use the corpus embedding model and a cached collection. Warning-level
logging limits output to the MCP stderr pipe. Model imports run on the main
thread at startup before synchronous queries execute on worker threads.
"""

import os
import sys
from typing import Any

from chromadb import CloudClient
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server.fastmcp import FastMCP


GASES_INFO_COLLECTION = "gases-info"


EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

DEFAULT_RESULT_COUNT = 5


QUERY_INCLUDE = ["documents", "metadatas", "distances"]


mcp = FastMCP("aeko-chroma", log_level="WARNING")

_collection = None


def _required_setting(env_var: str) -> str:
    """Resolve a required Chroma Cloud setting and reject an empty value."""

    value = os.environ.get(env_var, "")
    if value == "":
        raise RuntimeError(f"{env_var} is not set in the MCP server's environment.")

    return value


def _embedding_function() -> SentenceTransformerEmbeddingFunction:
    """Build the embedding function using the same model as the stored corpus."""

    return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def _build_client() -> Any:
    """Build an authenticated Chroma Cloud client from required settings."""

    return CloudClient(
        tenant=_required_setting('CHROMA_TENANT'),
        database=_required_setting('CHROMA_DATABASE'),
        api_key=_required_setting('CHROMA_API_KEY'),
    )


def _get_collection() -> Any:
    """Resolve and cache the gases-info collection with its embedding function."""

    global _collection
    if _collection is None:
        _collection = _build_client().get_collection(
            GASES_INFO_COLLECTION,
            embedding_function=_embedding_function(),
        )

    return _collection


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
    """Import the embedding model on the main thread, warm the collection, and serve MCP over stdio."""

    import sentence_transformers

    try:
        _get_collection()
    except Exception as exc:
        print(f"chroma warm-up failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
