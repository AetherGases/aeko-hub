"""End-to-end tests against the real application.

The app is started through its real lifespan, with only two seams faked:

* `aeko` — an external package, replaced suite-wide by `tests/fake_aeko.py`
* `pymongo.MongoClient` — replaced by an in-memory double

Everything else is production code: the real routers, the real dependency
functions and the real service classes. The database seam is swapped for
in-memory repositories because the concrete repositories still reference
query helpers that do not exist yet (see the xfail test at the bottom).
"""

import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from internal.http import session_handlers, user_handlers
from session.entity import Message, Session
from session.service import Service as SessionService
from user.entity import User
from user.service import Service as UserService

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

SDK_IMPORT = re.compile(r"^\s*(?:from\s+aeko(?:\.\w+)*\s+import|import\s+aeko\b)", re.MULTILINE)


class InMemoryUserRepository:
    def __init__(self, users=None):
        """Seed the repository with users, and no memories."""
        self.users = users or {}
        self.memories = []

    def get_user(self, id_external_user):
        """Look a user up by external id.

        Raises:
            ValueError: nobody carries that identifier.
        """
        user = self.users.get(id_external_user)
        if user is None:
            raise ValueError(f"User with id_external_user {id_external_user} not found.")
        return user

    def get_user_by_id(self, id_user):
        """Look a user up by internal id, or `None` when there is none."""
        return next((user for user in self.users.values() if user.id == id_user), None)

    def get_user_memories(self, id_user):
        """Return the memories recorded for one user."""
        return [memory for memory in self.memories if memory.id_user == id_user]

    def create_user_memory(self, user_memory):
        """Record one memory."""
        self.memories.append(user_memory)


class InMemorySessionRepository:
    def __init__(self, sessions=None, messages=None):
        """Seed the repository with sessions and their messages."""
        self.sessions = sessions or {}
        self.messages = messages or {}
        self.created_names = {}

    def get_user_sessions(self, id_user):
        """List a user's sessions.

        Raises:
            ValueError: the user owns none.
        """
        sessions = [s for s in self.sessions.values() if s.id_user == id_user]
        if not sessions:
            raise ValueError(f"No sessions found for user with id_user {id_user}.")
        return sessions

    def get_session(self, id_session):
        """Fetch one session.

        Raises:
            ValueError: no session carries that identifier.
        """
        session = self.sessions.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session

    def get_session_messages(self, id_session):
        """Return a session's history, empty when it has none."""
        return self.messages.get(id_session, [])

    def get_session_messages_count(self, id_session):
        """Count a session's messages."""
        return len(self.messages.get(id_session, []))

    def create_session(self, id_user, user_repository):
        """Open a session named after its position, and return its id."""
        id_session = f"session-{len(self.sessions) + 1}"
        self.sessions[id_session] = Session(id=id_session, id_user=id_user, name="new session", messages=[])
        return id_session

    def save_message(self, id_session, message):
        """Append one exchange to a session's history."""
        self.messages.setdefault(id_session, []).append(message)

    def update_name(self, id_session, name):
        """Record the name given to a session."""
        self.created_names[id_session] = name


@pytest.fixture
def seeded_repositories():
    """One user, one session of theirs, and one message in it."""
    user = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")
    session = Session(id="s1", id_user="u1", name="Weekly emissions review", messages=[])
    message = Message(
        input="Summarize this session.",
        output="Here is the summary.",
        submitted_at=SUBMITTED_AT,
        llm="fake-llm",
        input_tokens=10,
        output_tokens=20,
    )
    return (
        InMemoryUserRepository(users={12345: user}),
        InMemorySessionRepository(sessions={"s1": session}, messages={"s1": [message]}),
    )


