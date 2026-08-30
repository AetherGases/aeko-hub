"""Unit tests for the user service business rules."""

import pytest

from user.entity import User, UserMemory
from user.service import Service
from user.user import IService

USER = User(id="u1", id_external_user=12345, role="analyst", usecase="report_generation")


class StubUserRepository:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result

    def get_user(self, id_external_user):
        return self._run("get_user", id_external_user)

    def get_user_by_id(self, id_user):
        return self._run("get_user_by_id", id_user)

    def get_user_memories(self, id_user):
        return self._run("get_user_memories", id_user)

    def create_user_memory(self, user_memory):
        return self._run("create_user_memory", user_memory)


def test_service_implements_the_service_interface():
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_get_mongo_user_delegates_to_the_repository():
    repository = StubUserRepository(result=USER)
    service = Service(repository)

    assert service.get_mongo_user(12345) is USER
    assert repository.calls == [("get_user", 12345)]


def test_get_mongo_user_propagates_value_error():
    service = Service(StubUserRepository(error=ValueError("User not found.")))

    with pytest.raises(ValueError, match="User not found."):
        service.get_mongo_user(404)


def test_get_mongo_user_wraps_unexpected_errors():
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_mongo_user(12345)


def test_get_user_memories_delegates_to_the_repository():
    memory = UserMemory(id="m1", id_user="u1", field="improvement_plan", description="text")
    repository = StubUserRepository(result=[memory])
    service = Service(repository)

    assert service.get_user_memories("u1") == [memory]
    assert repository.calls == [("get_user_memories", "u1")]


def test_get_user_memories_wraps_unexpected_errors():
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_user_memories("u1")


def test_create_user_memory_delegates_to_the_repository():
    repository = StubUserRepository()
    service = Service(repository)
    memory = UserMemory(id=None, id_user="u1", field="improvement_plan", description="text")

    assert service.create_user_memory(memory) is None
    assert repository.calls == [("create_user_memory", memory)]


def test_create_user_memory_wraps_unexpected_errors():
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.create_user_memory(UserMemory(id=None, id_user="u1", field="f", description="d"))
