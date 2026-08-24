from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient

from internal.http.improvement_plan_handlers import router as improvement_plan_router
from internal.http.session_handlers import router as session_router
from internal.http.user_handlers import router as user_router

# Single entry point for all aeko imports. Every other module receives SDK
# factories/values through dependency injection instead of importing the
# package directly.
from aeko import (
    AGENT_NAMES,
    Aeko,
    AekoInventoryAnalyzer,
    AekoMessenger,
    AekoTool,
)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# The SDK never reads the environment on its own; the application owns its
# configuration and passes it in through Aeko.config().
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AEKO_FAST_MODEL = os.getenv("AEKO_FAST_MODEL")
AEKO_SLOW_MODEL = os.getenv("AEKO_SLOW_MODEL")
AEKO_MAX_TOKENS = os.getenv("AEKO_MAX_TOKENS")
AEKO_REPORT_MAX_TOKENS = os.getenv("AEKO_REPORT_MAX_TOKENS")

# Tools are bound per agent. The keys are the SDK's routing keys and must be
# written exactly as in AGENT_NAMES, accents included. Each entry is either a
# bare LangChain tool or an AekoTool(tool=..., description=...).
AEKO_TOOLS: dict[str, list] = {
    "FAQ": [],  # Fill up later....
    "Análista de inventários": [],  # Fill up later....
    "Analista de Poluentes": [],  # Fill up later....
    "Analista de Gases Verdes": [],  # Fill up later....
    "Coordenador de Melhoria Contínua": [],  # Fill up later....
}

mongo_client = None
db = None

def _optional_int(value: str | None) -> int | None:
    """Read an optional numeric setting, leaving unset ones as `None`.

    `None` is what tells the SDK to keep its own default.
    """
    return int(value) if value else None


def build_gas_reduction_context(data: dict) -> str:
    """Render the external gas reduction payload as the plain text the SDK wants.

    `AekoInventoryAnalyzer.set_context()` takes free-form text describing the
    previous report, so the dict coming from the external API is flattened into
    readable `key: value` lines.
    """
    return "\n".join(f"{key}: {value}" for key, value in data.items())


def configure_aeko() -> None:
    """Process-wide SDK setup. Runs once, at startup, never per request."""
    unknown_agents = set(AEKO_TOOLS) - set(AGENT_NAMES)
    if unknown_agents:
        raise RuntimeError(
            f"Unknown Aeko agent names in AEKO_TOOLS: {sorted(unknown_agents)}. "
            f"Valid names: {list(AGENT_NAMES)}"
        )

    Aeko.config(
        GEMINI_API_KEY,
        fast_model=AEKO_FAST_MODEL or None,
        slow_model=AEKO_SLOW_MODEL or None,
        max_tokens=_optional_int(AEKO_MAX_TOKENS),
        report_max_tokens=_optional_int(AEKO_REPORT_MAX_TOKENS),
    )
    AekoMessenger.set_tools(AEKO_TOOLS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the database, configure the SDK, and publish both on `app.state`.

    Everything here runs exactly once per process, before the first request:
    the SDK rebuilds every agent on configuration, so doing it per request
    would throw away warm agents under load. The connection is closed and
    the SDK left configured when the app shuts down.
    """
    global mongo_client, db
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db

    configure_aeko()

    # Factories, not instances: both SDK entry points carry per-session mutable
    # state (`prepare()` history, `set_context()`), so a shared instance would
    # leak one request's context into the next.
    app.state._state["aeko_messenger_factory"] = AekoMessenger
    app.state._state["aeko_inventory_analyzer_factory"] = AekoInventoryAnalyzer
    app.state._state["build_gas_reduction_context"] = build_gas_reduction_context
    app.state._state["aeko_tool"] = AekoTool
    try:
        db.command("ping")
    except Exception as exc:
        raise RuntimeError("Failed to connect to MongoDB") from exc
    yield
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
]

app = FastAPI(
    lifespan=lifespan,
    title="Aeko API",
    version="1.0.0",
    description="HTTP API for user, session, and report workflows in the Aeko core gateway.",
    openapi_tags=OPENAPI_TAGS,
)
app.include_router(user_router)
app.include_router(session_router)