"""Tests for the `hub_metrics` domain and the event tracking that feeds it.

The log block of `shared/request_log.py` says what a request did while the
process is alive; nothing of it survives a restart, so no dashboard can be
built on top of it. Event tracking is the other half: every request leaves one
row — under the `_id` its caller was answered with, saying how long it took,
what it answered and which endpoint it was — and `hub_metrics` is the domain
that stores those rows and hands them back.

What is worth pinning down:

* the domain itself — entity, query helpers, repository and service, the same
  four layers every other domain here has;
* the tracking — one event per request, whatever the request did, with the
  route *template* as the endpoint so a dashboard can group by it;
* the sink — `shared` never imports a domain, so `cmd/api/main.py` registers
  the function that writes. Without one, tracking is a no-op;
* the response header — the identifier goes back to the caller, and it is the
  same one the row was stored under, or it names nothing;
* that a metric which fails to be written never takes the request down with it.

No Mongo and no network: the same doubles the sibling modules use.
"""

import asyncio
import re
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_metrics.database import query as q
from hub_metrics.database.repository import Repository, metric_from_data
from hub_metrics.entity import Metric
from hub_metrics.hub_metrics import IRepository, IService
from hub_metrics.service import Service
from internal.http import hub_metrics_handlers
from shared import event_tracking
from shared.event_tracking import (
    CRASHED_STATUS,
    REQUEST_ID_HEADER,
    UNKNOWN_ENDPOINT,
    Event,
    endpoint_of,
    new_id_request,
    record_event,
    set_event_sink,
)
from shared.logger import COLOR_ENV_VAR, Module
from shared.operation import operation
from shared.request_log import RequestLogMiddleware
from tests.mongo_doubles import StubCollection, StubDatabase

ROUTE = "/aether-api/v1/ai/hub-metrics"

HEADER = re.compile(r"^\[aeko-hub\] \[request\] \[[^\]]+\] (?P<description>.*)$")
LINE = re.compile(r"^\[aeko-hub\] \[(?P<module>\w+)\] \[[^\]]+\] (?P<description>.*)$")

USER_ROUTE_TEMPLATE = "/aether-api/v1/ai/user/{id_external_user}"

METRIC_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c0aa",
    "latency": "12.4ms",
    "response_status": 200,
    "endpoint": USER_ROUTE_TEMPLATE,
}


def build_metric(**overrides) -> Metric:
    fields = {
        "latency": "12.4ms",
        "response_status": 200,
        "endpoint": USER_ROUTE_TEMPLATE,
    }
    fields.update(overrides)
    return Metric(**fields)


@pytest.fixture(autouse=True)
def no_color(monkeypatch):
    """These read the description; escape codes would only be in the way."""
    monkeypatch.delenv(COLOR_ENV_VAR, raising=False)


@pytest.fixture
def recorded():
    """A sink that keeps every event, registered for the length of the test."""
    events = []
    set_event_sink(events.append)
    yield events
    set_event_sink(None)


def entries(capsys):
    parsed = []
    for line in capsys.readouterr().out.splitlines():
        match = LINE.match(line)
        if match:
            parsed.append((match["module"], match["description"]))
    return parsed


def descriptions(capsys, module):
    return [description for name, description in entries(capsys) if name == module]


# ---------------------------------------------------------------------------
# entity
# ---------------------------------------------------------------------------
def test_a_metric_carries_the_three_fields_of_one_request():
    metric = build_metric()

    assert metric.latency == "12.4ms"
    assert metric.response_status == 200
    assert metric.endpoint == USER_ROUTE_TEMPLATE


def test_a_metric_may_arrive_without_an_identifier():
    """Not the normal path — a tracked request already has the `_id` it was
    answered with — but a row without one is still worth writing."""
    assert build_metric().id is None


