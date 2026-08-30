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

# The 1.x variables are gone; clearing them keeps a developer's local `.env`
# from making a stale name look supported.
os.environ.pop("AEKO_MODEL_LIST", None)
os.environ.pop("AEKO_API_KEY_LIST", None)


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


@pytest.fixture(autouse=True)
def reset_aeko_runtime():
    """`Aeko.config()` and `set_tools()` are process-wide; no test may inherit them."""
    fake_aeko.Aeko.reset()
    yield
    fake_aeko.Aeko.reset()


@pytest.fixture
def fake_sdk():
    """The module registered as `aeko` for the whole suite."""
    return fake_aeko


@pytest.fixture
def configured_sdk(reset_aeko_runtime):
    """The SDK as a started application leaves it: an API key supplied.

    Tests that mount a router without running the real lifespan need this;
    without it the SDK refuses every run, which is what `AekoNotConfiguredError`
    is for.
    """
    fake_aeko.Aeko.config("test-gemini-key")
    return fake_aeko


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