@pytest.fixture
def live_app(api_main, seeded_repositories):
    """The real app, started through its real lifespan."""
    user_repository, session_repository = seeded_repositories
    app = api_main.app
    app.dependency_overrides[user_handlers.get_user_service] = lambda: UserService(user_repository)
    app.dependency_overrides[session_handlers.get_session_service] = lambda: SessionService(session_repository)
    with TestClient(app) as client:
        yield client, api_main, user_repository, session_repository
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Application wiring
# ---------------------------------------------------------------------------
def test_lifespan_configures_the_sdk_from_environment(live_app, fake_sdk):
    """`Aeko.config()` runs exactly once, with the values the app read from env."""
    assert fake_sdk.Aeko.config_calls == [
        {
            "api_key": "test-gemini-key",
            "fast_model": "fast-model",
            "slow_model": "slow-model",
            "max_tokens": 512,
            "report_max_tokens": 4096,
        }
    ]
    assert fake_sdk.Aeko.is_configured() is True


def test_lifespan_registers_tools_under_real_agent_names(live_app, fake_sdk):
    """`set_tools` is a classmethod keyed by the SDK's own routing names."""
    tools = fake_sdk.AekoMessenger.tools

    assert set(tools) == {
        "FAQ",
        "Análista de inventários",
        "Analista de Poluentes",
        "Analista de Gases Verdes",
        "Coordenador de Melhoria Contínua",
    }
    assert set(tools).issubset(set(fake_sdk.AGENT_NAMES))


def test_lifespan_rejects_tools_bound_to_an_unknown_agent(api_main):
    """A typo in an agent name has to fail at startup, not on the first request."""
    api_main.AEKO_TOOLS = {"Analista de Poluente": []}

    with pytest.raises(RuntimeError, match="Unknown Aeko agent names"):
        api_main.configure_aeko()


def test_lifespan_publishes_sdk_factories_on_app_state(live_app, fake_sdk):
    """Factories, not instances: both entry points carry per-session state."""
    _, api_main, _, _ = live_app
    state = api_main.app.state._state

    assert state["aeko_messenger_factory"] is fake_sdk.AekoMessenger
    assert state["aeko_inventory_analyzer_factory"] is fake_sdk.AekoInventoryAnalyzer
    assert state["aeko_tool"] is fake_sdk.AekoTool


def test_build_gas_reduction_context_renders_plain_text(live_app):
    """`set_context()` takes free-form text, so the external payload is flattened."""
    _, api_main, _, _ = live_app
    build = api_main.app.state._state["build_gas_reduction_context"]

    context = build({"total_tco2e": 12400, "scope": 1})

    assert isinstance(context, str)
    assert context == "total_tco2e: 12400\nscope: 1"


def test_lifespan_pings_the_database_and_closes_the_client(api_main):
    """The lifespan proves the connection works and releases it on shutdown."""
    with TestClient(api_main.app):
        pass
    client = api_main.MongoClient.instances[-1]

    assert client.database.commands == ["ping"]
    assert client.closed is True


def test_only_the_entry_point_imports_the_sdk():
    """Guards the refactor: `aeko` must be imported in one place only."""
    ignored = {"tests", ".git", ".venv", "venv", "env", "site-packages", "__pycache__"}
    importers = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in REPO_ROOT.rglob("*.py")
        if ignored.isdisjoint(path.parts)
        and SDK_IMPORT.search(path.read_text(encoding="utf-8"))
    )

    assert importers == ["cmd/api/main.py"]


# ---------------------------------------------------------------------------
# User journey across the registered routes
# ---------------------------------------------------------------------------
def test_journey_user_then_sessions_then_messages(live_app):
    """The three read routes chain: a user, their sessions, one session's messages."""
    client, _, _, _ = live_app

    user = client.get("/v1/ai/user/12345")
    assert user.status_code == 200
    assert user.json()["role"] == "analyst"

    sessions = client.get("/v1/ai/sessions/user/u1")
    assert sessions.status_code == 200
    assert sessions.json() == [{"id": "s1", "name": "Weekly emissions review"}]

    id_session = sessions.json()[0]["id"]
    messages = client.get(f"/v1/ai/session/{id_session}/messages")
    assert messages.status_code == 200
    assert messages.json() == [
        {
            "input_message": "Summarize this session.",
            "output_message": "Here is the summary.",
            "submitted_at": SUBMITTED_AT.isoformat(),
        }
    ]


