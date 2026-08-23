"""Unit tests for the Users router.

The handler is exercised in isolation: the service layer is replaced through
`app.dependency_overrides`, so these tests cover the HTTP contract only —
status codes, response shape and error mapping.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal.http import user_handlers
from user.entity import User

ROUTE = "/v1/ai/user/{id_external_user}"


class StubUserService:
    def __init__(self, user=None, error=None):
        self.user = user
        self.error = error
        self.calls = []

    def get_mongo_user(self, id_external_user):
        self.calls.append(id_external_user)
        if self.error is not None:
            raise self.error
        return self.user

    def get_user_memories(self, id_user):
        raise NotImplementedError

    def create_user_memory(self, user_memory):
        raise NotImplementedError


def build_client(service=None, db="fake-db"):
    app = FastAPI()
    app.include_router(user_handlers.router)
    app.state.db = db
    if service is not None:
        app.dependency_overrides[user_handlers.get_user_service] = lambda: service
    return TestClient(app)


def test_get_user_returns_profile():
    service = StubUserService(
        user=User(id="65a8b3d6c0f8e1d7f4b2c010", id_external_user=12345, role="analyst", usecase="report_generation")
    )
    response = build_client(service).get(ROUTE.format(id_external_user=12345))

    assert response.status_code == 200
    assert response.json() == {
        "id_external_user": 12345,
        "role": "analyst",
        "usecase": "report_generation",
    }


def test_get_user_forwards_the_path_parameter_as_int():
    service = StubUserService(user=User(id="1", id_external_user=999, role="admin", usecase="audit"))
    build_client(service).get(ROUTE.format(id_external_user=999))

    assert service.calls == [999]


def test_get_user_maps_value_error_to_404():
    service = StubUserService(error=ValueError("User not found."))
    response = build_client(service).get(ROUTE.format(id_external_user=404))

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found."


def test_get_user_maps_unexpected_error_to_500():
    service = StubUserService(error=RuntimeError("mongo exploded"))
    response = build_client(service).get(ROUTE.format(id_external_user=1))

    assert response.status_code == 500
    assert "mongo exploded" in response.json()["detail"]


def test_get_user_returns_503_when_database_is_not_initialized():
    """Exercises the real dependency, which guards on an uninitialized db."""
    response = build_client(service=None, db=None).get(ROUTE.format(id_external_user=1))

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


@pytest.mark.parametrize("bad_id", ["not-an-int", "1.5"])
def test_get_user_rejects_non_integer_identifier(bad_id):
    service = StubUserService(user=None)
    response = build_client(service).get(ROUTE.format(id_external_user=bad_id))

    assert response.status_code == 422
