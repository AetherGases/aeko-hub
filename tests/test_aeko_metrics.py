"""Verify aeko metrics behavior and error handling."""

import asyncio
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aeko_metrics.aeko_metrics import IRepository, IService
from aeko_metrics.database import query as q
from aeko_metrics.database.repository import Repository, metric_from_data
from aeko_metrics.entity import AgentMetric, Metric
from aeko_metrics.service import Service
from internal.http import aeko_metrics_handlers
from internal.shared import event_tracking
from internal.shared.event_tracking import (
    REQUEST_ID_HEADER,
    current_id_request,
    record_aeko_metrics,
    set_aeko_metrics_sink,
)
from internal.shared.logger import Module
from internal.shared.request_log import RequestLogMiddleware
from tests import fake_aeko
from tests.mongo_doubles import StubCollection, StubDatabase

ROUTE = "/aether-api/v1/ai/aeko-metrics"

LINE = re.compile(r"^\[aeko-hub\] \[(?P<module>\w+)\] \[[^\]]+\] (?P<description>.*)$")

AGENT_DOCUMENT = {
    "name": "Analista de Poluentes",
    "input_tokens": 11,
    "output_tokens": 22,
    "llm": "gemini-3.5-flash",
    "used_tools": ["climatiq_search", "calculator"],
}

METRIC_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c0bb",
    "id_request": "65a8b3d6c0f8e1d7f4b2c0aa",
    "latency": 4823,
    "error_description": None,
    "flow": "conversational",
    "used_agents": [AGENT_DOCUMENT],
}


def build_agent(**overrides) -> AgentMetric:
    """Build an agent metric fixture with optional field overrides."""
    fields = {
        "name": "Analista de Poluentes",
        "input_tokens": 11,
        "output_tokens": 22,
        "llm": "gemini-3.5-flash",
        "used_tools": ["climatiq_search", "calculator"],
    }
    fields.update(overrides)
    return AgentMetric(**fields)


def build_metric(**overrides) -> Metric:
    """Build a metric fixture with optional field overrides."""
    fields = {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "flow": "conversational",
        "used_agents": [build_agent()],
    }
    fields.update(overrides)
    return Metric(**fields)


def build_sdk_metrics(**overrides) -> fake_aeko.AekoMetrics:
    """Build SDK run metrics with optional field overrides."""
    fields = {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "flow": "conversational",
        "used_agents": [fake_aeko.AekoAgentMetrics(**AGENT_DOCUMENT)],
    }
    fields.update(overrides)
    return fake_aeko.AekoMetrics(**fields)


@pytest.fixture(autouse=True)
def no_color(monkeypatch):
    """Disable color output for deterministic log assertions."""
    monkeypatch.delenv('AEKO_LOG_COLOR', raising=False)


@pytest.fixture(autouse=True)
def no_aeko_sink():
    """Clear the SDK metric sink around each test."""
    set_aeko_metrics_sink(None)
    yield
    set_aeko_metrics_sink(None)


@pytest.fixture
def recorded():
    """Capture metric sink calls for the duration of the test."""
    metrics = []
    set_aeko_metrics_sink(metrics.append)
    yield metrics
    set_aeko_metrics_sink(None)


def descriptions(capsys, module):
    """Return captured operation descriptions for the selected module."""
    parsed = []
    for line in capsys.readouterr().out.splitlines():
        match = LINE.match(line)
        if match and match["module"] == module:
            parsed.append(match["description"])
    return parsed


def test_a_metric_carries_what_the_sdk_reported_about_one_request():
    """Verify that a metric carries what the sdk reported about one request."""
    metric = build_metric()

    assert metric.id_request == METRIC_DOCUMENT["id_request"]
    assert metric.latency == 4823
    assert metric.flow == "conversational"
    assert [agent.name for agent in metric.used_agents] == ["Analista de Poluentes"]


def test_a_successful_request_has_no_error_description():
    """Verify that a successful request has no error description."""
    assert build_metric().error_description is None


