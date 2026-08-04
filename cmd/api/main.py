from contextlib import asynccontextmanager
import os
import sys
from unittest.mock import MagicMock

from dotenv import load_dotenv
from fastapi import FastAPI
from pymongo import MongoClient

from internal.http.session_handlers import router as session_router
from internal.http.user_handlers import router as user_router

# Mocks ai sdk
mock_aeko = MagicMock()

mock_aeko.AekoMessenger = MagicMock()

sys.modules["aeko_sdk"] = mock_aeko

from aeko_sdk import AekoMessenger # type: ignore
from aeko_sdk import AekoMessageDTO # type: ignore

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
aeko_model_list = os.getenv("AEKO_MODEL_LIST")
aeko_api_key_list = os.getenv("AEKO_API_KEY_LIST")

# Tools must follow the defined interfaces in Aeko SDK
AEKO_REPORT_ANALYTICS_TOOLS = [] # Fill up later....
AEKO_POLLUTANTS_ANALYTICS_TOOLS = [] # Fill up later....
AEKO_GREEN_GASES_ANALYTICS_TOOLS = [] # Fill up later....
AEKO_VIABILLITY_ANALYTICS_TOOLS = [] # Fill up later...., only web query
AEKO_REPORT_BUILDER_TOOLS = [] # Fill up later....


mongo_client = None
db = None

aeko_model_list = aeko_model_list.split(",") if aeko_model_list else []
aeko_api_key_list = aeko_api_key_list.split(",") if aeko_api_key_list else []
aeko_messenger = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db
    aeko_messenger = AekoMessenger()
    aeko_messenger.config(models=aeko_model_list, api_keys=aeko_api_key_list)
    aeko_messenger.set_tools(
        report_analytics_tools=AEKO_REPORT_ANALYTICS_TOOLS,
        pollutants_analytics_tools=AEKO_POLLUTANTS_ANALYTICS_TOOLS,
        green_gases_analytics_tools=AEKO_GREEN_GASES_ANALYTICS_TOOLS,
        viability_analytics_tools=AEKO_VIABILLITY_ANALYTICS_TOOLS,
        report_builder_tools=AEKO_REPORT_BUILDER_TOOLS
    )
    app.state._state["aeko_messenger"] = aeko_messenger
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
    title="Aether AI Gateway",
    version="1.0.0",
    description="HTTP API for user, session, and report workflows in the Aether core gateway.",
    openapi_tags=OPENAPI_TAGS,
)
app.include_router(user_router)
app.include_router(session_router)