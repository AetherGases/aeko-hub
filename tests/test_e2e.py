"""End-to-end tests against the real application.

The app is started through its real lifespan, with only two seams faked:

* `aeko` — an external package, replaced suite-wide by `tests/fake_aeko.py`
* `pymongo.MongoClient` — replaced by an in-memory double

Everything else is production code: the real routers, the real dependency
functions and the real service classes. The database seam is swapped for
in-memory repositories so a journey can be followed without a Mongo server.
"""

import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from improvement_plan.entity import ImprovementPlan
from improvement_plan.service import Service as ImprovementPlanService
from internal.http import improvement_plan_handlers, session_handlers, user_handlers
from session.entity import Message, Session
from session.service import Service as SessionService
from user.entity import User, UserMemory
from user.service import Service as UserService

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

# The report journey: one inventory of one unit, resolved as Markdown by the
# ms-inventory microservice.
ID_INVENTORY = 502
ID_UNIT = 77
INVENTORY_MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"

# The five agents the gateway registers tools for, spelled as the SDK's
# routing keys.
TOOLED_AGENTS = {
    "FAQ",
    "Análista de inventários",
    "Analista de Poluentes",
    "Analista de Gases Verdes",
    "Coordenador de Melhoria Contínua",
}


class InMemoryUserRepository:
    def __init__(self, users=None, memories=None):
        self.users = users or {}
        self.memories = list(memories or [])

    def get_user(self, id_external_user):
        user = self.users.get(id_external_user)
        if user is None:
            raise ValueError(f"User with id_external_user {id_external_user} not found.")
        return user

    def get_user_by_id(self, id_user):
        return next((user for user in self.users.values() if user.id == id_user), None)

    def get_user_memories(self, id_user):
        return [memory for memory in self.memories if memory.id_user == id_user]

    def create_user_memory(self, user_memory):
        self.memories.append(user_memory)


class InMemorySessionRepository:
    def __init__(self, sessions=None, messages=None):
        self.sessions = sessions or {}
        self.messages = messages or {}
        self.created_names = {}

    def get_user_sessions(self, id_user):
        sessions = [s for s in self.sessions.values() if s.id_user == id_user]
        if not sessions:
            raise ValueError(f"No sessions found for user with id_user {id_user}.")
        return sessions

    def get_session(self, id_session):
        session = self.sessions.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session

    def get_session_messages(self, id_session):
        return self.messages.get(id_session, [])

    def get_session_messages_count(self, id_session):
        return len(self.messages.get(id_session, []))

    def create_session(self, id_user, user_repository):
        id_session = f"session-{len(self.sessions) + 1}"
        self.sessions[id_session] = Session(id=id_session, id_user=id_user, name="", messages=[])
        return id_session

    def save_message(self, id_session, message):
        self.messages.setdefault(id_session, []).append(message)

    def update_name(self, id_session, name):
        self.created_names[id_session] = name
        self.sessions[id_session].name = name


class InMemoryImprovementPlanRepository:
    def __init__(self, plans=None):
        self.plans = list(plans or [])

    def get_by_id_external_inventory(self, id_external_inventory):
        plan = next(
            (p for p in self.plans if p.id_external_inventory == id_external_inventory), None
        )
        if plan is None:
            raise ValueError(f"Improvement plan with id_external_inventory {id_external_inventory} not found.")
        return plan

    def get_last_by_id_external_unit(self, id_external_unit, limit):
        of_the_unit = [p for p in self.plans if p.id_external_unit == id_external_unit]
        return sorted(of_the_unit, key=lambda plan: plan.updated_at, reverse=True)[:limit]

    def create(self, improvement_plan):
        improvement_plan.id = f"plan-{len(self.plans) + 1}"
        improvement_plan.updated_at = improvement_plan.updated_at or datetime.utcnow()
        self.plans.append(improvement_plan)
        return improvement_plan


class InMemoryInventoryRepository:
    """Stands in for the ms-inventory microservice the gateway calls."""

    def __init__(self, markdown=INVENTORY_MARKDOWN):
        self.markdown = markdown
        self.resolved = []

    def get_inventory_markdown(self, id_external_inventory):
        self.resolved.append(id_external_inventory)
        return self.markdown


