"""Tests for the `aeko_metrics` domain and the SDK tracking that feeds it.

`hub_metrics` stores what the *gateway* did with a request — how long it took,
what it answered, which endpoint it was. It knows nothing about what happened
inside, and a request that spent nine of its ten seconds in one agent looks
exactly like one that spent them in Mongo.

Since 3.x the SDK answers that question itself: both entry points take the
`id_request` the API already minted and hand back an `AekoMetrics` beside the
answer — how long the run took, whether it failed, which flow it was, and one
entry per agent *invocation* with its tokens, its model and the tools it
actually reached for. `aeko_metrics` is the domain that stores those rows.

What is worth pinning down:

* the domain itself — entity, query helpers, repository and service, the same
  four layers `hub_metrics` and every other domain here has;
* the identifier — the SDK is handed the very id the middleware minted, so a
  row here and a row in `hub_metrics` name the same request. It is a *field*,
  not the `_id`: the two collections would otherwise fight over one value;
* the sink — `shared` never imports a domain and never imports the SDK, so it
  holds a function and `cmd/api/main.py` registers the one that writes;
* that a failed run is stored too — the tracking rides out on the exception,
  and a request that failed is the one worth having recorded;
* that a metric which fails to be written never takes the request down with it.

No Mongo and no network: the same doubles the sibling modules use.
"""

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
from shared import event_tracking
from shared.event_tracking import (
    REQUEST_ID_HEADER,
    current_id_request,
    record_aeko_metrics,
    set_aeko_metrics_sink,
)
from shared.logger import COLOR_ENV_VAR, Module
from shared.request_log import RequestLogMiddleware
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
    fields = {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "flow": "conversational",
        "used_agents": [build_agent()],
    }
    fields.update(overrides)
    return Metric(**fields)


