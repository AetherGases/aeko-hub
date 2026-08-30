"""Unit tests for the concrete user repository and its query helpers.

`user.database.repository.Repository` is the object both
`GET /v1/ai/user/{id_external_user}` and
`POST /aether-api/v1/ai/user/session/message` build at request time, so the
contract it must honour is `user.user.IRepository`.
"""

from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from tests.mongo_doubles import StubCollection, StubDatabase
from user.database import query as q
from user.database.repository import Repository
from user.entity import User, UserMemory
from user.user import IRepository

ID_USER = "65a8b3d6c0f8e1d7f4b2c010"

USER_DOCUMENT = {
    "_id": ID_USER,
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
}

MEMORY_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c099",
    "id_user": "65a8b3d6c0f8e1d7f4b2c010",
    "field": "improvement_plan",
    "description": "replace the boiler",
    "created_at": datetime(2026, 7, 26, 14, 30, 0),
    "expires_at": datetime(2026, 8, 7, 14, 30, 0),
}


def build_repository(user=None, user_memory=None):
    database = StubDatabase(user=user or StubCollection(), user_memory=user_memory or StubCollection())
    return Repository(database), database


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_repository_implements_the_repository_interface():
    assert issubclass(Repository, IRepository)


def test_repository_has_no_unimplemented_abstract_method():
    assert Repository.__abstractmethods__ == frozenset()


def test_repository_can_be_instantiated():
    repository = Repository("db")

    assert isinstance(repository, IRepository)
    assert repository.db == "db"


@pytest.mark.parametrize("method", sorted(IRepository.__abstractmethods__))
def test_repository_exposes_every_method_of_the_interface(method):
    assert callable(getattr(Repository, method, None))


# ---------------------------------------------------------------------------
# get_user - used by GET /v1/ai/user/{id_external_user}
# ---------------------------------------------------------------------------
def test_get_user_returns_the_user_entity():
    repository, _ = build_repository(user=StubCollection(find_one_result=USER_DOCUMENT))

    user = repository.get_user(12345)

    assert isinstance(user, User)
    assert (user.id, user.id_external_user, user.role, user.usecase) == (
        "65a8b3d6c0f8e1d7f4b2c010",
        12345,
        "analyst",
        "report_generation",
    )


def test_get_user_queries_by_the_external_identifier():
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user(12345)

    assert collection.call_args("find_one")[0][0] == {"id_external_user": 12345}


def test_get_user_reads_the_collection_only_once():
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user(12345)

    assert len(collection.call_args("find_one")) == 1


def test_get_user_raises_value_error_when_not_found():
    repository, _ = build_repository(user=StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match="12345"):
        repository.get_user(12345)


