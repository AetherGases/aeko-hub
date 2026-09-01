"""Tests for the project's own ChromaDB MCP server.

`cmd/api/mcp/chroma_mcp_server.py` is the one MCP server this repository owns
instead of integrating, because the published `chroma-mcp` cannot reach Chroma
Cloud and cannot embed with the model the `gases-info` corpus was ingested
with. Its own docstring carries that reasoning.

The two expensive collaborators are faked here: `CloudClient` would open a
network connection, and `SentenceTransformerEmbeddingFunction` would download
and load roughly a gigabyte of model weights. Neither ever runs in the suite.

What is worth pinning down:

* the collection, the embedding model and the cloud credentials are chosen by
  this server, never by the caller;
* the collection handle is cached, so one spawn loads the model once;
* the tool returns text, never raw vectors.
"""

import asyncio

import pytest

from cmd.api.mcp import chroma_mcp_server

CLOUD_ENV = {
    "CHROMA_TENANT": "tenant-from-env",
    "CHROMA_DATABASE": "aeko-gases-vector-store",
    "CHROMA_API_KEY": "key-from-env",
}


class FakeCollection:
    def __init__(self, result=None):
        self.result = result if result is not None else {"documents": [[]]}
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.result


class FakeClient:
    def __init__(self, collection=None):
        self.collection = collection or FakeCollection()
        self.get_collection_calls = []

    def get_collection(self, name, embedding_function=None):
        self.get_collection_calls.append((name, embedding_function))
        return self.collection


class RecordingCloudClient:
    """Stands in for `chromadb.CloudClient`, recording how it was built."""

    instances = []

    def __init__(self, tenant=None, database=None, api_key=None):
        self.tenant = tenant
        self.database = database
        self.api_key = api_key
        self.collection = FakeCollection()
        RecordingCloudClient.instances.append(self)

    def get_collection(self, name, embedding_function=None):
        return self.collection


class RecordingEmbeddingFunction:
    """Stands in for the sentence-transformer EF, which would load a model."""

    instances = []

    def __init__(self, model_name=None):
        self.model_name = model_name
        RecordingEmbeddingFunction.instances.append(self)


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch):
    """The collection handle is a module global: no test may inherit it."""
    RecordingCloudClient.instances = []
    RecordingEmbeddingFunction.instances = []
    monkeypatch.setattr(chroma_mcp_server, "_collection", None)
    yield


@pytest.fixture
def cloud_env(monkeypatch):
    for name, value in CLOUD_ENV.items():
        monkeypatch.setenv(name, value)
    return CLOUD_ENV


# ---------------------------------------------------------------------------
# Configuration: read from the environment the parent process handed over.
# ---------------------------------------------------------------------------
def test_build_client_uses_the_cloud_client_with_the_environments_credentials(
    monkeypatch, cloud_env
):
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)

    chroma_mcp_server._build_client()

    client = RecordingCloudClient.instances[-1]
    assert client.tenant == "tenant-from-env"
    assert client.database == "aeko-gases-vector-store"
    assert client.api_key == "key-from-env"


@pytest.mark.parametrize("missing", ["CHROMA_TENANT", "CHROMA_DATABASE", "CHROMA_API_KEY"])
def test_build_client_raises_naming_the_missing_variable(monkeypatch, cloud_env, missing):
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        chroma_mcp_server._build_client()


def test_the_embedding_function_is_the_model_the_corpus_was_ingested_with(monkeypatch):
    """A different model here silently invalidates every stored vector."""
    monkeypatch.setattr(
        chroma_mcp_server, "SentenceTransformerEmbeddingFunction", RecordingEmbeddingFunction
    )

    chroma_mcp_server._embedding_function()

    assert RecordingEmbeddingFunction.instances[-1].model_name == (
        "paraphrase-multilingual-mpnet-base-v2"
    )


# ---------------------------------------------------------------------------
# _get_collection — pinned, and resolved once per process.
# ---------------------------------------------------------------------------
def test_get_collection_pins_the_gases_info_collection_and_the_embedding_function(monkeypatch):
    client = FakeClient()
    embedding_function = object()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: client)
    monkeypatch.setattr(chroma_mcp_server, "_embedding_function", lambda: embedding_function)

    chroma_mcp_server._get_collection()

    assert client.get_collection_calls == [("gases-info", embedding_function)]


def test_get_collection_is_resolved_once_per_process(monkeypatch):
    """Loading the model costs seconds and hundreds of megabytes."""
    builds = []
    client = FakeClient()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: builds.append(1) or client)
    monkeypatch.setattr(chroma_mcp_server, "_embedding_function", lambda: object())

    first = chroma_mcp_server._get_collection()
    second = chroma_mcp_server._get_collection()

    assert first is second
    assert builds == [1]


# ---------------------------------------------------------------------------
# query_gases_info — the only tool the server exposes.
# ---------------------------------------------------------------------------
def query(**kwargs):
    return asyncio.run(chroma_mcp_server.query_gases_info(**kwargs))


def test_query_gases_info_searches_the_pinned_collection(monkeypatch):
    collection = FakeCollection(result={"documents": [["biogas substitui gas natural"]]})
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    result = query(query_texts=["substituto para o metano"])

    assert result == {"documents": [["biogas substitui gas natural"]]}
    assert collection.queries[-1]["query_texts"] == ["substituto para o metano"]


def test_query_gases_info_defaults_the_result_count(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    assert collection.queries[-1]["n_results"] == 5


def test_query_gases_info_honours_an_explicit_result_count(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"], n_results=12)

    assert collection.queries[-1]["n_results"] == 12


def test_query_gases_info_returns_text_and_never_raw_vectors(monkeypatch):
    """Embeddings would be megabytes of numbers the agent cannot read."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    included = collection.queries[-1]["include"]
    assert "documents" in included
    assert "embeddings" not in included


# ---------------------------------------------------------------------------
# main — how `cmd/api/mcp/chroma_mcp.py` starts this process.
# ---------------------------------------------------------------------------
def test_main_serves_over_stdio(monkeypatch):
    transports = []
    monkeypatch.setattr(
        chroma_mcp_server.mcp, "run", lambda transport: transports.append(transport)
    )

    chroma_mcp_server.main()

    assert transports == ["stdio"]
