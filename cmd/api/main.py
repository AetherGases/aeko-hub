from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pymongo import MongoClient
import os
import uvicorn

from internal.http.user_handlers import router as user_router

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

mongo_client = None
db = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    app.state.db = db
    try:
        db.command("ping")
    except Exception as exc:
        raise RuntimeError("Failed to connect to MongoDB") from exc
    yield
    mongo_client.close()

app = FastAPI(lifespan=lifespan)
app.include_router(user_router)