def test_a_metric_can_be_built_with_the_identifier_it_was_stored_under():
    assert build_metric(id=METRIC_DOCUMENT["_id"]).id == METRIC_DOCUMENT["_id"]


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------
def test_the_write_query_is_the_document_the_dashboard_reads():
    assert q.create_metric_query(build_metric()) == {
        "latency": "12.4ms",
        "response_status": 200,
        "endpoint": USER_ROUTE_TEMPLATE,
    }


def test_the_write_query_stores_the_identifier_the_caller_was_answered_with():
    """The header named a row; `_id` is what makes that row findable."""
    document = q.create_metric_query(build_metric(id=METRIC_DOCUMENT["_id"]))

    assert document["_id"] == ObjectId(METRIC_DOCUMENT["_id"])


def test_a_metric_without_an_identifier_lets_mongo_assign_one():
    """No header was answered with it, so there is nothing to be findable by."""
    assert "_id" not in q.create_metric_query(build_metric())


def test_the_read_query_matches_every_row():
    query, projection = q.get_all_metrics_query()

    assert query == {}
    assert projection == {}


# ---------------------------------------------------------------------------
# repository
# ---------------------------------------------------------------------------
def build_repository(collection=None):
    database = StubDatabase(hub_metrics=collection or StubCollection())
    return Repository(database), database


def test_repository_implements_the_repository_interface():
    assert issubclass(Repository, IRepository)
    assert Repository.__abstractmethods__ == frozenset()


def test_creating_a_metric_stores_the_document():
    repository, database = build_repository()

    repository.create_metric(build_metric())

    (document,) = database.hub_metrics.call_args("insert_one")[0]
    assert document == q.create_metric_query(build_metric())


def test_creating_a_metric_returns_it_with_the_identifier_mongo_assigned():
    repository, _ = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c0aa"))

    stored = repository.create_metric(build_metric())

    assert stored.id == "65a8b3d6c0f8e1d7f4b2c0aa"


def test_a_write_that_fails_is_reported_as_a_database_error():
    repository, _ = build_repository(StubCollection(error=ConnectionError("connection refused")))

    with pytest.raises(RuntimeError, match="connection refused"):
        repository.create_metric(build_metric())


def test_reading_the_metrics_maps_every_document():
    repository, _ = build_repository(StubCollection(find_result=[METRIC_DOCUMENT]))

    (metric,) = repository.get_all_metrics()

    assert metric.id == METRIC_DOCUMENT["_id"]
    assert metric.latency == "12.4ms"
    assert metric.response_status == 200
    assert metric.endpoint == USER_ROUTE_TEMPLATE


def test_an_empty_collection_reads_as_an_empty_list():
    repository, _ = build_repository(StubCollection(find_result=[]))

    assert repository.get_all_metrics() == []


def test_a_read_that_fails_is_reported_as_a_database_error():
    repository, _ = build_repository(StubCollection(error=ConnectionError("connection refused")))

    with pytest.raises(RuntimeError, match="connection refused"):
        repository.get_all_metrics()


def test_a_document_missing_fields_still_becomes_a_metric():
    """A row written before a field existed must not break the dashboard."""
    metric = metric_from_data({"_id": "1"})

    assert metric.id == "1"
    assert metric.latency == ""
    assert metric.response_status == 0


def test_both_repository_methods_are_logged_as_database_operations(capsys):
    repository, _ = build_repository(StubCollection(find_result=[]))

    repository.create_metric(build_metric())
    repository.get_all_metrics()

    written = descriptions(capsys, "database")
    assert written[0].startswith("hub_metrics.create_metric succeeded in ")
    assert written[1].startswith("hub_metrics.get_all_metrics succeeded in ")


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------
class StubMetricsRepository:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result

    def create_metric(self, metric):
        return self._run("create_metric", metric)

    def get_all_metrics(self):
        return self._run("get_all_metrics")


def test_service_implements_the_service_interface():
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_adding_a_metric_reaches_the_repository():
    repository = StubMetricsRepository()
    metric = build_metric()

    Service(repository).add_metric(metric)

    assert repository.calls == [("create_metric", metric)]


