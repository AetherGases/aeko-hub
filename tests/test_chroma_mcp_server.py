"""Verify chroma mcp server behavior and error handling."""

import asyncio
import inspect
import sys
import types

import pytest

from cmd.api.integrations.mcp import chroma_mcp_server

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
        """Record a vector query and return scripted search results."""
        self.queries.append(kwargs)
        return self.result


class FakeClient:
    def __init__(self, collection=None):
        self.collection = collection or FakeCollection()
        self.get_collection_calls = []

    def get_collection(self, name, embedding_function=None):
        """Record the collection lookup and return the test collection."""
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
        """Record the collection lookup and return the test collection."""
        return self.collection


class RecordingEmbeddingFunction:
    """Stands in for the sentence-transformer EF, which would load a model."""

    instances = []

    def __init__(self, model_name=None):
        self.model_name = model_name
        RecordingEmbeddingFunction.instances.append(self)


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch):
    """Clear cached Chroma server state for an isolated test."""
    RecordingCloudClient.instances = []
    RecordingEmbeddingFunction.instances = []
    monkeypatch.setattr(chroma_mcp_server, "_collection", None)
    yield


@pytest.fixture
def cloud_env(monkeypatch):
    """Set Chroma Cloud credentials for the test."""
    for name, value in CLOUD_ENV.items():
        monkeypatch.setenv(name, value)
    return CLOUD_ENV


def test_build_client_uses_the_cloud_client_with_the_environments_credentials(
    monkeypatch, cloud_env
):
    """Verify that build client uses the cloud client with the environments credentials."""
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)

    chroma_mcp_server._build_client()

    client = RecordingCloudClient.instances[-1]
    assert client.tenant == "tenant-from-env"
    assert client.database == "aeko-gases-vector-store"
    assert client.api_key == "key-from-env"


@pytest.mark.parametrize("missing", ["CHROMA_TENANT", "CHROMA_DATABASE", "CHROMA_API_KEY"])
def test_build_client_raises_naming_the_missing_variable(monkeypatch, cloud_env, missing):
    """Verify that build client raises naming the missing variable."""
    monkeypatch.setattr(chroma_mcp_server, "CloudClient", RecordingCloudClient)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        chroma_mcp_server._build_client()


def test_the_embedding_function_is_the_model_the_corpus_was_ingested_with(monkeypatch):
    """Verify that the embedding function is the model the corpus was ingested with."""
    monkeypatch.setattr(
        chroma_mcp_server, "SentenceTransformerEmbeddingFunction", RecordingEmbeddingFunction
    )

    chroma_mcp_server._embedding_function()

    assert RecordingEmbeddingFunction.instances[-1].model_name == (
        "paraphrase-multilingual-mpnet-base-v2"
    )


def test_get_collection_pins_the_gases_info_collection_and_the_embedding_function(monkeypatch):
    """Verify that get collection pins the gases info collection and the embedding function."""
    client = FakeClient()
    embedding_function = object()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: client)
    monkeypatch.setattr(chroma_mcp_server, "_embedding_function", lambda: embedding_function)

    chroma_mcp_server._get_collection()

    assert client.get_collection_calls == [("gases-info", embedding_function)]


def test_get_collection_is_resolved_once_per_process(monkeypatch):
    """Verify that get collection is resolved once per process."""
    builds = []
    client = FakeClient()
    monkeypatch.setattr(chroma_mcp_server, "_build_client", lambda: builds.append(1) or client)
    monkeypatch.setattr(chroma_mcp_server, "_embedding_function", lambda: object())

    first = chroma_mcp_server._get_collection()
    second = chroma_mcp_server._get_collection()

    assert first is second
    assert builds == [1]


def query(**kwargs):
    """Record a vector query and return scripted search results."""

    result = chroma_mcp_server.query_gases_info(**kwargs)
    return asyncio.run(result) if inspect.isawaitable(result) else result


def test_query_gases_info_searches_the_pinned_collection(monkeypatch):
    """Verify that query gases info searches the pinned collection."""
    collection = FakeCollection(result={"documents": [["biogas substitui gas natural"]]})
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    result = query(query_texts=["substituto para o metano"])

    assert result == {"documents": [["biogas substitui gas natural"]]}
    assert collection.queries[-1]["query_texts"] == ["substituto para o metano"]


def test_query_gases_info_defaults_the_result_count(monkeypatch):
    """Verify that query gases info defaults the result count."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    assert collection.queries[-1]["n_results"] == 5


def test_query_gases_info_honours_an_explicit_result_count(monkeypatch):
    """Verify that query gases info honours an explicit result count."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"], n_results=12)

    assert collection.queries[-1]["n_results"] == 12


def test_query_gases_info_returns_text_and_never_raw_vectors(monkeypatch):
    """Verify that query gases info returns text and never raw vectors."""
    collection = FakeCollection()
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: collection)

    query(query_texts=["metano"])

    included = collection.queries[-1]["include"]
    assert "documents" in included
    assert "embeddings" not in included


@pytest.fixture
def started_server(monkeypatch):
    """Start the Chroma server with external dependencies replaced."""

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.ModuleType("sentence_transformers"))

    transports = []
    monkeypatch.setattr(
        chroma_mcp_server.mcp, "run", lambda transport: transports.append(transport)
    )
    return transports


def test_main_serves_over_stdio(monkeypatch, started_server):
    """Verify that main serves over stdio."""
    monkeypatch.setattr(chroma_mcp_server, "_get_collection", lambda: FakeCollection())

    chroma_mcp_server.main()

    assert started_server == ["stdio"]


def test_main_warms_the_collection_up_before_serving(monkeypatch, started_server):
    """Verify that main warms the collection up before serving."""
    warmed = []
    monkeypatch.setattr(
        chroma_mcp_server, "_get_collection", lambda: warmed.append(1) or FakeCollection()
    )

    chroma_mcp_server.main()

    assert warmed == [1]


def test_main_still_serves_when_the_warm_up_fails(monkeypatch, started_server):
    """Verify that main still serves when the warm up fails."""

    def explode():
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("CHROMA_API_KEY is not set in the MCP server's environment.")

    monkeypatch.setattr(chroma_mcp_server, "_get_collection", explode)

    chroma_mcp_server.main()

    assert started_server == ["stdio"]