def test_journey_unknown_user_is_404(live_app):
    """Both read routes report a missing user rather than failing."""
    client, _, _, _ = live_app

    assert client.get("/v1/ai/user/99999").status_code == 404
    assert client.get("/v1/ai/sessions/user/ghost").status_code == 404


# ---------------------------------------------------------------------------
# The conversational flow against the SDK
# ---------------------------------------------------------------------------
def test_send_message_completes_the_round_trip(live_app, fake_sdk):
    """A turn reaches the SDK, comes back answered, and is persisted."""
    client, _, _, session_repository = live_app

    response = client.post(
        "/aether-api/v1/ai/user/session/message",
        json={"id_session": "s1", "input": "What is scope 3?", "id_user": "u1"},
    )

    assert response.status_code == 200
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert len(session_repository.get_session_messages("s1")) == 2
    assert fake_sdk.AekoMessenger.instances[-1].sent_inputs == ["What is scope 3?"]


def test_send_message_prepares_the_session_with_rehydrated_history(live_app, fake_sdk):
    """History lives in our database and is handed back on every request."""
    client, _, _, _ = live_app

    client.post(
        "/aether-api/v1/ai/user/session/message",
        json={"id_session": "s1", "input": "What is scope 3?", "id_user": "u1"},
    )

    prepared = fake_sdk.AekoMessenger.instances[-1].prepared_with
    assert prepared["session_id"] == "s1"
    assert prepared["user_info"] == "role: analyst\nusecase: report_generation"
    assert prepared["history"] == [
        {"role": "user", "content": "Summarize this session."},
        {"role": "assistant", "content": "Here is the summary."},
    ]


def test_send_message_builds_a_fresh_messenger_per_request(live_app, fake_sdk):
    """A shared instance would leak one session's memory into the next."""
    client, _, _, _ = live_app
    payload = {"id_session": "s1", "input": "What is scope 3?", "id_user": "u1"}

    client.post("/aether-api/v1/ai/user/session/message", json=payload)
    client.post("/aether-api/v1/ai/user/session/message", json=payload)

    assert len(fake_sdk.AekoMessenger.instances) == 2
    assert fake_sdk.AekoMessenger.instances[0] is not fake_sdk.AekoMessenger.instances[1]


def test_send_message_names_a_brand_new_session_after_its_first_input(live_app):
    """An empty `id_session` opens a session named after the opening message."""
    client, _, _, session_repository = live_app

    response = client.post(
        "/aether-api/v1/ai/user/session/message",
        json={"id_session": "", "input": "How do I cut boiler emissions?", "id_user": "u1"},
    )

    assert response.status_code == 200
    assert session_repository.created_names == {"session-2": "How do I cut boiler emissions?"}


def test_send_message_returns_502_when_the_guardrail_rejects_every_draft(live_app, fake_sdk):
    """An empty answer is a successful run with nothing to persist, not an error."""
    client, _, _, session_repository = live_app
    fake_sdk.AekoMessenger.reject_next = True

    response = client.post(
        "/aether-api/v1/ai/user/session/message",
        json={"id_session": "s1", "input": "What is scope 3?", "id_user": "u1"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "The output guardrail rejected every draft."
    assert len(session_repository.get_session_messages("s1")) == 1


# ---------------------------------------------------------------------------
# Known gaps — these document intended behaviour that does not work yet.
# ---------------------------------------------------------------------------
@pytest.mark.xfail(reason="improvement_plan_router is imported but never registered on the app", strict=True)
def test_report_route_is_registered(live_app):
    """The Reports router should be mounted on the app."""
    client, _, _, _ = live_app

    response = client.post(
        "/aether-api/v1/ai/report",
        params={"s3": "reports/input/u1/input.pdf", "id_user": "u1"},
    )

    assert response.status_code != 404