def test_adding_a_metric_returns_what_was_stored():
    stored = build_metric(id="1")

    assert Service(StubMetricsRepository(result=stored)).add_metric(build_metric()) is stored


def test_a_failed_write_becomes_a_runtime_error():
    service = Service(StubMetricsRepository(error=RuntimeError("mongo exploded")))

    with pytest.raises(RuntimeError, match="mongo exploded"):
        service.add_metric(build_metric())


def test_reading_the_metrics_reaches_the_repository():
    repository = StubMetricsRepository(result=[build_metric()])

    assert len(Service(repository).get_all_metrics()) == 1
    assert repository.calls == [("get_all_metrics",)]


def test_a_failed_read_becomes_a_runtime_error():
    service = Service(StubMetricsRepository(error=RuntimeError("mongo exploded")))

    with pytest.raises(RuntimeError, match="mongo exploded"):
        service.get_all_metrics()


# ---------------------------------------------------------------------------
# shared/event_tracking.py — the sink
# ---------------------------------------------------------------------------
EVENT = Event(
    id_request=METRIC_DOCUMENT["_id"],
    latency="12.4ms",
    response_status=200,
    endpoint="/x",
)


def test_an_event_carries_exactly_what_a_metric_needs():
    assert EVENT.id_request == METRIC_DOCUMENT["_id"]
    assert EVENT.latency == "12.4ms"
    assert EVENT.response_status == 200
    assert EVENT.endpoint == "/x"


def test_nothing_is_recorded_when_no_sink_is_registered():
    """The suite, and any process that never wired a database, track nothing."""
    assert record_event(EVENT) is False


def test_a_registered_sink_receives_the_event(recorded):
    assert record_event(EVENT) is True
    assert recorded == [EVENT]


def test_the_sink_can_be_taken_back_off():
    events = []
    set_event_sink(events.append)
    set_event_sink(None)

    assert record_event(EVENT) is False
    assert events == []


def test_a_sink_that_raises_is_given_up_on_rather_than_propagated(capsys):
    """A dashboard row is never worth failing the request that produced it."""

    def explode(event):
        raise RuntimeError("connection refused")

    set_event_sink(explode)
    try:
        assert record_event(EVENT) is False
    finally:
        set_event_sink(None)

    assert descriptions(capsys, "database")[0].startswith("hub_metrics.record gave up: ")


def test_every_request_identifier_is_its_own():
    assert new_id_request() != new_id_request()


def test_the_request_identifier_is_the_one_mongo_will_store_it_under():
    """It is answered in a header before the row exists, so it must be an `_id`."""
    assert ObjectId.is_valid(new_id_request())


# ---------------------------------------------------------------------------
# shared/event_tracking.py — the endpoint
# ---------------------------------------------------------------------------
def test_the_endpoint_is_the_route_template_not_the_path_that_was_asked_for():
    """`/user/12345` and `/user/999` are one row on the dashboard, not two."""
    scope = {
        "type": "http",
        "path": "/aether-api/v1/ai/user/12345",
        "route": SimpleNamespace(path=USER_ROUTE_TEMPLATE),
    }

    assert endpoint_of(scope) == USER_ROUTE_TEMPLATE


def test_a_path_that_matched_no_route_is_kept_as_it_came():
    assert endpoint_of({"type": "http", "path": "/no-such-endpoint"}) == "/no-such-endpoint"


def test_a_route_that_carries_no_template_falls_back_to_the_path():
    """A mount answers without one, and a row still has to say something."""
    scope = {"type": "http", "path": "/mounted/thing", "route": SimpleNamespace()}

    assert endpoint_of(scope) == "/mounted/thing"


def test_a_scope_without_even_a_path_still_produces_a_row():
    assert endpoint_of({"type": "http"}) == UNKNOWN_ENDPOINT


# ---------------------------------------------------------------------------
# the middleware: one event per request
# ---------------------------------------------------------------------------
def build_app(operations=(), status=200, raises=None):
    async def app(scope, receive, send):
        for module, name in operations:
            with operation(module, name):
                pass

        if raises is not None:
            raise raises

        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


