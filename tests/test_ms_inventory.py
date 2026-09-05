"""Verify ms inventory behavior and error handling."""

import pytest

from improvement_plan.improvement_plan import IInventoryRepository
from improvement_plan.integration import ms_inventory
from improvement_plan.integration.ms_inventory import Repository

BASE_URL = "http://ms-inventory:8080"
ID_INVENTORY = 502
RESOLVE_URL = f"{BASE_URL}/aether-api/v1/ms-inventory/resolve/{ID_INVENTORY}"
MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"


class StubResponse:
    def __init__(self, payload=None, status_error=None, json_error=None):
        self.payload = {"content": MARKDOWN} if payload is None else payload
        self.status_error = status_error
        self.json_error = json_error

    def raise_for_status(self):
        """Raise the scripted HTTP status error, if configured."""
        if self.status_error is not None:
            raise self.status_error

    def json(self):
        """Return the scripted JSON response body."""
        if self.json_error is not None:
            raise self.json_error
        return self.payload


@pytest.fixture
def recorded_get(monkeypatch):
    """Replace inventory HTTP requests with a call recorder."""
    calls = []

    def fake_get(url, timeout=None):
        """Record an inventory HTTP request and return its scripted response."""
        calls.append({"url": url, "timeout": timeout})
        return calls_response[0]

    calls_response = [StubResponse()]
    monkeypatch.setattr(ms_inventory.requests, "get", fake_get)
    monkeypatch.setenv('MS_INVENTORY_BASE_URL', BASE_URL)

    def answer_with(response):
        """Configure the inventory HTTP response for the test."""
        calls_response[0] = response

    fake_get.calls = calls
    fake_get.answer_with = answer_with
    return fake_get


def test_repository_implements_the_inventory_repository_interface():
    """Verify that repository implements the inventory repository interface."""
    assert issubclass(Repository, IInventoryRepository)
    assert Repository.__abstractmethods__ == frozenset()


def test_the_inventory_is_resolved_by_its_external_identifier(recorded_get):
    """Verify that the inventory is resolved by its external identifier."""
    Repository().get_inventory_markdown(ID_INVENTORY)

    assert recorded_get.calls[0]["url"] == RESOLVE_URL


def test_the_request_carries_a_timeout(recorded_get):
    """Verify that the request carries a timeout."""
    Repository().get_inventory_markdown(ID_INVENTORY)

    assert recorded_get.calls[0]["timeout"] == ms_inventory.MS_INVENTORY_REQUEST_TIMEOUT


def test_a_base_url_with_a_trailing_slash_does_not_double_it(recorded_get, monkeypatch):
    """Verify that a base url with a trailing slash does not double it."""
    monkeypatch.setenv('MS_INVENTORY_BASE_URL', f"{BASE_URL}/")

    Repository().get_inventory_markdown(ID_INVENTORY)

    assert recorded_get.calls[0]["url"] == RESOLVE_URL


def test_a_missing_base_url_is_refused_by_name(recorded_get, monkeypatch):
    """Verify that a missing base url is refused by name."""
    monkeypatch.delenv('MS_INVENTORY_BASE_URL', raising=False)

    with pytest.raises(RuntimeError, match='MS_INVENTORY_BASE_URL'):
        Repository().get_inventory_markdown(ID_INVENTORY)

    assert recorded_get.calls == []


def test_the_content_field_is_what_comes_back(recorded_get):
    """Verify that the content field is what comes back."""
    assert Repository().get_inventory_markdown(ID_INVENTORY) == MARKDOWN


def test_a_failing_status_is_wrapped_with_the_inventory_it_was_asked_for(recorded_get):
    """Verify that a failing status is wrapped with the inventory it was asked for."""
    recorded_get.answer_with(StubResponse(status_error=OSError("503 Service Unavailable")))

    with pytest.raises(RuntimeError, match="503 Service Unavailable"):
        Repository().get_inventory_markdown(ID_INVENTORY)


def test_a_transport_failure_is_wrapped(monkeypatch):
    """Verify that a transport failure is wrapped."""
    monkeypatch.setenv('MS_INVENTORY_BASE_URL', BASE_URL)

    def explode(url, timeout=None):
        """Raise the configured failure to exercise error handling."""
        raise OSError("connection refused")

    monkeypatch.setattr(ms_inventory.requests, "get", explode)

    with pytest.raises(RuntimeError, match="connection refused"):
        Repository().get_inventory_markdown(ID_INVENTORY)


def test_a_body_that_is_not_json_is_wrapped(recorded_get):
    """Verify that a body that is not json is wrapped."""
    recorded_get.answer_with(StubResponse(json_error=ValueError("Expecting value")))

    with pytest.raises(RuntimeError, match="Expecting value"):
        Repository().get_inventory_markdown(ID_INVENTORY)


@pytest.mark.parametrize("payload", [{}, {"content": ""}, {"content": None}, {"conteudo": "x"}])
def test_an_answer_without_content_is_rejected(recorded_get, payload):
    """Verify that an answer without content is rejected."""
    recorded_get.answer_with(StubResponse(payload=payload))

    with pytest.raises(ValueError, match="content"):
        Repository().get_inventory_markdown(ID_INVENTORY)


def test_an_answer_that_is_not_an_object_is_rejected(recorded_get):
    """Verify that an answer that is not an object is rejected."""
    recorded_get.answer_with(StubResponse(payload=["not", "an", "object"]))

    with pytest.raises(ValueError, match="content"):
        Repository().get_inventory_markdown(ID_INVENTORY)
