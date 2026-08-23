"""Unit tests for the Sessions router.

The service layer is replaced through `app.dependency_overrides`, so these
tests cover the HTTP contract only: status codes, response shape, error
mapping, and the dependency injection of the Aeko messenger held on
`app.state`.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal.http import session_handlers
from session.entity import Message, Session

SESSIONS_ROUTE = "/v1/ai/sessions/user/{id_user}"
MESSAGES_ROUTE = "/v1/ai/session/{id_session}/messages"
SEND_ROUTE = "/aether-api/v1/ai/user/session/message"

SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)


class StubSessionService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, **call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.result

    def get_user_sessions(self, id_user):
        return self._run(id_user=id_user)

    def get_session_messages(self, id_session):
        return self._run(id_session=id_session)

    def send_message(self, id_session, input, id_user, aeko_messenger, user_repository):
        return self._run(
            id_session=id_session,
            input=input,
            id_user=id_user,
            aeko_messenger=aeko_messenger,
            user_repository=user_repository,
        )

    def _validate_session_and_user_allowance(self, id_session, id_user):
        raise NotImplementedError


class StubUserRepository:
    """Stands in for the concrete repository the handler builds inline."""

    def __init__(self, db):
        self.db = db


def build_client(service=None, db="fake-db", aeko_messenger=None):
    app = FastAPI()
    app.include_router(session_handlers.router)
    app.state.db = db
    app.state._state["aeko_messenger"] = aeko_messenger
    if service is not None:
        app.dependency_overrides[session_handlers.get_session_service] = lambda: service
    return TestClient(app)


def make_message(input="Summarize this session.", output="Here is the summary."):
    return Message(
        input=input,
        output=output,
        submitted_at=SUBMITTED_AT,
        llm="fake-llm",
        input_tokens=10,
        output_tokens=20,
    )


# ---------------------------------------------------------------------------
# GET /v1/ai/sessions/user/{id_user}
# ---------------------------------------------------------------------------
def test_get_user_sessions_returns_sessions():
    service = StubSessionService(
        result=[
            Session(id="65a8b3d6c0f8e1d7f4b2c001", id_user="u1", name="Weekly emissions review", messages=[]),
            Session(id="65a8b3d6c0f8e1d7f4b2c002", id_user="u1", name="Scope 3 questions", messages=[]),
        ]
    )
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 200
    assert response.json() == [
        {"id": "65a8b3d6c0f8e1d7f4b2c001", "name": "Weekly emissions review"},
        {"id": "65a8b3d6c0f8e1d7f4b2c002", "name": "Scope 3 questions"},
    ]
    assert service.calls == [{"id_user": "u1"}]


def test_get_user_sessions_returns_empty_list():
    response = build_client(StubSessionService(result=[])).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 200
    assert response.json() == []


def test_get_user_sessions_maps_value_error_to_404():
    service = StubSessionService(error=ValueError("No sessions found."))
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="ghost"))

    assert response.status_code == 404
    assert response.json()["detail"] == "No sessions found."


def test_get_user_sessions_maps_unexpected_error_to_500():
    service = StubSessionService(error=RuntimeError("boom"))
    response = build_client(service).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_get_user_sessions_returns_503_when_database_is_not_initialized():
    response = build_client(service=None, db=None).get(SESSIONS_ROUTE.format(id_user="u1"))

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


# ---------------------------------------------------------------------------
# GET /v1/ai/session/{id_session}/messages
# ---------------------------------------------------------------------------
def test_get_session_messages_returns_messages():
    service = StubSessionService(result=[make_message()])
    response = build_client(service).get(MESSAGES_ROUTE.format(id_session="s1"))

    assert response.status_code == 200
    assert response.json() == [
        {
            "input_message": "Summarize this session.",
            "output_message": "Here is the summary.",
            "submitted_at": SUBMITTED_AT.isoformat(),
        }
    ]
    assert service.calls == [{"id_session": "s1"}]


def test_get_session_messages_maps_value_error_to_400():
    service = StubSessionService(error=ValueError("Invalid session."))
    response = build_client(service).get(MESSAGES_ROUTE.format(id_session="bad"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid session."


def test_get_session_messages_maps_unexpected_error_to_500():
    service = StubSessionService(error=RuntimeError("boom"))
    response = build_client(service).get(MESSAGES_ROUTE.format(id_session="s1"))

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /aether-api/v1/ai/user/session/message
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_user_repository(monkeypatch):
    """The handler builds `UserRepository(db)` inline; swap it for a stub."""
    monkeypatch.setattr(session_handlers, "UserRepository", StubUserRepository)
    return StubUserRepository


def test_send_message_returns_the_exchange(fake_sdk, patched_user_repository):
    service = StubSessionService(result=make_message())
    messenger = fake_sdk.AekoMessenger()
    client = build_client(service, aeko_messenger=messenger)

    response = client.post(
        SEND_ROUTE,
        json={"id_session": "s1", "input": "Summarize this session.", "id_user": "u1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "input_message": "Summarize this session.",
        "output_message": "Here is the summary.",
        "submitted_at": SUBMITTED_AT.isoformat(),
    }


def test_send_message_injects_the_messenger_from_app_state(fake_sdk, patched_user_repository):
    service = StubSessionService(result=make_message())
    messenger = fake_sdk.AekoMessenger()
    client = build_client(service, aeko_messenger=messenger)

    client.post(SEND_ROUTE, json={"id_session": "", "input": "hi", "id_user": "u1"})

    call = service.calls[0]
    assert call["aeko_messenger"] is messenger
    assert call["id_session"] == ""
    assert call["id_user"] == "u1"
    assert isinstance(call["user_repository"], StubUserRepository)


def test_send_message_defaults_missing_body_fields(fake_sdk, patched_user_repository):
    service = StubSessionService(result=make_message())
    client = build_client(service, aeko_messenger=fake_sdk.AekoMessenger())

    client.post(SEND_ROUTE, json={})

    assert service.calls[0]["input"] == ""
    assert service.calls[0]["id_user"] == ""
    assert service.calls[0]["id_session"] is None


def test_send_message_returns_500_when_messenger_is_not_initialized():
    service = StubSessionService(result=make_message())
    client = build_client(service, aeko_messenger=None)

    response = client.post(SEND_ROUTE, json={"id_session": "s1", "input": "hi", "id_user": "u1"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Aeko messenger is not initialized"


def test_send_message_maps_value_error_to_400(fake_sdk, patched_user_repository):
    service = StubSessionService(error=ValueError("Session limit reached."))
    client = build_client(service, aeko_messenger=fake_sdk.AekoMessenger())

    response = client.post(SEND_ROUTE, json={"id_session": "s1", "input": "hi", "id_user": "u1"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Session limit reached."


def test_send_message_maps_unexpected_error_to_500(fake_sdk, patched_user_repository):
    service = StubSessionService(error=RuntimeError("boom"))
    client = build_client(service, aeko_messenger=fake_sdk.AekoMessenger())

    response = client.post(SEND_ROUTE, json={"id_session": "s1", "input": "hi", "id_user": "u1"})

    assert response.status_code == 500
    assert "boom" in response.json()["detail"]