@pytest.fixture
def seeded_repositories():
    user = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")
    session = Session(id="s1", id_user="u1", name="Weekly emissions review", messages=[])
    message = Message(
        input="Summarize this session.",
        output="Here is the summary.",
        submitted_at=SUBMITTED_AT,
    )
    memories = [
        UserMemory(
            id="m1",
            id_user="u1",
            field="preferred_language",
            description="Answers in Portuguese",
            expires_at=datetime.utcnow() + timedelta(days=1),
        ),
        UserMemory(
            id="m2",
            id_user="u1",
            field="stale",
            description="Should never reach a prompt",
            expires_at=datetime.utcnow() - timedelta(days=1),
        ),
    ]
    return (
        InMemoryUserRepository(users={12345: user}, memories=memories),
        InMemorySessionRepository(sessions={"s1": session}, messages={"s1": [message]}),
    )


@pytest.fixture
def live_app(api_main, seeded_repositories, monkeypatch):
    """The real app, started through its real lifespan."""
    user_repository, session_repository = seeded_repositories
    app = api_main.app
    app.dependency_overrides[user_handlers.get_user_service] = lambda: UserService(user_repository)
    app.dependency_overrides[session_handlers.get_session_service] = lambda: SessionService(session_repository)
    # The send-message handler builds its user repository inline, so it is not
    # reachable through `dependency_overrides`.
    monkeypatch.setattr(session_handlers, "UserRepository", lambda db: user_repository)
    with TestClient(app) as client:
        yield client, api_main, user_repository, session_repository
    app.dependency_overrides.clear()


@pytest.fixture
def report_app(live_app, monkeypatch):
    """The running app with the report flow's two repositories in memory.

    Everything between the route and them is production code: the handler, the
    service that used to live in `inventory_analysis`, and the analyzer the
    lifespan publishes (the fake SDK's).
    """
    client, api_main, user_repository, _ = live_app
    plan_repository = InMemoryImprovementPlanRepository()
    inventory_repository = InMemoryInventoryRepository()

    client.app.dependency_overrides[improvement_plan_handlers.get_improvement_plan_service] = (
        lambda: ImprovementPlanService(plan_repository, inventory_repository)
    )
    # The handler builds its user repository inline, so it is not reachable
    # through `dependency_overrides` either.
    monkeypatch.setattr(improvement_plan_handlers, "UserRepository", lambda db: user_repository)

    return client, api_main, plan_repository, inventory_repository


def request_report(client, id_external_inventory=ID_INVENTORY, id_external_unit=ID_UNIT, id_user="u1"):
    return client.post(
        "/aether-api/v1/ai/report",
        params={
            "id_external_inventory": id_external_inventory,
            "id_external_unit": id_external_unit,
            "id_user": id_user,
        },
    )


# ---------------------------------------------------------------------------
# Application wiring
# ---------------------------------------------------------------------------
def test_lifespan_configures_the_sdk_from_environment(live_app, fake_sdk):
    assert fake_sdk.RUNTIME.config_calls == [
        {
            "api_key": "test-gemini-key",
            "fast_model": "fast-model",
            "slow_model": "slow-model",
            "max_tokens": 512,
            "report_max_tokens": 4096,
        }
    ]
    assert fake_sdk.Aeko.is_configured() is True


def test_lifespan_registers_the_tools_under_the_sdk_agent_names(live_app, fake_sdk):
    assert set(fake_sdk.RUNTIME.tools) == TOOLED_AGENTS


def test_registered_tool_keys_are_all_known_agents(live_app, fake_sdk):
    assert TOOLED_AGENTS.issubset(set(fake_sdk.AGENT_NAMES))


def test_lifespan_registers_every_agent_in_a_single_call(live_app, fake_sdk):
    """`set_tools()` replaces the whole registry, so one call must carry them all."""
    assert len(fake_sdk.RUNTIME.set_tools_calls) == 1


# Every agent that gets the general web research tools of the Tavily MCP
# integration also gets one integration nobody else does — "Analista de Gases
# Verdes" the ChromaDB vector search, "Analista de Poluentes" the Climatiq
# calculator, "Coordenador de Melhoria Contínua" the ROI and payback tools —
# so each of them has a test of its own below, asserting its whole tool set.


# The one tool nobody is singled out for: arithmetic is every agent's problem,
# and a language model predicting digits is every agent's failure mode (see
# `cmd/api/tools/calculator.py`).
CALCULATOR_TOOL_NAME = "calculator"


def test_faq_gets_the_site_map_and_user_memory_tools(live_app, fake_sdk):
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["FAQ"]}
    assert tool_names == {
        "tavily_map",
        "tavily_search",
        "tavily_research",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    }