async def call(app, method="GET", path="/x", sent=None):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if sent is not None:
            sent.append(message)

    await app({"type": "http", "method": method, "path": path, "query_string": b""}, receive, send)


def answered_ids(sent):
    """The `x-request-id` of every response start message in `sent`."""
    return [
        value.decode()
        for message in sent
        if message["type"] == "http.response.start"
        for name, value in message["headers"]
        if name == REQUEST_ID_HEADER.encode()
    ]


def test_a_request_leaves_exactly_one_event(recorded):
    asyncio.run(call(RequestLogMiddleware(build_app([(Module.DATABASE, "user.get_user")]))))

    assert len(recorded) == 1


def test_the_event_carries_the_status_that_was_answered(recorded):
    asyncio.run(call(RequestLogMiddleware(build_app(status=404))))

    assert recorded[0].response_status == 404


def test_the_event_carries_the_path_of_the_request(recorded):
    asyncio.run(call(RequestLogMiddleware(build_app()), path="/one"))

    assert recorded[0].endpoint == "/one"


def test_the_event_latency_is_the_one_the_block_reports(capsys, recorded):
    asyncio.run(call(RequestLogMiddleware(build_app())))

    headers = [HEADER.match(line) for line in capsys.readouterr().out.splitlines()]
    (header,) = [match for match in headers if match]
    assert f" in {recorded[0].latency}" in header["description"]


def test_two_requests_are_two_rows_with_two_identifiers(recorded):
    app = RequestLogMiddleware(build_app())

    asyncio.run(call(app, path="/one"))
    asyncio.run(call(app, path="/two"))

    first, second = recorded
    assert first.id_request != second.id_request


def test_a_request_that_ran_no_operation_is_still_tracked(recorded):
    """Event tracking is per request, not per operation."""
    asyncio.run(call(RequestLogMiddleware(build_app())))

    assert len(recorded) == 1


def test_a_request_that_crashed_is_tracked_as_a_server_error(recorded):
    app = RequestLogMiddleware(build_app(raises=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        asyncio.run(call(app))

    assert recorded[0].response_status == CRASHED_STATUS


def test_a_lifespan_message_is_not_a_request_and_leaves_no_row(recorded):
    async def app(scope, receive, send):
        return None

    asyncio.run(RequestLogMiddleware(app)({"type": "lifespan"}, None, None))

    assert recorded == []


def test_a_sink_that_fails_does_not_fail_the_request(capsys):
    def explode(event):
        raise RuntimeError("connection refused")

    set_event_sink(explode)
    try:
        asyncio.run(call(RequestLogMiddleware(build_app())))
    finally:
        set_event_sink(None)

    assert any(HEADER.match(line) for line in capsys.readouterr().out.splitlines())


def test_the_row_is_written_before_the_block_closes(capsys):
    """So the write itself is one of the operations the block lists."""

    def sink(event):
        with operation(Module.DATABASE, "hub_metrics.create_metric"):
            pass

    set_event_sink(sink)
    try:
        asyncio.run(call(RequestLogMiddleware(build_app())))
    finally:
        set_event_sink(None)

    lines = capsys.readouterr().out.splitlines()
    assert "(1 operation)" in lines[0]
    assert "hub_metrics.create_metric" in lines[1]


# ---------------------------------------------------------------------------
# the response header
# ---------------------------------------------------------------------------
def test_the_response_carries_the_identifier_back_to_the_caller():
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app()), sent=sent))

    assert len(answered_ids(sent)) == 1


def test_the_header_is_the_identifier_the_row_was_stored_under(recorded):
    """The whole point: a caller can name the row that explains their request."""
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app()), sent=sent))

    assert answered_ids(sent) == [recorded[0].id_request]


def test_two_requests_are_answered_with_two_identifiers():
    first, second = [], []
    app = RequestLogMiddleware(build_app())

    asyncio.run(call(app, sent=first))
    asyncio.run(call(app, sent=second))

    assert answered_ids(first) != answered_ids(second)


