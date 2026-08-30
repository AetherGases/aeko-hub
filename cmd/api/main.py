from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient

from internal.http.improvement_plan_handlers import router as improvement_plan_router
from internal.http.session_handlers import router as session_router
from internal.http.user_handlers import router as user_router

# Single entry point for all aeko imports. Every other module receives
# SDK instances/DTOs through dependency injection instead of importing the
# package directly.
from aeko import (
    Aeko,
    AekoInventoryAnalyzer,
    AekoMessage,
    AekoMessenger,
    AekoSession,
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

# Tools must follow the defined interfaces in Aeko SDK. The keys are the
# agents' own names, which is what the graph routes by — pass them exactly as
# the SDK spells them, accents included. `set_tools()` replaces the whole
# registry, so every agent's tools travel in the single call below.
AEKO_TOOLS = {
    "FAQ": [],  # Fill up later....
    "Análista de inventários": [],  # Fill up later....
    "Analista de Poluentes": [],  # Fill up later....
    "Analista de Gases Verdes": [],  # Fill up later....
    "Coordenador de Melhoria Contínua": [],  # Fill up later....
}

mongo_client = None
db = None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value else None


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


def build_inventory_analyzer() -> AekoInventoryAnalyzer:
    """A fresh analyzer per report: `set_context()` is instance state."""
    return AekoInventoryAnalyzer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db

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
        db.command("ping")
    except Exception as exc:
        print(f"MongoDB error: {type(exc).__name__}: {exc}")
        raise
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
    title="Aether AI Gateway",
    version="1.0.0",
    description="HTTP API for user, session, and report workflows in the Aether core gateway.",
    openapi_tags=OPENAPI_TAGS,
)
app.include_router(user_router)
app.include_router(session_router)
app.include_router(improvement_plan_router)