ROI_TOOL_NAMES = {"calculate_roi", "calculate_payback"}


def test_continuous_improvement_coordinator_also_gets_the_roi_tools(live_app, fake_sdk):
    """Only this agent weighs an investment: it is the one that proposes them."""
    tool_names = {
        tool.name for tool in fake_sdk.RUNTIME.tools["Coordenador de Melhoria Contínua"]
    }
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    } | ROI_TOOL_NAMES


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Coordenador de Melhoria Contínua"}),
)
def test_no_other_agent_can_reach_the_roi_tools(live_app, fake_sdk, agent):
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert tool_names.isdisjoint(ROI_TOOL_NAMES)


def test_green_gas_analyst_also_gets_the_chroma_vector_search(live_app, fake_sdk):
    """Only this agent reads the `gases-info` collection (see the Feature/40 card)."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Analista de Gases Verdes"]}
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        "query_gases_info",
        CALCULATOR_TOOL_NAME,
    }


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Analista de Gases Verdes"}),
)
def test_no_other_agent_can_reach_the_gases_info_collection(live_app, fake_sdk, agent):
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert "query_gases_info" not in tool_names


CLIMATIQ_TOOL_NAMES = {"climatiq_search", "climatiq_estimate"}


def test_pollutant_analyst_also_gets_the_climatiq_calculator(live_app, fake_sdk):
    """Only this agent calculates emissions through Climatiq (see the Feature/45 card)."""
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Analista de Poluentes"]}
    assert tool_names == {
        "tavily_search",
        "tavily_research",
        "find_improvement_plan",
        "find_user_memory",
        CALCULATOR_TOOL_NAME,
    } | CLIMATIQ_TOOL_NAMES


@pytest.mark.parametrize(
    "agent",
    sorted(TOOLED_AGENTS - {"Analista de Poluentes"}),
)
def test_no_other_agent_can_reach_climatiq(live_app, fake_sdk, agent):
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}
    assert tool_names.isdisjoint(CLIMATIQ_TOOL_NAMES)


def test_inventory_analyst_gets_no_tavily_tools_but_gets_mongo_tools(live_app, fake_sdk):
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools["Análista de inventários"]}
    assert tool_names == {"find_improvement_plan", "find_user_memory", CALCULATOR_TOOL_NAME}


# ---------------------------------------------------------------------------
# The calculator: the one tool every agent gets
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("agent", sorted(TOOLED_AGENTS))
def test_every_agent_gets_the_calculator(live_app, fake_sdk, agent):
    """Unlike Chroma and Climatiq, this one is not anybody's speciality.

    Every agent quotes numbers, and none of them can be trusted to do the
    arithmetic in its own head — so the rule is the mirror image of the guard
    tests above: not "only this agent", but "no agent without it".
    """
    tool_names = {tool.name for tool in fake_sdk.RUNTIME.tools[agent]}

    assert CALCULATOR_TOOL_NAME in tool_names


def test_the_calculator_the_agents_get_actually_calculates(live_app, fake_sdk):
    """The registry holds the real tool, not a name that resolves to nothing."""
    tools = fake_sdk.RUNTIME.tools["Analista de Poluentes"]
    calculator = next(tool for tool in tools if tool.name == CALCULATOR_TOOL_NAME)

    assert calculator.tool.func("(1200 * 2.68) / 1000") == "3.216"


def test_the_same_calculator_is_registered_for_every_agent(live_app, fake_sdk):
    """One built tool, five registries — as with Tavily and Climatiq next door.

    A LangChain `Tool` here is a name, a description and a pure function, so
    there is nothing per-agent to keep apart and nothing to be mutated.
    """
    calculators = {
        id(tool.tool)
        for agent in TOOLED_AGENTS
        for tool in fake_sdk.RUNTIME.tools[agent]
        if tool.name == CALCULATOR_TOOL_NAME
    }

    assert len(calculators) == 1


def test_lifespan_publishes_sdk_factories_on_app_state(live_app, fake_sdk):
    _, api_main, _, _ = live_app
    state = api_main.app.state._state

    user = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")
    messenger = state["aeko_messenger_factory"](user, [])
    session = state["aeko_session_factory"](Session(id="s1", id_user="u1", name="n", messages=[]))

    assert isinstance(messenger, fake_sdk.AekoMessenger)
    assert isinstance(session, fake_sdk.AekoSession)
    assert isinstance(state["aeko_inventory_analyzer_factory"](), fake_sdk.AekoInventoryAnalyzer)


def test_lifespan_publishes_no_shared_sdk_instance(live_app):
    """v2 builds a messenger per user and an analyzer per report: nothing is shared."""
    _, api_main, _, _ = live_app
    state = api_main.app.state._state

    assert "aeko_messenger" not in state
    assert "aeko_inventory_analyzer" not in state


def test_every_factory_call_builds_a_fresh_instance(live_app):
    _, api_main, _, _ = live_app
    factory = api_main.app.state._state["aeko_inventory_analyzer_factory"]

    assert factory() is not factory()


def test_lifespan_pings_the_database_and_closes_the_client(api_main):
    with TestClient(api_main.app):
        pass
    client = api_main.MongoClient.instances[-1]

    assert client.database.commands == ["ping"]
    assert client.closed is True


class FakeMCPSession:
    """One MCP session as the application holds it, without a server behind it."""

    def __init__(self, name, fails_with=None):
        self.name = name
        self.fails_with = fails_with
        self.started = threading.Event()
        self.closed = False

    def start(self):
        self.started.set()
        if self.fails_with is not None:
            raise self.fails_with

    def close(self):
        self.closed = True


def printed_within(capsys, needle, timeout=5.0):
    """Wait for a background thread's `print` to arrive."""
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        output += capsys.readouterr().out
        if needle in output:
            return True
        time.sleep(0.05)
    return False


