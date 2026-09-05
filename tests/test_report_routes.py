"""Unit tests for the Reports router.

The route is mounted on a standalone app here to cover its HTTP contract on
its own; `test_app_wiring.py` and `test_e2e.py` cover it inside the real
application.

What it takes changed with the flow it serves: no S3 reference, no PDF. The
inventory is resolved by the ms-inventory microservice from its external id,
and what comes back is the improvement plan that was persisted.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import MalformedPlanError
from internal.http import improvement_plan_handlers

ROUTE = "/aether-api/v1/ai/report"
REQUIRED_PARAMS = {"id_external_inventory": 502, "id_external_unit": 77, "id_user": "u1"}

CREATED_PLAN = ImprovementPlan(
    id="65a8b3d6c0f8e1d7f4b2c020",
    id_external_inventory=502,
    id_external_unit=77,
    defined_problem="high scope 1 emissions",
    method="replace the boiler fleet",
    reasoning="direct combustion dominates the inventory",
)


class StubReportService:
    def __init__(self, plan=CREATED_PLAN, error=None):
        self.plan = plan
        self.error = error
        self.calls = []

    def input_inventory(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.plan


class StubUserRepository:
    def __init__(self, db):
        self.db = db


class StubUserService:
    def __init__(self, repository):
        self.repository = repository


@pytest.fixture
def patched_user_service(monkeypatch):
    """The handler builds the user service inline; swap both halves out."""
    monkeypatch.setattr(improvement_plan_handlers, "UserRepository", StubUserRepository)
    monkeypatch.setattr(improvement_plan_handlers, "UserService", StubUserService)
    return StubUserService


def build_analyzer_factory():
    return lambda: "analyzer"


def build_client(service=None, db="fake-db", analyzer_factory=build_analyzer_factory()):
    app = FastAPI()
    app.include_router(improvement_plan_handlers.router)
    app.state.db = db
    if analyzer_factory is not None:
        app.state.aeko_inventory_analyzer_factory = analyzer_factory
    if service is not None:
        app.dependency_overrides[improvement_plan_handlers.get_improvement_plan_service] = lambda: service
    return TestClient(app)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_input_report_returns_the_created_plan(patched_user_service):
    service = StubReportService()

    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 200
    assert response.json() == {
        "id": "65a8b3d6c0f8e1d7f4b2c020",
        "id_external_inventory": 502,
        "id_external_unit": 77,
        "defined_problem": "high scope 1 emissions",
        "method": "replace the boiler fleet",
        "reasoning": "direct combustion dominates the inventory",
    }


def test_input_report_forwards_what_the_flow_needs(patched_user_service):
    service = StubReportService()

    build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    id_external_inventory, id_external_unit, id_user, user_service, analyzer_factory = service.calls[0]
    assert (id_external_inventory, id_external_unit, id_user) == (502, 77, "u1")
    assert isinstance(user_service, StubUserService)
    assert callable(analyzer_factory)


# ---------------------------------------------------------------------------
# What the caller is told when it goes wrong
# ---------------------------------------------------------------------------
def test_input_report_maps_value_error_to_400(patched_user_service):
    service = StubReportService(error=ValueError("id_external_inventory is required."))

    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 400
    assert response.json()["detail"] == "id_external_inventory is required."


def test_input_report_maps_a_plan_that_never_took_shape_to_502(patched_user_service):
    """The run was made and is recorded; what it produced is simply not a
    report, and the answer to that is to ask again rather than to page anyone."""
    service = StubReportService(
        error=MalformedPlanError("The analysis produced no plan in the shape a report is stored in.")
    )

    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The analysis produced no plan in the shape a report is stored in."
    )


def test_input_report_maps_unexpected_error_to_500(patched_user_service):
    service = StubReportService(error=RuntimeError("analyzer down"))

    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 500
    assert "analyzer down" in response.json()["detail"]


def test_input_report_returns_503_when_database_is_not_initialized():
    response = build_client(service=None, db=None).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_input_report_returns_500_when_the_sdk_was_never_configured(patched_user_service):
    """The analyzer factory is published by the lifespan; without it there is
    no SDK to run the report through."""
    response = build_client(StubReportService(), analyzer_factory=None).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 500
    assert response.json()["detail"] == "Aeko SDK is not initialized"


@pytest.mark.parametrize("missing", list(REQUIRED_PARAMS))
def test_input_report_requires_every_parameter(missing, patched_user_service):
    params = {key: value for key, value in REQUIRED_PARAMS.items() if key != missing}

    response = build_client(StubReportService()).post(ROUTE, params=params)

    assert response.status_code == 422


@pytest.mark.parametrize("param", ["id_external_inventory", "id_external_unit"])
def test_the_external_identifiers_must_be_numbers(param, patched_user_service):
    """Both reference Postgres, and the SDK takes the inventory's as an int."""
    params = {**REQUIRED_PARAMS, param: "not-a-number"}

    response = build_client(StubReportService()).post(ROUTE, params=params)

    assert response.status_code == 422