def test_a_failed_request_carries_why_it_failed():
    """Verify that a failed request carries why it failed."""
    metric = build_metric(
        error_description="no answer approved by the output guardrail or the response checker"
    )

    assert (
        metric.error_description
        == "no answer approved by the output guardrail or the response checker"
    )


def test_a_metric_arrives_without_an_identifier():
    """Verify that a metric arrives without an identifier."""
    assert build_metric().id is None


def test_a_metric_can_be_built_with_the_identifier_it_was_stored_under():
    """Verify that a metric can be built with the identifier it was stored under."""
    assert build_metric(id=METRIC_DOCUMENT["_id"]).id == METRIC_DOCUMENT["_id"]


def test_a_request_that_called_no_agent_still_is_a_metric():
    """Verify that a request that called no agent still is a metric."""
    assert Metric(id_request="r", latency=3, flow="conversational").used_agents == []


def test_an_agent_entry_carries_what_that_one_invocation_consumed():
    """Verify that an agent entry carries what that one invocation consumed."""
    agent = build_agent()

    assert (agent.input_tokens, agent.output_tokens) == (11, 22)
    assert agent.llm == "gemini-3.5-flash"
    assert agent.used_tools == ["climatiq_search", "calculator"]


def test_an_agent_that_reached_for_no_tool_lists_none():
    """Verify that an agent that reached for no tool lists none."""
    assert AgentMetric(name="FAQ").used_tools == []


def test_the_write_query_is_the_document_the_dashboard_reads():
    """Verify that the write query is the document the dashboard reads."""
    document = q.create_metric_query(build_metric())

    assert document == {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "error_description": None,
        "flow": "conversational",
        "used_agents": [AGENT_DOCUMENT],
    }


def test_the_write_query_never_names_the_identifier_itself():
    """Verify that the write query never names the identifier itself."""
    assert "_id" not in q.create_metric_query(build_metric(id="65a8b3d6c0f8e1d7f4b2c0bb"))


def test_the_write_query_keeps_every_invocation_of_a_repeated_agent():
    """Verify that the write query keeps every invocation of a repeated agent."""
    metric = build_metric(
        used_agents=[build_agent(name="Roteador"), build_agent(name="Roteador")]
    )

    stored = q.create_metric_query(metric)["used_agents"]

    assert [agent["name"] for agent in stored] == ["Roteador", "Roteador"]


def test_the_read_query_matches_every_row():
    """Verify that the read query matches every row."""
    assert q.get_all_metrics_query() == ({}, {})


def build_repository(collection=None):
    """Build a repository backed by configurable MongoDB doubles."""
    collection = collection or StubCollection()
    return Repository(StubDatabase(aeko_metrics=collection)), collection


def test_repository_implements_the_repository_interface():
    """Verify that repository implements the repository interface."""
    repository, _ = build_repository()

    assert isinstance(repository, IRepository)


def test_creating_a_metric_stores_the_document():
    """Verify that creating a metric stores the document."""
    repository, collection = build_repository()

    repository.create_metric(build_metric())

    assert collection.call_args("insert_one") == [(q.create_metric_query(build_metric()),)]


def test_creating_a_metric_returns_it_with_the_identifier_mongo_assigned():
    """Verify that creating a metric returns it with the identifier mongo assigned."""
    repository, _ = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c0bb"))

    stored = repository.create_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0bb"