def test_lifespan_warms_up_every_mcp_session_and_closes_it_afterwards(api_main, monkeypatch):
    """Opening the sessions at start-up is what keeps the cold start off the
    first user's question; closing them is what keeps the server processes
    from outliving the API."""
    sessions = (FakeMCPSession("tavily"), FakeMCPSession("mongodb"), FakeMCPSession("chroma"))
    monkeypatch.setattr(api_main, "MCP_SESSIONS", sessions)
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "true")

    with TestClient(api_main.app):
        for session in sessions:
            assert session.started.wait(timeout=5), f"{session.name} was never started"

    assert [session.closed for session in sessions] == [True, True, True]


def test_lifespan_spawns_no_mcp_server_when_warm_up_is_switched_off(api_main, monkeypatch):
    """What the test suite itself relies on — see `AEKO_MCP_WARM_UP` in conftest."""
    session = FakeMCPSession("chroma")
    monkeypatch.setattr(api_main, "MCP_SESSIONS", (session,))
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "false")

    with TestClient(api_main.app):
        pass

    assert session.started.is_set() is False
    assert session.closed is True


def test_lifespan_starts_even_when_an_mcp_server_refuses_to(api_main, monkeypatch, capsys):
    """A broken integration must not take the whole API down with it."""
    session = FakeMCPSession("chroma", fails_with=RuntimeError("CHROMA_API_KEY is not set."))
    monkeypatch.setattr(api_main, "MCP_SESSIONS", (session,))
    monkeypatch.setattr(api_main, "MCP_WARM_UP", "true")

    with TestClient(api_main.app) as client:
        assert client.get("/aether-api/v1/ai/user/12345").status_code in (200, 404, 503)
        assert printed_within(capsys, "CHROMA_API_KEY")


IMPORTS_THE_SDK = re.compile(r"^\s*(?:from|import)\s+aeko\b", re.MULTILINE)


def test_only_the_entry_point_imports_the_sdk():
    """Guards the refactor: `aeko` must be imported in one place only."""
    ignored = {"tests", ".git", ".venv", "venv", "env", "site-packages", "__pycache__"}
    importers = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in REPO_ROOT.rglob("*.py")
        if ignored.isdisjoint(path.parts)
        and IMPORTS_THE_SDK.search(path.read_text(encoding="utf-8"))
    )

    assert importers == ["cmd/api/main.py"]


# ---------------------------------------------------------------------------
# User journey across the registered routes
# ---------------------------------------------------------------------------
def test_journey_user_then_sessions_then_messages(live_app):
    client, _, _, _ = live_app

    user = client.get("/aether-api/v1/ai/user/12345")
    assert user.status_code == 200
    assert user.json()["role"] == "analyst"

    sessions = client.get("/aether-api/v1/ai/sessions/user/u1")
    assert sessions.status_code == 200
    assert sessions.json() == [{"id": "s1", "name": "Weekly emissions review"}]

    id_session = sessions.json()[0]["id"]
    messages = client.get(f"/aether-api/v1/ai/session/{id_session}/messages")
    assert messages.status_code == 200
    assert messages.json() == [
        {
            "input_message": "Summarize this session.",
            "output_message": "Here is the summary.",
            "submitted_at": SUBMITTED_AT.isoformat(),
        }
    ]