def test_get_user_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(user=StubCollection(error=OSError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        repository.get_user(12345)


# ---------------------------------------------------------------------------
# get_user_by_id - used when a new session is created
# ---------------------------------------------------------------------------
def test_get_user_by_id_returns_the_user_entity():
    repository, _ = build_repository(user=StubCollection(find_one_result=USER_DOCUMENT))

    user = repository.get_user_by_id("65a8b3d6c0f8e1d7f4b2c010")

    assert isinstance(user, User)
    assert user.id == "65a8b3d6c0f8e1d7f4b2c010"


def test_get_user_by_id_queries_by_the_internal_identifier():
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user_by_id(ID_USER)

    query = collection.call_args("find_one")[0][0]
    assert {"_id": ID_USER} in query["$or"]
    assert {"_id": ObjectId(ID_USER)} in query["$or"]


def test_get_user_by_id_returns_none_when_not_found():
    repository, _ = build_repository(user=StubCollection(find_one_result=None))

    assert repository.get_user_by_id("ghost") is None


def test_get_user_by_id_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(user=StubCollection(error=OSError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        repository.get_user_by_id("u1")


# ---------------------------------------------------------------------------
# user memories
# ---------------------------------------------------------------------------
def test_get_user_memories_maps_every_document():
    repository, _ = build_repository(user_memory=StubCollection(find_result=[MEMORY_DOCUMENT]))

    memories = repository.get_user_memories("65a8b3d6c0f8e1d7f4b2c010")

    assert len(memories) == 1
    assert isinstance(memories[0], UserMemory)
    assert memories[0].field == "improvement_plan"
    assert memories[0].created_at == MEMORY_DOCUMENT["created_at"]


def test_get_user_memories_renders_an_object_id_owner_as_text():
    document = {**MEMORY_DOCUMENT, "_id": ObjectId(MEMORY_DOCUMENT["_id"]), "id_user": ObjectId(ID_USER)}
    repository, _ = build_repository(user_memory=StubCollection(find_result=[document]))

    memories = repository.get_user_memories(ID_USER)

    assert memories[0].id_user == ID_USER


def test_get_user_memories_returns_an_empty_list():
    repository, _ = build_repository(user_memory=StubCollection(find_result=[]))

    assert repository.get_user_memories("u1") == []


def test_get_user_memories_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(user_memory=StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_user_memories("u1")


def test_create_user_memory_inserts_the_document():
    collection = StubCollection()
    repository, _ = build_repository(user_memory=collection)
    created_at = datetime(2026, 7, 26, 14, 30, 0)

    repository.create_user_memory(
        UserMemory(id=None, id_user="u1", field="improvement_plan", description="text", created_at=created_at)
    )

    document = collection.call_args("insert_one")[0][0]
    assert document["id_user"] == "u1"
    assert document["field"] == "improvement_plan"
    assert document["created_at"] == created_at


def test_create_user_memory_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(user_memory=StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create_user_memory(UserMemory(id=None, id_user="u1", field="f", description="d"))


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------
def test_get_user_query_filter_targets_the_external_identifier():
    assert q.get_user_query_filter(12345) == {"id_external_user": 12345}


def test_get_user_query_filter_keeps_the_external_identifier_a_number():
    """`id_external_user` references Postgres, never a Mongo `_id`."""
    assert isinstance(q.get_user_query_filter(12345)["id_external_user"], int)


def test_get_user_query_targets_the_internal_identifier():
    query, projection = q.get_user_query(ID_USER)

    assert {"_id": ID_USER} in query["$or"]
    assert {"_id": ObjectId(ID_USER)} in query["$or"]
    assert projection == {}


def test_get_user_query_keeps_an_identifier_that_is_not_an_object_id():
    query, _ = q.get_user_query("u1")

    assert query["$or"] == [{"_id": "u1"}, {"_id": "u1"}]


def test_get_user_memories_query_targets_the_user():
    query = q.get_user_memories_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert {"id_user": ObjectId(ID_USER)} in query["$or"]


def test_create_user_memory_query_stores_the_owner_as_an_object_id():
    document = q.create_user_memory_query(UserMemory(id=None, id_user=ID_USER, field="f", description="d"))

    assert document["id_user"] == ObjectId(ID_USER)


def test_create_user_memory_query_keeps_an_owner_that_is_not_an_object_id():
    document = q.create_user_memory_query(UserMemory(id=None, id_user="u1", field="f", description="d"))

    assert document["id_user"] == "u1"


def test_create_user_memory_query_keeps_explicit_timestamps():
    created_at = datetime(2026, 7, 26, 14, 30, 0)
    expires_at = datetime(2026, 9, 1, 0, 0, 0)

    document = q.create_user_memory_query(
        UserMemory(id=None, id_user="u1", field="f", description="d", created_at=created_at, expires_at=expires_at)
    )

    assert document["created_at"] == created_at
    assert document["expires_at"] == expires_at


def test_create_user_memory_query_defaults_the_expiration_window():
    created_at = datetime(2026, 7, 26, 14, 30, 0)

    document = q.create_user_memory_query(
        UserMemory(id=None, id_user="u1", field="f", description="d", created_at=created_at)
    )

    assert document["expires_at"] == created_at + timedelta(days=q.USER_MEMORY_TTL_DAYS)


def test_create_user_memory_query_defaults_the_creation_timestamp():
    document = q.create_user_memory_query(UserMemory(id=None, id_user="u1", field="f", description="d"))

    assert isinstance(document["created_at"], datetime)
    assert document["expires_at"] > document["created_at"]