def build_sdk_metrics(**overrides) -> fake_aeko.AekoMetrics:
    """What the SDK hands back, as the composition root receives it."""
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
    """These read the description; escape codes would only be in the way."""
    monkeypatch.delenv(COLOR_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def no_aeko_sink():
    """No test may inherit another's sink, and none may leak one."""
    set_aeko_metrics_sink(None)
    yield
    set_aeko_metrics_sink(None)


@pytest.fixture
def recorded():
    """A sink that keeps everything it is handed, for the length of the test."""
    metrics = []
    set_aeko_metrics_sink(metrics.append)
    yield metrics
    set_aeko_metrics_sink(None)


def descriptions(capsys, module):
    parsed = []
    for line in capsys.readouterr().out.splitlines():
        match = LINE.match(line)
        if match and match["module"] == module:
            parsed.append(match["description"])
    return parsed


# ---------------------------------------------------------------------------
# entity
# ---------------------------------------------------------------------------
def test_a_metric_carries_what_the_sdk_reported_about_one_request():
    metric = build_metric()

    assert metric.id_request == METRIC_DOCUMENT["id_request"]
    assert metric.latency == 4823
    assert metric.flow == "conversational"
    assert [agent.name for agent in metric.used_agents] == ["Analista de Poluentes"]


def test_a_successful_request_has_no_error_description():
    assert build_metric().error_description is None


def test_a_failed_request_carries_why_it_failed():
    metric = build_metric(error_description="no answer approved by the output guardrail")

    assert metric.error_description == "no answer approved by the output guardrail"


def test_a_metric_arrives_without_an_identifier():
    """Unlike `hub_metrics`, the `_id` here is the database's to assign."""
    assert build_metric().id is None


def test_a_metric_can_be_built_with_the_identifier_it_was_stored_under():
    assert build_metric(id=METRIC_DOCUMENT["_id"]).id == METRIC_DOCUMENT["_id"]


def test_a_request_that_called_no_agent_still_is_a_metric():
    assert Metric(id_request="r", latency=3, flow="conversational").used_agents == []


def test_an_agent_entry_carries_what_that_one_invocation_consumed():
    agent = build_agent()

    assert (agent.input_tokens, agent.output_tokens) == (11, 22)
    assert agent.llm == "gemini-3.5-flash"
    assert agent.used_tools == ["climatiq_search", "calculator"]


def test_an_agent_that_reached_for_no_tool_lists_none():
    assert AgentMetric(name="FAQ").used_tools == []


# ---------------------------------------------------------------------------
# the query helpers
# ---------------------------------------------------------------------------
def test_the_write_query_is_the_document_the_dashboard_reads():
    document = q.create_metric_query(build_metric())

    assert document == {
        "id_request": METRIC_DOCUMENT["id_request"],
        "latency": 4823,
        "error_description": None,
        "flow": "conversational",
        "used_agents": [AGENT_DOCUMENT],
    }


def test_the_write_query_never_names_the_identifier_itself():
    """The `_id` is Mongo's here: `hub_metrics` already stores a row under the
    request's own identifier, and two collections cannot own one value."""
    assert "_id" not in q.create_metric_query(build_metric(id="65a8b3d6c0f8e1d7f4b2c0bb"))


def test_the_write_query_keeps_every_invocation_of_a_repeated_agent():
    metric = build_metric(
        used_agents=[build_agent(name="Roteador"), build_agent(name="Roteador")]
    )

    stored = q.create_metric_query(metric)["used_agents"]

    assert [agent["name"] for agent in stored] == ["Roteador", "Roteador"]


def test_the_read_query_matches_every_row():
    assert q.get_all_metrics_query() == ({}, {})


# ---------------------------------------------------------------------------
# the repository
# ---------------------------------------------------------------------------
def build_repository(collection=None):
    collection = collection or StubCollection()
    return Repository(StubDatabase(aeko_metrics=collection)), collection


def test_repository_implements_the_repository_interface():
    repository, _ = build_repository()

    assert isinstance(repository, IRepository)


def test_creating_a_metric_stores_the_document():
    repository, collection = build_repository()

    repository.create_metric(build_metric())

    assert collection.call_args("insert_one") == [(q.create_metric_query(build_metric()),)]


def test_creating_a_metric_returns_it_with_the_identifier_mongo_assigned():
    repository, _ = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c0bb"))

    stored = repository.create_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0bb"


def test_a_write_that_fails_is_reported_as_a_database_error():
    repository, _ = build_repository(StubCollection(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error creating aeko metric in database"):
        repository.create_metric(build_metric())


def test_reading_the_metrics_maps_every_document():
    repository, _ = build_repository(StubCollection(find_result=[METRIC_DOCUMENT]))

    metrics = repository.get_all_metrics()

    assert len(metrics) == 1
    assert metrics[0].id == METRIC_DOCUMENT["_id"]
    assert metrics[0].id_request == METRIC_DOCUMENT["id_request"]
    assert metrics[0].used_agents[0].used_tools == AGENT_DOCUMENT["used_tools"]


def test_an_empty_collection_reads_as_an_empty_list():
    repository, _ = build_repository(StubCollection(find_result=[]))

    assert repository.get_all_metrics() == []


def test_a_read_that_fails_is_reported_as_a_database_error():
    repository, _ = build_repository(StubCollection(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error fetching aeko metrics from database"):
        repository.get_all_metrics()


def test_a_document_missing_fields_still_becomes_a_metric():
    """A row written before a field existed is worth more than a broken read."""
    metric = metric_from_data({"_id": "65a8b3d6c0f8e1d7f4b2c0bb"})

    assert metric.id_request == ""
    assert metric.latency == 0
    assert metric.flow == ""
    assert metric.error_description is None
    assert metric.used_agents == []


def test_an_agent_entry_missing_fields_still_reads():
    metric = metric_from_data({**METRIC_DOCUMENT, "used_agents": [{"name": "FAQ"}]})

    agent = metric.used_agents[0]
    assert (agent.name, agent.input_tokens, agent.output_tokens) == ("FAQ", 0, 0)
    assert (agent.llm, agent.used_tools) == ("", [])


def test_a_document_without_an_identifier_reads_without_one():
    assert metric_from_data({"id_request": "r"}).id is None


def test_both_repository_methods_are_logged_as_database_operations(capsys):
    repository, _ = build_repository(StubCollection(find_result=[]))

    repository.create_metric(build_metric())
    repository.get_all_metrics()

    logged = descriptions(capsys, Module.DATABASE.value)
    assert any(line.startswith("aeko_metrics.create_metric succeeded") for line in logged)
    assert any(line.startswith("aeko_metrics.get_all_metrics succeeded") for line in logged)


# ---------------------------------------------------------------------------
# the service
# ---------------------------------------------------------------------------
class StubMetricsRepository:
    def __init__(self, metrics=None, error=None):
        self.metrics = metrics or []
        self.error = error
        self.created = []

    def create_metric(self, metric):
        self.created.append(metric)
        if self.error is not None:
            raise self.error
        metric.id = "65a8b3d6c0f8e1d7f4b2c0bb"
        return metric

    def get_all_metrics(self):
        if self.error is not None:
            raise self.error
        return self.metrics


def test_service_implements_the_service_interface():
    assert isinstance(Service(StubMetricsRepository()), IService)


def test_adding_a_metric_reaches_the_repository():
    repository = StubMetricsRepository()
    metric = build_metric()

    Service(repository).add_metric(metric)

    assert repository.created == [metric]


def test_adding_a_metric_returns_what_was_stored():
    stored = Service(StubMetricsRepository()).add_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0bb"


def test_a_failed_write_becomes_a_runtime_error():
    service = Service(StubMetricsRepository(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error adding aeko metric"):
        service.add_metric(build_metric())


def test_reading_the_metrics_reaches_the_repository():
    metrics = [build_metric()]

    assert Service(StubMetricsRepository(metrics)).get_all_metrics() == metrics


def test_a_failed_read_becomes_a_runtime_error():
    service = Service(StubMetricsRepository(error=RuntimeError("mongo is down")))

    with pytest.raises(RuntimeError, match="Error retrieving aeko metrics"):
        service.get_all_metrics()


# ---------------------------------------------------------------------------
# the sink
# ---------------------------------------------------------------------------
def test_nothing_is_recorded_when_no_sink_is_registered():
    assert record_aeko_metrics(build_sdk_metrics()) is False


def test_a_registered_sink_receives_what_the_sdk_reported(recorded):
    metrics = build_sdk_metrics()

    assert record_aeko_metrics(metrics) is True
    assert recorded == [metrics]


def test_the_sink_can_be_taken_back_off(recorded):
    record_aeko_metrics(build_sdk_metrics())
    set_aeko_metrics_sink(None)

    assert record_aeko_metrics(build_sdk_metrics()) is False
    assert len(recorded) == 1


def test_a_run_that_reported_nothing_is_not_written(recorded):
    """An error raised outside a request carries no tracking at all."""
    assert record_aeko_metrics(None) is False
    assert recorded == []


def test_a_sink_that_raises_is_given_up_on_rather_than_propagated(capsys):
    def explode(metrics):
        raise RuntimeError("mongo is down")

    set_aeko_metrics_sink(explode)

    assert record_aeko_metrics(build_sdk_metrics()) is False
    assert any(
        "aeko_metrics.record gave up: RuntimeError: mongo is down" in line
        for line in descriptions(capsys, Module.DATABASE.value)
    )


def test_the_two_sinks_are_independent(recorded):
    """The request's own row and the SDK's are tracked by different halves."""
    event_tracking.set_event_sink(None)

    assert record_aeko_metrics(build_sdk_metrics()) is True
    assert event_tracking._sink is None


# ---------------------------------------------------------------------------
# the request identifier the SDK is handed
# ---------------------------------------------------------------------------
def build_app(seen):
    """An ASGI app that reports the identifier its request is being tracked by."""

    async def app(scope, receive, send):
        seen.append(current_id_request())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return RequestLogMiddleware(app)


def call(app, path="/aether-api/v1/ai/ping"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "method": "GET", "path": path}
    asyncio.run(app(scope, receive, send))
    return sent


def answered_id(sent):
    headers = dict(sent[0]["headers"])
    return headers[REQUEST_ID_HEADER.encode("ascii")].decode("ascii")


def test_outside_a_request_there_is_no_identifier_to_hand_over():
    assert current_id_request() == ""


def test_a_request_is_readable_by_the_identifier_it_is_tracked_under():
    seen = []

    sent = call(build_app(seen))

    assert seen == [answered_id(sent)]


def test_the_identifier_the_sdk_gets_is_the_one_the_row_is_stored_under(recorded):
    seen = []
    events = []
    event_tracking.set_event_sink(events.append)

    try:
        call(build_app(seen))
    finally:
        event_tracking.set_event_sink(None)

    assert seen == [events[0].id_request]


def test_two_requests_are_handed_two_identifiers():
    seen = []
    app = build_app(seen)

    call(app)
    call(app)

    assert len(set(seen)) == 2


def test_the_identifier_does_not_outlive_the_request_that_had_it():
    call(build_app([]))

    assert current_id_request() == ""


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------
class StubMetricsService:
    def __init__(self, metrics=None, error=None):
        self.metrics = metrics or []
        self.error = error
        self.calls = []

    def add_metric(self, metric):
        raise NotImplementedError

    def get_all_metrics(self):
        self.calls.append("get_all_metrics")
        if self.error is not None:
            raise self.error
        return self.metrics


def build_client(service=None, db="fake-db"):
    app = FastAPI()
    app.include_router(aeko_metrics_handlers.router)
    app.state.db = db
    if service is not None:
        app.dependency_overrides[aeko_metrics_handlers.get_aeko_metrics_service] = lambda: service
    return TestClient(app)


def test_the_route_returns_every_row():
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
    service = StubMetricsService(
        [build_metric(id=METRIC_DOCUMENT["_id"], error_description="boom")]
    )

    response = build_client(service).get(ROUTE)

    assert response.json()[0]["error_description"] == "boom"


def test_an_empty_database_answers_with_an_empty_list():
    response = build_client(StubMetricsService([])).get(ROUTE)

    assert response.status_code == 200
    assert response.json() == []


def test_the_route_maps_an_unexpected_error_to_500():
    response = build_client(StubMetricsService(error=RuntimeError("mongo exploded"))).get(ROUTE)

    assert response.status_code == 500
    assert "mongo exploded" in response.json()["detail"]


def test_the_route_returns_503_when_the_database_is_not_initialized():
    response = build_client(service=None, db=None).get(ROUTE)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_the_dependency_builds_the_real_stack():
    """The route with nothing overridden: handler, service, repository, Mongo."""
    database = StubDatabase(aeko_metrics=StubCollection(find_result=[METRIC_DOCUMENT]))

    response = build_client(service=None, db=database).get(ROUTE)

    assert response.status_code == 200
    assert response.json()[0]["id_request"] == METRIC_DOCUMENT["id_request"]


def test_only_the_read_is_exposed():
    """Writing a row is the SDK's account of a run, not a caller's to post."""
    app = FastAPI()
    app.include_router(aeko_metrics_handlers.router)

    methods = {method for route in app.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}


# ---------------------------------------------------------------------------
# the wiring
# ---------------------------------------------------------------------------
def test_the_route_is_registered_on_the_application(api_main):
    assert "get" in api_main.app.openapi()["paths"].get(ROUTE, {})


def test_the_lifespan_registers_a_sink_and_takes_it_back_off(api_main):
    with TestClient(api_main.app):
        assert event_tracking._aeko_sink is not None

    assert event_tracking._aeko_sink is None


def test_the_sink_writes_what_the_sdk_reported_into_the_collection(api_main):
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
    database = StubDatabase(aeko_metrics=StubCollection())

    api_main.build_aeko_metrics_sink(database)(
        build_sdk_metrics(error_description="MalformedAgentOutputError: no sections")
    )

    (document,) = database["aeko_metrics"].call_args("insert_one")[0]
    assert document["error_description"] == "MalformedAgentOutputError: no sections"