def test_a_failing_response_carries_it_too():
    """A 500 is the response whose identifier is worth the most."""
    sent = []

    asyncio.run(call(RequestLogMiddleware(build_app(status=500)), sent=sent))

    assert len(answered_ids(sent)) == 1


def test_the_headers_the_application_set_are_kept():
    sent = []

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(call(RequestLogMiddleware(app), sent=sent))

    names = [name for name, _ in sent[0]["headers"]]
    assert b"content-type" in names
    assert REQUEST_ID_HEADER.encode() in names


def test_an_identifier_the_application_wrote_itself_is_replaced_not_added_to():
    """There is one identifier per request; two would only raise the question."""
    sent = []

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(REQUEST_ID_HEADER.encode(), b"made-up")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(call(RequestLogMiddleware(app), sent=sent))

    (answered,) = answered_ids(sent)
    assert answered != "made-up"


def test_a_response_that_never_started_has_nowhere_to_carry_it():
    """The exception goes up untouched; the row is still written."""
    sent = []
    app = RequestLogMiddleware(build_app(raises=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        asyncio.run(call(app, sent=sent))

    assert answered_ids(sent) == []


def test_the_real_application_answers_with_the_identifier_of_the_stored_row(api_main):
    """The header is the `_id`: the caller can be looked up by primary key."""
    with TestClient(api_main.app) as client:
        response = client.get("/aether-api/v1/ai/user/12345")
        stored = list(api_main.db["hub_metrics"].documents)

    assert response.headers["X-Request-Id"] == str(stored[0]["_id"])


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
    app.include_router(hub_metrics_handlers.router)
    app.state.db = db
    if service is not None:
        app.dependency_overrides[hub_metrics_handlers.get_hub_metrics_service] = lambda: service
    return TestClient(app)


def test_the_route_returns_every_row():
    service = StubMetricsService([build_metric(id=METRIC_DOCUMENT["_id"])])

    response = build_client(service).get(ROUTE)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": METRIC_DOCUMENT["_id"],
            "latency": "12.4ms",
            "response_status": 200,
            "endpoint": USER_ROUTE_TEMPLATE,
        }
    ]


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
    database = StubDatabase(hub_metrics=StubCollection(find_result=[METRIC_DOCUMENT]))

    response = build_client(service=None, db=database).get(ROUTE)

    assert response.status_code == 200
    assert response.json()[0]["id"] == METRIC_DOCUMENT["_id"]


def test_only_the_read_is_exposed():
    """`add_metric` is the middleware's business, not the caller's."""
    app = FastAPI()
    app.include_router(hub_metrics_handlers.router)

    methods = {method for route in app.routes for method in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}


# ---------------------------------------------------------------------------
# the wiring
# ---------------------------------------------------------------------------
def test_the_route_is_registered_on_the_application(api_main):
    assert "get" in api_main.app.openapi()["paths"].get(ROUTE, {})


def test_the_lifespan_registers_a_sink_and_takes_it_back_off(api_main):
    with TestClient(api_main.app):
        assert event_tracking._sink is not None

    assert event_tracking._sink is None


def test_every_request_of_the_real_application_lands_in_the_collection(api_main):
    """End to end: the middleware, the sink, the service, the repository, Mongo."""
    with TestClient(api_main.app) as client:
        client.get("/no-such-endpoint")
        stored = list(api_main.db["hub_metrics"].documents)

    assert len(stored) == 1
    assert stored[0]["response_status"] == 404
    assert stored[0]["endpoint"] == "/no-such-endpoint"
    assert stored[0]["latency"].endswith("ms")
    assert str(stored[0]["_id"])


def test_a_tracked_request_records_the_route_template(api_main):
    with TestClient(api_main.app) as client:
        client.get("/aether-api/v1/ai/user/12345")
        stored = list(api_main.db["hub_metrics"].documents)

    assert stored[0]["endpoint"] == USER_ROUTE_TEMPLATE