def test_journey_unknown_user_is_404(live_app):
    client, _, _, _ = live_app

    assert client.get("/aether-api/v1/ai/user/99999").status_code == 404
    assert client.get("/aether-api/v1/ai/sessions/user/ghost").status_code == 404


# ---------------------------------------------------------------------------
# The conversational flow, end to end against the v2 SDK
# ---------------------------------------------------------------------------
def send(client, **body):
    return client.post("/aether-api/v1/ai/user/session/message", json=body)


def test_send_message_completes_the_round_trip(live_app):
    client, _, _, session_repository = live_app

    response = send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    assert response.status_code == 200, response.json()
    assert response.json()["output_message"] == "echo: What is scope 3?"
    assert len(session_repository.get_session_messages("s1")) == 2


def test_send_message_hands_the_session_document_to_the_sdk(live_app, fake_sdk):
    client, _, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    message, session, _ = fake_sdk.AekoMessenger.instances[-1].sent[-1]
    assert message == "What is scope 3?"
    assert session.id == "s1"
    assert session.id_user == "u1"
    # The turn already stored is replayed as the conversation itself.
    assert [turn.input for turn in session.messages][0] == "Summarize this session."


def test_send_message_builds_the_messenger_for_the_asking_user(live_app, fake_sdk):
    client, _, _, _ = live_app

    send(client, id_session="s1", input="hi", id_user="u1")

    messenger = fake_sdk.AekoMessenger.instances[-1]
    assert messenger.user.id_external_user == 12345
    assert messenger.user.role == "analyst"
    assert messenger.user.usecase == "report_generation"


def test_send_message_hands_over_only_the_memories_that_are_still_valid(live_app, fake_sdk):
    client, _, _, _ = live_app

    send(client, id_session="s1", input="hi", id_user="u1")

    messenger = fake_sdk.AekoMessenger.instances[-1]
    assert [memory.field for memory in messenger.memories] == ["preferred_language"]


def test_send_message_builds_a_new_messenger_for_every_request(live_app, fake_sdk):
    client, _, _, _ = live_app

    send(client, id_session="s1", input="one", id_user="u1")
    send(client, id_session="s1", input="two", id_user="u1")

    assert len(fake_sdk.AekoMessenger.instances) == 2


def test_send_message_names_a_brand_new_session_after_its_first_message(live_app):
    client, _, _, session_repository = live_app

    response = send(client, id_session="", input="How do I cut boiler emissions?", id_user="u1")

    assert response.status_code == 200
    assert session_repository.created_names == {"session-2": "How do I cut boiler emissions?"}


def test_send_message_returns_502_when_the_guardrail_rejected_every_draft(live_app, fake_sdk):
    client, _, _, session_repository = live_app
    fake_sdk.AekoMessenger.next_approved = False

    response = send(client, id_session="s1", input="hi", id_user="u1")

    assert response.status_code == 502
    assert len(session_repository.get_session_messages("s1")) == 1


# ---------------------------------------------------------------------------
# The report journey
# ---------------------------------------------------------------------------
def test_a_report_answers_with_the_plan_it_persisted(report_app):
    client, _, plan_repository, _ = report_app

    response = request_report(client)

    assert response.status_code == 200
    body = response.json()
    assert body["id_external_inventory"] == ID_INVENTORY
    assert body["id_external_unit"] == ID_UNIT
    assert body["defined_problem"] and body["method"] and body["reasoning"]
    assert [plan.id for plan in plan_repository.plans] == [body["id"]]


def test_the_inventory_is_resolved_by_the_microservice(report_app):
    """No S3, no spreadsheet: the file belongs to ms-inventory now."""
    client, _, _, inventory_repository = report_app

    request_report(client)

    assert inventory_repository.resolved == [ID_INVENTORY]


def test_the_analyzer_reads_the_markdown_the_microservice_returned(report_app, fake_sdk):
    client, *_ = report_app

    request_report(client)

    analyzer = fake_sdk.AekoInventoryAnalyzer.instances[-1]
    inventory, id_external_inventory, id_request = analyzer.analyzed[0]
    assert inventory == INVENTORY_MARKDOWN
    assert id_external_inventory == ID_INVENTORY
    assert id_request