def test_a_write_that_fails_is_reported_as_a_database_error():
    """Verify that a write that fails is reported as a database error."""
    repository, _ = build_repository(StubCollection(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error creating aeko metric in database"):
        repository.create_metric(build_metric())


def test_reading_the_metrics_maps_every_document():
    """Verify that reading the metrics maps every document."""
    repository, _ = build_repository(StubCollection(find_result=[METRIC_DOCUMENT]))

    metrics = repository.get_all_metrics()

    assert len(metrics) == 1
    assert metrics[0].id == METRIC_DOCUMENT["_id"]
    assert metrics[0].id_request == METRIC_DOCUMENT["id_request"]
    assert metrics[0].used_agents[0].used_tools == AGENT_DOCUMENT["used_tools"]


def test_an_empty_collection_reads_as_an_empty_list():
    """Verify that an empty collection reads as an empty list."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    assert repository.get_all_metrics() == []


def test_a_read_that_fails_is_reported_as_a_database_error():
    """Verify that a read that fails is reported as a database error."""
    repository, _ = build_repository(StubCollection(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error fetching aeko metrics from database"):
        repository.get_all_metrics()


def test_a_document_missing_fields_still_becomes_a_metric():
    """Verify that a document missing fields still becomes a metric."""
    metric = metric_from_data({"_id": "65a8b3d6c0f8e1d7f4b2c0bb"})

    assert metric.id_request == ""
    assert metric.latency == 0
    assert metric.flow == ""
    assert metric.error_description is None
    assert metric.used_agents == []


def test_an_agent_entry_missing_fields_still_reads():
    """Verify that an agent entry missing fields still reads."""
    metric = metric_from_data({**METRIC_DOCUMENT, "used_agents": [{"name": "FAQ"}]})

    agent = metric.used_agents[0]
    assert (agent.name, agent.input_tokens, agent.output_tokens) == ("FAQ", 0, 0)
    assert (agent.llm, agent.used_tools) == ("", [])


def test_a_document_without_an_identifier_reads_without_one():
    """Verify that a document without an identifier reads without one."""
    assert metric_from_data({"id_request": "r"}).id is None


def test_both_repository_methods_are_logged_as_database_operations(capsys):
    """Verify that both repository methods are logged as database operations."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    repository.create_metric(build_metric())
    repository.get_all_metrics()

    logged = descriptions(capsys, Module.DATABASE.value)
    assert any(line.startswith("aeko_metrics.create_metric succeeded") for line in logged)
    assert any(line.startswith("aeko_metrics.get_all_metrics succeeded") for line in logged)


class StubMetricsRepository:
    def __init__(self, metrics=None, error=None):
        self.metrics = metrics or []
        self.error = error
        self.created = []

    def create_metric(self, metric):
        """Persist a metric and return it with its database identifier."""
        self.created.append(metric)
        if self.error is not None:
            raise self.error
        metric.id = "65a8b3d6c0f8e1d7f4b2c0bb"
        return metric

    def get_all_metrics(self):
        """Retrieve all stored metrics."""
        if self.error is not None:
            raise self.error
        return self.metrics


def test_service_implements_the_service_interface():
    """Verify that service implements the service interface."""
    assert isinstance(Service(StubMetricsRepository()), IService)


def test_adding_a_metric_reaches_the_repository():
    """Verify that adding a metric reaches the repository."""
    repository = StubMetricsRepository()
    metric = build_metric()

    Service(repository).add_metric(metric)

    assert repository.created == [metric]


def test_adding_a_metric_returns_what_was_stored():
    """Verify that adding a metric returns what was stored."""
    stored = Service(StubMetricsRepository()).add_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0bb"


def test_a_failed_write_becomes_a_runtime_error():
    """Verify that a failed write becomes a runtime error."""
    service = Service(StubMetricsRepository(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error adding aeko metric"):
        service.add_metric(build_metric())


def test_reading_the_metrics_reaches_the_repository():
    """Verify that reading the metrics reaches the repository."""
    metrics = [build_metric()]

    assert Service(StubMetricsRepository(metrics)).get_all_metrics() == metrics


def test_a_failed_read_becomes_a_runtime_error():
    """Verify that a failed read becomes a runtime error."""
    service = Service(StubMetricsRepository(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error retrieving aeko metrics"):
        service.get_all_metrics()


def test_nothing_is_recorded_when_no_sink_is_registered():
    """Verify that nothing is recorded when no sink is registered."""
    assert record_aeko_metrics(build_sdk_metrics()) is False


def test_a_registered_sink_receives_what_the_sdk_reported(recorded):
    """Verify that a registered sink receives what the sdk reported."""
    metrics = build_sdk_metrics()

    assert record_aeko_metrics(metrics) is True
    assert recorded == [metrics]


def test_the_sink_can_be_taken_back_off(recorded):
    """Verify that the sink can be taken back off."""
    record_aeko_metrics(build_sdk_metrics())
    set_aeko_metrics_sink(None)

    assert record_aeko_metrics(build_sdk_metrics()) is False
    assert len(recorded) == 1


def test_a_run_that_reported_nothing_is_not_written(recorded):
    """Verify that a run that reported nothing is not written."""
    assert record_aeko_metrics(None) is False
    assert recorded == []


def test_a_sink_that_raises_is_given_up_on_rather_than_propagated(capsys):
    """Verify that a sink that raises is given up on rather than propagated."""
    def explode(metrics):
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("mongo is down")

    set_aeko_metrics_sink(explode)

    assert record_aeko_metrics(build_sdk_metrics()) is False
    assert any(
        "aeko_metrics.record gave up: RuntimeError: mongo is down" in line
        for line in descriptions(capsys, Module.DATABASE.value)
    )


def test_the_two_sinks_are_independent(recorded):
    """Verify that the two sinks are independent."""
    event_tracking.set_event_sink(None)

    assert record_aeko_metrics(build_sdk_metrics()) is True
    assert event_tracking._sink is None


def build_app(seen):
    """Build an ASGI application with configurable response behavior."""

    async def app(scope, receive, send):
        """Serve the simulated ASGI response used by the test."""
        seen.append(current_id_request())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return RequestLogMiddleware(app)


def call(app, path="/aether-api/v1/ai/ping"):
    """Invoke the ASGI application with a simulated request scope."""
    sent = []

    async def send(message):
        """Send or capture the request messages used by the test."""
        sent.append(message)

    async def receive():
        """Supply a simulated ASGI request message."""
        return {"type": "http.request"}

    scope = {"type": "http", "method": "GET", "path": path}
    asyncio.run(app(scope, receive, send))
    return sent


def answered_id(sent):
    """Extract the request identifier from captured ASGI response headers."""
    headers = dict(sent[0]["headers"])
    return headers[REQUEST_ID_HEADER.encode("ascii")].decode("ascii")


def test_outside_a_request_there_is_no_identifier_to_hand_over():
    """Verify that outside a request there is no identifier to hand over."""
    assert current_id_request() == ""


def test_a_request_is_readable_by_the_identifier_it_is_tracked_under():
    """Verify that a request is readable by the identifier it is tracked under."""
    seen = []

    sent = call(build_app(seen))

    assert seen == [answered_id(sent)]


def test_the_identifier_the_sdk_gets_is_the_one_the_row_is_stored_under(recorded):
    """Verify that the identifier the sdk gets is the one the row is stored under."""
    seen = []
    events = []
    event_tracking.set_event_sink(events.append)

    try:
        call(build_app(seen))
    finally:
        event_tracking.set_event_sink(None)

    assert seen == [events[0].id_request]


def test_two_requests_are_handed_two_identifiers():
    """Verify that two requests are handed two identifiers."""
    seen = []
    app = build_app(seen)

    call(app)
    call(app)

    assert len(set(seen)) == 2


def test_the_identifier_does_not_outlive_the_request_that_had_it():
    """Verify that the identifier does not outlive the request that had it."""
    call(build_app([]))

    assert current_id_request() == ""


class StubMetricsService:
    def __init__(self, metrics=None, error=None):
        self.metrics = metrics or []
        self.error = error
        self.calls = []

    def add_metric(self, metric):
        """Store a metric through the repository and return the stored entity."""
        raise NotImplementedError

    def get_all_metrics(self):
        """Retrieve all stored metrics."""
        self.calls.append("get_all_metrics")
        if self.error is not None:
            raise self.error
        return self.metrics


def build_client(service=None, db="fake-db"):
    """Build a test client or client double with the supplied dependencies."""
    app = FastAPI()
    app.include_router(aeko_metrics_handlers.router)
    app.state.db = db
    if service is not None:
        app.dependency_overrides[aeko_metrics_handlers.get_aeko_metrics_service] = lambda: service
    return TestClient(app)


def test_the_route_returns_every_row():
    """Verify that the route returns every row."""
    service = StubMetricsService([build_metric(id=METRIC_DOCUMENT["_id"])])

    response = build_client(service).get(ROUTE)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": METRIC_DOCUMENT["_id"],
            "id_request": METRIC_DOCUMENT["id_request"],
            "latency": 4823,
            "error_description": None,
            "flow": "conversational",
            "used_agents": [AGENT_DOCUMENT],
        }
    ]


def test_the_route_reports_a_failed_run_as_the_failure_it_was():
    """Verify that the route reports a failed run as the failure it was."""
    service = StubMetricsService(
        [build_metric(id=METRIC_DOCUMENT["_id"], error_description="boom")]
    )

    response = build_client(service).get(ROUTE)

    assert response.json()[0]["error_description"] == "boom"


def test_an_empty_database_answers_with_an_empty_list():
    """Verify that an empty database answers with an empty list."""
    response = build_client(StubMetricsService([])).get(ROUTE)

    assert response.status_code == 200
    assert response.json() == []


def test_the_route_maps_an_unexpected_error_to_500():
    """Verify that the route maps an unexpected error to 500."""
    response = build_client(StubMetricsService(error=RuntimeError("mongo exploded"))).get(ROUTE)

    assert response.status_code == 500
    assert "mongo exploded" in response.json()["detail"]


def test_the_route_returns_503_when_the_database_is_not_initialized():
    """Verify that the route returns 503 when the database is not initialized."""
    response = build_client(service=None, db=None).get(ROUTE)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_the_dependency_builds_the_real_stack():
    """Verify that the dependency builds the real stack."""
    database = StubDatabase(aeko_metrics=StubCollection(find_result=[METRIC_DOCUMENT]))

    response = build_client(service=None, db=database).get(ROUTE)

    assert response.status_code == 200
    assert response.json()[0]["id_request"] == METRIC_DOCUMENT["id_request"]


def test_only_the_read_is_exposed():
    """Verify that only the read is exposed."""
    app = FastAPI()
    app.include_router(aeko_metrics_handlers.router)

    methods = {method for route in app.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}


def test_the_route_is_registered_on_the_application(api_main):
    """Verify that the route is registered on the application."""
    assert "get" in api_main.app.openapi()["paths"].get(ROUTE, {})


def test_the_lifespan_registers_a_sink_and_takes_it_back_off(api_main):
    """Verify that the lifespan registers a sink and takes it back off."""
    with TestClient(api_main.app):
        assert event_tracking._aeko_sink is not None

    assert event_tracking._aeko_sink is None


def test_the_sink_writes_what_the_sdk_reported_into_the_collection(api_main):
    """Verify that the sink writes what the sdk reported into the collection."""
    database = StubDatabase(aeko_metrics=StubCollection())

    api_main.build_aeko_metrics_sink(database)(build_sdk_metrics())

    (document,) = database["aeko_metrics"].call_args("insert_one")[0]
    assert document == {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "error_description": None,
        "flow": "conversational",
        "used_agents": [AGENT_DOCUMENT],
    }


def test_the_sink_carries_a_failed_run_across(api_main):
    """Verify that the sink carries a failed run across."""
    database = StubDatabase(aeko_metrics=StubCollection())

    api_main.build_aeko_metrics_sink(database)(
        build_sdk_metrics(error_description="MalformedAgentOutputError: no sections")
    )

    (document,) = database["aeko_metrics"].call_args("insert_one")[0]
    assert document["error_description"] == "MalformedAgentOutputError: no sections"
