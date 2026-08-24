"""Unit tests for the Reports router.

This router is not registered in `cmd/api/main.py` yet (see `test_e2e.py`),
so it is mounted on a standalone app here to cover its HTTP contract.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal.http import improvement_plan_handlers

ROUTE = "/aether-api/v1/ai/report"
REQUIRED_PARAMS = {"s3": "reports/input/u1/input.pdf", "id_user": "u1"}


class StubReportService:
    def __init__(self, s3_path=None, error=None):
        """Hold the path to return, or the error to raise."""
        self.s3_path = s3_path
        self.error = error
        self.calls = []

    def input_report(self, *args):
        """Record the positional arguments the handler forwards."""
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.s3_path


class StubUserRepository:
    def __init__(self, db):
        """Hold the database handle the handler passes in."""
        self.db = db


@pytest.fixture
def patched_user_repository(monkeypatch):
    """The handler builds `UserRepository(db)` inline; swap it for a stub."""
    monkeypatch.setattr(improvement_plan_handlers, "UserRepository", StubUserRepository)
    return StubUserRepository


def build_client(service=None, db="fake-db"):
    """Mount the Reports router on a standalone app and return a client."""
    app = FastAPI()
    app.include_router(improvement_plan_handlers.router)
    app.state.db = db
    if service is not None:
        app.dependency_overrides[improvement_plan_handlers.get_session_service] = lambda: service
    return TestClient(app)


def test_input_report_returns_path_and_file_name(patched_user_repository):
    """The file name is derived from the last segment of the S3 path."""
    service = StubReportService(s3_path="s3://reports-bucket/reports/output/u1/202607261430.pdf")
    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 200
    assert response.json() == {
        "s3_path": "s3://reports-bucket/reports/output/u1/202607261430.pdf",
        "file_name": "202607261430.pdf",
    }


def test_input_report_forwards_all_optional_identifiers(patched_user_repository):
    """Every optional query parameter reaches the service, in order."""
    service = StubReportService(s3_path="s3://bucket/out.pdf")
    build_client(service).post(
        ROUTE,
        params={
            **REQUIRED_PARAMS,
            "id_gas_reduction": 9001,
            "id_department": 12,
            "id_external_user_owner": 12345,
            "id_external_user_validator": 12346,
            "id_external_input_report": 777,
        },
    )

    s3, id_user, id_gas_reduction, user_service, *rest = service.calls[0]
    assert s3 == REQUIRED_PARAMS["s3"]
    assert id_user == "u1"
    assert id_gas_reduction == 9001
    assert rest == [12, 12345, 12346, 777]


def test_input_report_defaults_optional_identifiers_to_none(patched_user_repository):
    """Omitted optional parameters arrive as `None`, not as missing arguments."""
    service = StubReportService(s3_path="s3://bucket/out.pdf")
    build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    _, _, id_gas_reduction, _, *rest = service.calls[0]
    assert id_gas_reduction is None
    assert rest == [None, None, None, None]


def test_input_report_maps_value_error_to_400(patched_user_repository):
    """A rejected input is the caller's fault."""
    service = StubReportService(error=ValueError("Invalid s3 path."))
    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid s3 path."


def test_input_report_maps_unexpected_error_to_500(patched_user_repository):
    """Anything unexpected is reported as a server error, detail included."""
    service = StubReportService(error=RuntimeError("analyzer down"))
    response = build_client(service).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 500
    assert "analyzer down" in response.json()["detail"]


def test_input_report_returns_503_when_database_is_not_initialized():
    """Exercises the real dependency, which guards on an uninitialized db."""
    response = build_client(service=None, db=None).post(ROUTE, params=REQUIRED_PARAMS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


@pytest.mark.parametrize("missing", ["s3", "id_user"])
def test_input_report_requires_mandatory_query_params(missing, patched_user_repository):
    """`s3` and `id_user` are both required."""
    params = {key: value for key, value in REQUIRED_PARAMS.items() if key != missing}
    response = build_client(StubReportService(s3_path="s3://bucket/out.pdf")).post(ROUTE, params=params)

    assert response.status_code == 422
