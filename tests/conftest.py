"""Shared test setup.

Two things must happen before any application module is imported:

1. `aeko` is registered in `sys.modules` pointing at `tests.fake_aeko`.
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

from tests import fake_aeko

sys.modules.setdefault("aeko", fake_aeko)

os.environ["MONGO_URI"] = "mongodb://fake-host:27017"
os.environ["DB_NAME"] = "aeko_test"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["AEKO_FAST_MODEL"] = "fast-model"
os.environ["AEKO_SLOW_MODEL"] = "slow-model"
os.environ["AEKO_MAX_TOKENS"] = "512"
os.environ["AEKO_REPORT_MAX_TOKENS"] = "4096"


# --------------------------------------------------------------------------
# Fake Mongo, used only to let the real app lifespan start without a server.
# --------------------------------------------------------------------------
class FakeCollection:
    def __init__(self, documents=None):
        """Start the collection holding `documents`, if any were given."""
        self.documents = list(documents or [])

    def find(self, query=None, projection=None):
        """Return every document; query and projection are ignored."""
        return list(self.documents)

    def find_one(self, query=None, projection=None):
        """Return the first document, or `None` when there is none."""
        return self.documents[0] if self.documents else None

    def insert_one(self, document):
        """Append a document and report a fixed inserted id."""
        self.documents.append(document)
        return type("InsertOneResult", (), {"inserted_id": "fake-inserted-id"})()

    def update_one(self, query, update):
        """Accept the update and do nothing with it."""
        return None


class FakeDatabase:
    def __init__(self):
        """Start with no collections and no commands recorded."""
        self.collections = {}
        self.commands = []

    def __getitem__(self, name):
        """Return a collection by name, creating it on first use."""
        return self.collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        """Expose collections as attributes, the way pymongo does."""
        if name in {"collections", "commands"}:
            raise AttributeError(name)
        return self[name]

    def command(self, name):
        """Record a database command and report it succeeded."""
        self.commands.append(name)
        return {"ok": 1}


class FakeMongoClient:
    """Drop-in replacement for `pymongo.MongoClient` in the app lifespan."""

    instances = []

    def __init__(self, uri=None, *args, **kwargs):
        """Register this client so tests can assert on it afterwards."""
        self.uri = uri
        self.database = FakeDatabase()
        self.closed = False
        FakeMongoClient.instances.append(self)

    def __getitem__(self, name):
        """Return the one fake database, whatever name is asked for."""
        return self.database

    def close(self):
        """Mark the client closed, so the lifespan can be asserted on."""
        self.closed = True


@pytest.fixture(autouse=True)
def reset_sdk():
    """The SDK fake keeps process-wide state, exactly like the real one."""
    fake_aeko.Aeko.reset()
    yield
    fake_aeko.Aeko.reset()


@pytest.fixture
def fake_sdk():
    """The module registered as `aeko` for the whole suite."""
    return fake_aeko


@pytest.fixture
def api_main(monkeypatch, reset_sdk):
    """The real `cmd.api.main` module with Mongo replaced by a fake client.

    Imported lazily so the environment above is already in place, and reloaded
    per test so module-level state never leaks between tests.
    """
    FakeMongoClient.instances = []
    module = importlib.import_module("cmd.api.main")
    module = importlib.reload(module)
    monkeypatch.setattr(module, "MongoClient", FakeMongoClient)
    return module
