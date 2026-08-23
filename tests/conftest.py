"""Shared test setup.

Two things must happen before any application module is imported:

1. `aeko_sdk` is registered in `sys.modules` pointing at `tests.fake_aeko_sdk`.
   The API imports the real SDK only at its entry point (`cmd/api/main.py`),
   so registering the fake here is enough for the whole suite.
2. The environment variables `cmd/api/main.py` reads at import time are set.
   `load_dotenv()` does not override variables that already exist, so these
   values win over any local `.env`.

pytest imports `conftest.py` before the test modules, so the module-level
statements below always run first.
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import fake_aeko_sdk

sys.modules.setdefault("aeko_sdk", fake_aeko_sdk)

os.environ["MONGO_URI"] = "mongodb://fake-host:27017"
os.environ["DB_NAME"] = "aeko_test"
os.environ["AEKO_MODEL_LIST"] = "model-a,model-b"
os.environ["AEKO_API_KEY_LIST"] = "key-a,key-b"


# --------------------------------------------------------------------------
# Fake Mongo, used only to let the real app lifespan start without a server.
# --------------------------------------------------------------------------
class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find(self, query=None, projection=None):
        return list(self.documents)

    def find_one(self, query=None, projection=None):
        return self.documents[0] if self.documents else None

    def insert_one(self, document):
        self.documents.append(document)
        return type("InsertOneResult", (), {"inserted_id": "fake-inserted-id"})()

    def update_one(self, query, update):
        return None


class FakeDatabase:
    def __init__(self):
        self.collections = {}
        self.commands = []

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        if name in {"collections", "commands"}:
            raise AttributeError(name)
        return self[name]

    def command(self, name):
        self.commands.append(name)
        return {"ok": 1}


class FakeMongoClient:
    """Drop-in replacement for `pymongo.MongoClient` in the app lifespan."""

    instances = []

    def __init__(self, uri=None, *args, **kwargs):
        self.uri = uri
        self.database = FakeDatabase()
        self.closed = False
        FakeMongoClient.instances.append(self)

    def __getitem__(self, name):
        return self.database

    def close(self):
        self.closed = True


@pytest.fixture
def fake_sdk():
    """The module registered as `aeko_sdk` for the whole suite."""
    return fake_aeko_sdk


@pytest.fixture
def api_main(monkeypatch):
    """The real `cmd.api.main` module with Mongo replaced by a fake client.

    Imported lazily so the environment above is already in place, and reloaded
    per test so module-level state never leaks between tests.
    """
    FakeMongoClient.instances = []
    module = importlib.import_module("cmd.api.main")
    module = importlib.reload(module)
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)
    return module