def test_the_last_two_plans_of_the_unit_become_the_analyzers_context(report_app, fake_sdk):
    client, _, plan_repository, _ = report_app
    plan_repository.plans.extend(
        [
            ImprovementPlan(id="p1", id_external_inventory=500, id_external_unit=ID_UNIT, defined_problem="oldest problem", method="oldest method", reasoning="oldest reasoning", updated_at=datetime(2026, 1, 1)),
            ImprovementPlan(id="p2", id_external_inventory=501, id_external_unit=ID_UNIT, defined_problem="middle problem", method="middle method", reasoning="middle reasoning", updated_at=datetime(2026, 3, 1)),
            ImprovementPlan(id="p3", id_external_inventory=499, id_external_unit=ID_UNIT + 1, defined_problem="another unit", method="another method", reasoning="another reasoning", updated_at=datetime(2026, 6, 1)),
            ImprovementPlan(id="p4", id_external_inventory=498, id_external_unit=ID_UNIT, defined_problem="newest problem", method="newest method", reasoning="newest reasoning", updated_at=datetime(2026, 5, 1)),
        ]
    )

    request_report(client)

    context = fake_sdk.AekoInventoryAnalyzer.instances[-1].context
    assert "newest problem" in context and "newest method" in context
    assert "middle problem" in context and "middle reasoning" in context
    # Only two, and only this unit's.
    assert "oldest problem" not in context
    assert "another unit" not in context


def test_a_report_records_what_the_analysis_cost(report_app):
    """The analytical flow reaches the SDK now, so it is tracked like the
    conversational one."""
    client, api_main, _, _ = report_app

    response = request_report(client)

    (document,) = stored_metrics(api_main)
    assert document["flow"] == "analytical"
    assert document["id_request"] == response.headers["x-request-id"]


def test_the_plan_is_remembered_for_the_user_who_asked(report_app, live_app):
    client, *_ = report_app
    _, _, user_repository, _ = live_app

    request_report(client)

    memory = user_repository.memories[-1]
    assert memory.id_user == "u1"
    assert memory.field == "improvement_plan"


# ---------------------------------------------------------------------------
# What the run cost, end to end
# ---------------------------------------------------------------------------
def stored_metrics(api_main):
    return list(api_main.db["aeko_metrics"].documents)


def test_send_message_records_what_the_run_cost(live_app):
    client, api_main, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (document,) = stored_metrics(api_main)
    assert document["flow"] == "conversational"
    assert document["error_description"] is None
    assert document["latency"] > 0
    assert [agent["name"] for agent in document["used_agents"]] == ["FAQ"]


def test_the_recorded_run_names_the_request_its_caller_was_answered_with(live_app):
    """The one thing that makes the two bases readable together: the SDK is
    handed the identifier the gateway already minted, not one of its own."""
    client, api_main, _, _ = live_app

    response = send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (document,) = stored_metrics(api_main)
    assert document["id_request"] == response.headers["x-request-id"]


def test_the_two_metric_bases_name_the_same_request(live_app):
    client, api_main, _, _ = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    (request_row,) = list(api_main.db["hub_metrics"].documents)
    (run_row,) = stored_metrics(api_main)
    assert str(request_row["_id"]) == run_row["id_request"]


def test_a_turn_the_guardrail_rejected_is_still_recorded(live_app, fake_sdk):
    client, api_main, _, _ = live_app
    fake_sdk.AekoMessenger.next_approved = False

    response = send(client, id_session="s1", input="hi", id_user="u1")

    assert response.status_code == 502
    (document,) = stored_metrics(api_main)
    assert document["error_description"] == "no answer approved by the output guardrail"


def test_a_request_that_never_reached_the_sdk_records_no_run(live_app):
    client, api_main, _, _ = live_app

    client.get("/aether-api/v1/ai/sessions/user/u1")

    assert stored_metrics(api_main) == []


def test_the_stored_turn_no_longer_carries_what_it_cost(live_app):
    """3.1 reduced `session.messages` to the exchange itself."""
    client, _, _, session_repository = live_app

    send(client, id_session="s1", input="What is scope 3?", id_user="u1")

    turn = session_repository.get_session_messages("s1")[-1]
    assert set(vars(turn)) == {"input", "output", "submitted_at"}
