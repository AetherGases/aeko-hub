from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pymongo import MongoClient
import os
import uvicorn

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
    try:
        db.command("ping")
    except Exception as exc:
        raise RuntimeError("Failed to connect to MongoDB") from exc
    yield
    mongo_client.close()

app = FastAPI(lifespan=lifespan)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=True)