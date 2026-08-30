"""Application wiring tests.

They cover what the routers and the dependency functions produce when nothing
is overridden: the routes the application actually exposes, the lifespan
failure path, and the real handler + service + concrete repository stack
running against a stubbed Mongo.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from internal.http import improvement_plan_handlers, session_handlers, user_handlers
from session.database.repository import Repository as SessionRepository
from session.service import Service as SessionService
from tests.mongo_doubles import StubCollection, StubDatabase
from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

REPORT_ROUTE = "/aether-api/v1/ai/report"
SEND_MESSAGE_ROUTE = "/aether-api/v1/ai/user/session/message"
ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"

USER_DOCUMENT = {
    "_id": ID_USER,
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
}

SESSION_DOCUMENT = {
    "_id": ID_SESSION,
    "id_user": ID_USER,
    "name": "Weekly emissions review",
}


def request_with(db):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
def test_report_route_is_registered_on_the_application(api_main):
    paths = api_main.app.openapi()["paths"]

    assert "post" in paths.get(REPORT_ROUTE, {})


@pytest.mark.parametrize(
    "path",
    [
        "/v1/ai/user/{id_external_user}",
        "/v1/ai/sessions/user/{id_user}",
        "/v1/ai/session/{id_session}/messages",
        SEND_MESSAGE_ROUTE,
        REPORT_ROUTE,
    ],
)
def test_every_documented_route_is_registered(api_main, path):
    assert path in api_main.app.openapi()["paths"]


def test_report_route_is_reachable(api_main):
    with TestClient(api_main.app) as client:
        response = client.post(REPORT_ROUTE, params={"s3": "reports/input/u1/input.pdf", "id_user": "u1"})

    assert response.status_code != 404


def test_report_route_still_validates_its_query_parameters(api_main):
    with TestClient(api_main.app) as client:
        response = client.post(REPORT_ROUTE, params={"id_user": "u1"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
def test_lifespan_fails_when_the_database_does_not_answer(api_main, monkeypatch):
    class UnreachableDatabase:
        def command(self, name):
            raise OSError("no route to host")

    class UnreachableClient:
        def __init__(self, uri=None, *args, **kwargs):
            self.database = UnreachableDatabase()

        def __getitem__(self, name):
            return self.database

        def close(self):
            pass

    monkeypatch.setattr(api_main, "MongoClient", UnreachableClient)

    with pytest.raises(RuntimeError, match="Failed to connect to MongoDB"):
        with TestClient(api_main.app):
            pass


# ---------------------------------------------------------------------------
# Dependency functions build the concrete stack
# ---------------------------------------------------------------------------
def test_user_dependency_builds_a_service_backed_by_the_concrete_repository():
    service = user_handlers.get_user_service(request_with(StubDatabase()))

    assert isinstance(service, UserService)
    assert isinstance(service.repository, UserRepository)


def test_session_dependency_builds_a_service_backed_by_the_concrete_repository():
    service = session_handlers.get_session_service(request_with(StubDatabase()))

    assert isinstance(service, SessionService)
    assert isinstance(service.repository, SessionRepository)


def test_report_dependency_builds_a_service_backed_by_the_concrete_repository():
    service = improvement_plan_handlers.get_session_service(request_with(StubDatabase()))

    assert isinstance(service, SessionService)
    assert isinstance(service.repository, SessionRepository)


@pytest.mark.parametrize(
    "dependency",
    [
        user_handlers.get_user_service,
        session_handlers.get_session_service,
        improvement_plan_handlers.get_session_service,
    ],
)
def test_dependencies_reject_an_uninitialized_database(dependency):
    with pytest.raises(HTTPException) as exc_info:
        dependency(request_with(None))

    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Real stack: handler + service + concrete repository over a stubbed Mongo
# ---------------------------------------------------------------------------
def build_client(router, database, api_main=None):
    """`api_main` supplies the very adapters the real lifespan publishes."""
    app = FastAPI()
    app.include_router(router)
    app.state.db = database
    if api_main is not None:
        app.state._state["aeko_messenger_factory"] = api_main.build_messenger
        app.state._state["aeko_session_factory"] = api_main.build_session
    return TestClient(app)


def test_get_user_runs_through_the_concrete_repository():
    database = StubDatabase(user=StubCollection(find_one_result=USER_DOCUMENT))

    response = build_client(user_handlers.router, database).get("/v1/ai/user/12345")

    assert response.status_code == 200
    assert response.json() == {"id_external_user": 12345, "role": "analyst", "usecase": "report_generation"}


def test_get_user_returns_404_when_the_document_does_not_exist():
    database = StubDatabase(user=StubCollection(find_one_result=None))

    response = build_client(user_handlers.router, database).get("/v1/ai/user/12345")

    assert response.status_code == 404


def test_get_user_sessions_runs_through_the_concrete_repository():
    database = StubDatabase(session=StubCollection(find_result=[SESSION_DOCUMENT]))

    response = build_client(session_handlers.router, database).get(f"/v1/ai/sessions/user/{ID_USER}")

    assert response.status_code == 200
    assert response.json() == [{"id": ID_SESSION, "name": "Weekly emissions review"}]


def test_get_session_messages_runs_through_the_concrete_repository():
    document = {"messages": [{"input": "hi", "output": "ho", "submitted_at": "2026-07-26T14:30:00"}]}
    database = StubDatabase(session=StubCollection(find_one_result=document))

    response = build_client(session_handlers.router, database).get(f"/v1/ai/session/{ID_SESSION}/messages")

    assert response.status_code == 200
    assert response.json() == [
        {"input_message": "hi", "output_message": "ho", "submitted_at": "2026-07-26T14:30:00"}
    ]


MESSAGES_DOCUMENT = {
    "messages": [
        {
            "input": "Summarize this session.",
            "output": "Here is the summary.",
            "submitted_at": "2026-07-26T14:30:00",
        }
    ]
}


def session_reads():
    """What the session collection answers, in the order the service asks."""
    return [{"messages_count": 0}, SESSION_DOCUMENT, SESSION_DOCUMENT, MESSAGES_DOCUMENT]


def test_send_message_runs_through_the_concrete_repositories(api_main, configured_sdk):
    session_collection = StubCollection(find_one_results=session_reads())
    database = StubDatabase(
        session=session_collection,
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "What is scope 3?", "id_user": ID_USER},
    )

    assert response.status_code == 200
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert len(session_collection.call_args("update_one")) == 1


def test_send_message_hands_the_real_dtos_to_the_sdk(api_main, configured_sdk):
    database = StubDatabase(
        session=StubCollection(find_one_results=session_reads()),
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "What is scope 3?", "id_user": ID_USER},
    )

    messenger = configured_sdk.AekoMessenger.instances[-1]
    _, session = messenger.sent[-1]
    assert isinstance(messenger.user, configured_sdk.AekoUser)
    assert isinstance(session, configured_sdk.AekoSession)
    assert session.id == ID_SESSION
    assert [turn.input for turn in session.messages][0] == "Summarize this session."


def test_send_message_returns_400_when_the_user_does_not_own_the_session(api_main, configured_sdk):
    session_collection = StubCollection(find_one_results=session_reads())
    database = StubDatabase(
        session=session_collection,
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "hi", "id_user": "someone-else"},
    )

    assert response.status_code == 400


def test_send_message_fails_when_the_sdk_was_never_configured(api_main):
    """No `Aeko.config()` means no run: a deployment problem, not a user one."""
    database = StubDatabase(
        session=StubCollection(find_one_results=session_reads()),
        user=StubCollection(find_one_result=USER_DOCUMENT),
        user_memory=StubCollection(find_result=[]),
    )

    response = build_client(session_handlers.router, database, api_main=api_main).post(
        SEND_MESSAGE_ROUTE,
        json={"id_session": ID_SESSION, "input": "hi", "id_user": ID_USER},
    )

    assert response.status_code == 500
    assert "not configured" in response.json()["detail"]
