"""Unit tests for the inventory analysis repository.

Only the storage/HTTP side is covered here: reading the spreadsheet from S3
and fetching the external inventory context. The analyzer itself is injected
into the service and is out of scope.
"""

import pytest

from inventory_analysis.database import repository as repository_module
from inventory_analysis.database.repository import Repository, _normalize_s3_reference
from inventory_analysis.inventory_analysis import IRepository


class StubBody:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


class StubS3Client:
    def __init__(self, payload=b"excel-bytes", error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_object(self, Bucket, Key):
        self.calls.append((Bucket, Key))
        if self.error is not None:
            raise self.error
        return {"Body": StubBody(self.payload)}


class StubResponse:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


def test_repository_implements_the_repository_interface():
    assert issubclass(Repository, IRepository)
    assert Repository.__abstractmethods__ == frozenset()


# ---------------------------------------------------------------------------
# get_excel_bytes
# ---------------------------------------------------------------------------
def test_get_excel_bytes_reads_the_object_body(monkeypatch):
    client = StubS3Client()
    monkeypatch.setattr(repository_module, "s3_client", client)

    assert Repository().get_excel_bytes("s3://reports-bucket/input.xlsx") == b"excel-bytes"
    assert client.calls == [("reports-bucket", "input.xlsx")]


def test_get_excel_bytes_wraps_storage_failures(monkeypatch):
    monkeypatch.setattr(repository_module, "s3_client", StubS3Client(error=OSError("access denied")))

    with pytest.raises(RuntimeError, match="access denied"):
        Repository().get_excel_bytes("bucket/key.xlsx")


def test_get_excel_bytes_rejects_an_invalid_reference(monkeypatch):
    monkeypatch.setattr(repository_module, "s3_client", StubS3Client())

    with pytest.raises(RuntimeError, match="Invalid S3 reference"):
        Repository().get_excel_bytes("bucket-only")


# ---------------------------------------------------------------------------
# get_external_inventory_context
# ---------------------------------------------------------------------------
def test_get_external_inventory_context_returns_the_payload(monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append((url, timeout))
        return StubResponse(payload={"scope_1": 10})

    monkeypatch.setattr(repository_module.requests, "get", fake_get)

    assert Repository().get_external_inventory_context(42) == {"scope_1": 10}
    assert "42" in calls[0][0]


def test_get_external_inventory_context_wraps_http_failures(monkeypatch):
    def fake_get(url, timeout=None):
        return StubResponse(error=OSError("503 Service Unavailable"))

    monkeypatch.setattr(repository_module.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="503 Service Unavailable"):
        Repository().get_external_inventory_context(42)


# ---------------------------------------------------------------------------
# reference normalization
# ---------------------------------------------------------------------------
def test_normalize_accepts_an_s3_uri():
    assert _normalize_s3_reference("s3://bucket/path/file.xlsx") == ("bucket", "path/file.xlsx")


def test_normalize_accepts_a_bucket_and_key():
    assert _normalize_s3_reference("bucket/path/file.xlsx") == ("bucket", "path/file.xlsx")


@pytest.mark.parametrize("reference", ["s3://bucket", "s3://bucket/", "s3:///key", "bucket-only", "/key"])
def test_normalize_rejects_invalid_references(reference):
    with pytest.raises(ValueError, match="Invalid S3"):
        _normalize_s3_reference(reference)
