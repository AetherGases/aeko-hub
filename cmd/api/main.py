from contextlib import asynccontextmanager
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient

from cmd.api.integrations.climatiq_api import get_climatiq_tools
from cmd.api.mcp.chroma_mcp import CHROMA_SESSION, get_gases_info_tools
from cmd.api.mcp.mongo_mcp import (
    MONGO_SESSION,
    get_improvement_plan_tools,
    get_user_memory_tools,
)
from cmd.api.mcp.tavily_mcp import (
    TAVILY_SESSION,
    get_tavily_search_tools,
    get_tavily_site_map_tool,
)
from cmd.api.tools.calculator import get_calculator_tools
from cmd.api.tools.finance import get_roi_payback_tools
from hub_metrics.database.repository import Repository as HubMetricsRepository
from hub_metrics.entity import Metric
from hub_metrics.service import Service as HubMetricsService
from internal.http.hub_metrics_handlers import router as hub_metrics_router
from internal.http.improvement_plan_handlers import router as improvement_plan_router
from internal.http.session_handlers import router as session_router
from internal.http.user_handlers import router as user_router
from shared import (
    Event,
    Module,
    RequestLogMiddleware,
    log_failure,
    operation,
    set_event_sink,
    silence_uvicorn_access_log,
)

# Single entry point for all aeko imports. Every other module receives
# SDK instances/DTOs through dependency injection instead of importing the
# package directly.
from aeko import (
    Aeko,
    AekoInventoryAnalyzer,
    AekoMessage,
    AekoMessenger,
    AekoSession,
    AekoTool,
    AekoUser,
    AekoUserMemory,
)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# The SDK never reads the environment: this application owns its configuration
# and passes it in through `Aeko.config()`. Only the key is required — every
# other setting falls back to the SDK's own default when left unset.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AEKO_FAST_MODEL = os.getenv("AEKO_FAST_MODEL")
AEKO_SLOW_MODEL = os.getenv("AEKO_SLOW_MODEL")
AEKO_MAX_TOKENS = os.getenv("AEKO_MAX_TOKENS")
AEKO_REPORT_MAX_TOKENS = os.getenv("AEKO_REPORT_MAX_TOKENS")

# Tools coming from MCP servers, wrapped as `AekoTool` here — the one place
# that imports `aeko` — so agent modules only ever hand back plain LangChain
# tools (see `cmd/api/mcp/tavily_mcp.py`).
TAVILY_SITE_MAP_TOOLS = [AekoTool(tool=tool) for tool in get_tavily_site_map_tool()]
TAVILY_RESEARCH_TOOLS = [AekoTool(tool=tool) for tool in get_tavily_search_tools()]

# MongoDB MCP: read-only `find`, each pinned in code to one collection (see
# cmd/api/mcp/mongo_mcp.py) — an agent never chooses the collection itself.
IMPROVEMENT_PLAN_TOOLS = [AekoTool(tool=tool) for tool in get_improvement_plan_tools()]
USER_MEMORY_TOOLS = [AekoTool(tool=tool) for tool in get_user_memory_tools()]

# ChromaDB MCP: vector search over the `gases-info` collection, pinned in code
# (see cmd/api/mcp/chroma_mcp.py). Only the green gas analyst gets it.
GASES_INFO_TOOLS = [AekoTool(tool=tool) for tool in get_gases_info_tools()]

# Climatiq's emission factor search and calculator, reached over plain HTTPS
# rather than MCP (see cmd/api/integrations/climatiq_api.py). Only the
# pollutant analyst gets them.
CLIMATIQ_TOOLS = [AekoTool(tool=tool) for tool in get_climatiq_tools()]

# Arithmetic, computed in this process (see cmd/api/tools/calculator.py). The
# one tool below that is nobody's speciality: every agent quotes numbers, and
# a language model arriving at them by predicting digits is every agent's way
# of being confidently wrong.
CALCULATOR_TOOLS = [AekoTool(tool=tool) for tool in get_calculator_tools()]

# ROI and payback over a fixed 60-month horizon, computed in this process as
# well (see cmd/api/tools/finance.py). Only the improvement coordinator
# gets them: it is the one agent that proposes spending money, and these are
# the two questions its proposals are judged by.
ROI_PAYBACK_TOOLS = [AekoTool(tool=tool) for tool in get_roi_payback_tools()]

# Tools must follow the defined interfaces in Aeko SDK. The keys are the
# agents' own names, which is what the graph routes by — pass them exactly as
# the SDK spells them, accents included. `set_tools()` replaces the whole
# registry, so every agent's tools travel in the single call below.
AEKO_TOOLS = {
    # FAQ only maps the Aether website — it never gets a free-form search tool.
    "FAQ": list(TAVILY_SITE_MAP_TOOLS)
    + list(TAVILY_RESEARCH_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(CALCULATOR_TOOLS),
    "Análista de inventários": list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(CALCULATOR_TOOLS),
    # The only agent that calculates emissions through Climatiq.
    "Analista de Poluentes": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(CLIMATIQ_TOOLS)
    + list(CALCULATOR_TOOLS),
    # The only agent that reads the `gases-info` vector store.
    "Analista de Gases Verdes": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(GASES_INFO_TOOLS)
    + list(CALCULATOR_TOOLS),
    # The only agent that weighs an investment before proposing it.
    "Coordenador de Melhoria Contínua": list(TAVILY_RESEARCH_TOOLS)
    + list(IMPROVEMENT_PLAN_TOOLS)
    + list(USER_MEMORY_TOOLS)
    + list(CALCULATOR_TOOLS)
    + list(ROI_PAYBACK_TOOLS),
}

# Every MCP server this application talks to keeps one session open for the
# life of the process (see `cmd/api/mcp/mcp_session.py`).
MCP_SESSIONS = (TAVILY_SESSION, MONGO_SESSION, CHROMA_SESSION)

# Opening those sessions starts the server processes, which is the whole cost
# of a cold start — for Chroma, importing torch and loading model weights. The
# test suite sets this to "false" so running the tests never spawns a server.
MCP_WARM_UP = os.getenv("AEKO_MCP_WARM_UP", "true")

mongo_client = None
db = None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value else None


def _warm_up_mcp_sessions() -> None:
    """Start every MCP server now, in the background.

    In the background because the sessions must not hold up the port: the API
    answers immediately, and the servers finish waking while the first user is
    still typing. A session that fails to open is reported and left alone —
    the call that needs it will try again and raise properly.
    """

    def warm_up(session) -> None:
        try:
            # `start()` logs the server's cold start itself, blue or red.
            # What is added here is that the warm-up gave up on it: the API
            # is now serving with that server unopened.
            session.start()
        except Exception as exc:
            log_failure(
                Module.MCP,
                f"{session.name}.warm_up gave up: {type(exc).__name__}: {exc}",
            )

    for session in MCP_SESSIONS:
        threading.Thread(target=warm_up, args=(session,), daemon=True).start()


def build_messenger(user, memories) -> AekoMessenger:
    """A messenger for one user, built per request.

    It holds only *who* is asking: the conversation travels with each
    `send_message()` call instead, so nothing about a session is retained
    between requests and any worker can serve any conversation.
    """
    return AekoMessenger(
        AekoUser(
            id=user.id,
            id_external_user=user.id_external_user,
            role=user.role,
            usecase=user.usecase,
        ),
        [
            AekoUserMemory(
                id=memory.id,
                id_user=memory.id_user,
                field=memory.field,
                description=memory.description,
                created_at=memory.created_at,
                expires_at=memory.expires_at,
            )
            for memory in memories
        ],
    )


def build_session(session) -> AekoSession:
    """The session document the SDK reads the conversation from and appends to."""
    return AekoSession(
        id=session.id,
        id_user=session.id_user,
        name=session.name,
        messages=[
            AekoMessage(
                input=message.input,
                output=message.output,
                submitted_at=message.submitted_at,
                llm=message.llm,
                input_tokens=message.input_tokens,
                output_tokens=message.output_tokens,
            )
            for message in session.messages
        ],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def build_metric_sink(database):
    """The function `shared/event_tracking.py` calls to persist one request.

    It lives here because this is the only file that may know both halves:
    `shared` holds an `Event` and no domain, and the domain holds a `Metric`
    and no middleware. The translation between the two is composition, which
    is what this module is.
    """

    service = HubMetricsService(HubMetricsRepository(database))

    def sink(event: Event) -> None:
        service.add_metric(
            Metric(
                # `_id`, because that is what the caller was already
                # answered with in the `x-request-id` header: the row has to be
                # findable under exactly the value they were handed.
                id=event.id_request,
                latency=event.latency,
                response_status=event.response_status,
                endpoint=event.endpoint,
            )
        )

    return sink


def build_inventory_analyzer() -> AekoInventoryAnalyzer:
    """A fresh analyzer per report: `set_context()` is instance state."""
    return AekoInventoryAnalyzer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db

    # Before the first request, and after uvicorn has configured its own
    # logging: `RequestLogMiddleware` closes every request with a block
    # that says what the request did, and uvicorn's access line would
    # only repeat its first sentence.
    silence_uvicorn_access_log()

    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db

    # Event tracking starts here and nowhere earlier: the middleware has been
    # answering requests since import, but it has nothing to write to until
    # this database handle exists.
    set_event_sink(build_metric_sink(db))

    # Process-wide setup: exactly once, before the first request. Both calls
    # rebuild every agent, so doing either per request would throw away warm
    # agents for every concurrent run.
    Aeko.config(
        GEMINI_API_KEY,
        fast_model=AEKO_FAST_MODEL,
        slow_model=AEKO_SLOW_MODEL,
        max_tokens=_int_or_none(AEKO_MAX_TOKENS),
        report_max_tokens=_int_or_none(AEKO_REPORT_MAX_TOKENS),
    )
    AekoMessenger.set_tools(AEKO_TOOLS)

    # The SDK objects are per-request, so what the application publishes are
    # the factories that build them from this API's own entities.
    app.state._state["aeko_messenger_factory"] = build_messenger
    app.state._state["aeko_session_factory"] = build_session
    app.state._state["aeko_inventory_analyzer_factory"] = build_inventory_analyzer

    try:
        # The first database access of the process, and the one that decides
        # whether there is an application at all — so it is logged like every
        # other one instead of being narrated by a `print`.
        with operation(Module.DATABASE, "mongo.ping"):
            db.command("ping")
    except Exception as exc:
        raise RuntimeError(f"Failed to connect to MongoDB: {exc}") from exc

    if MCP_WARM_UP.strip().lower() not in {"false", "0", "no"}:
        _warm_up_mcp_sessions()

    yield

    # Before the client below is closed: a sink left registered would hand the
    # next request a database that is no longer there.
    set_event_sink(None)

    # Each open session owns a server process — the Chroma one holding a
    # gigabyte of model weights. Closing them here is what keeps them from
    # outliving the API.
    for session in MCP_SESSIONS:
        session.close()

    mongo_client.close()

OPENAPI_TAGS = [
    {
        "name": "Users",
        "description": "Endpoints for retrieving user profile data used by the AI gateway.",
    },
    {
        "name": "Sessions",
        "description": "Endpoints for listing sessions and session messages.",
    },
    {
        "name": "Reports",
        "description": "Endpoints for generating AI-assisted reports and improvement plans.",
    },
    {
        "name": "Metrics",
        "description": "Endpoints for reading the event tracking base behind the observability dashboard.",
    },
]

app = FastAPI(
    lifespan=lifespan,
    title="Aether AI Gateway",
    version="1.0.0",
    description=(
        "HTTP API for user, session, and report workflows in the Aether core gateway. "
        "Every response carries an X-Request-Id header: the identifier of that request "
        "in the hub_metrics base."
    ),
    openapi_tags=OPENAPI_TAGS,
)
# Outermost of this application's own middleware, so the block covers the
# whole request rather than what is left of it after the others.
app.add_middleware(RequestLogMiddleware)

app.include_router(user_router)
app.include_router(session_router)
app.include_router(improvement_plan_router)
app.include_router(hub_metrics_router)
