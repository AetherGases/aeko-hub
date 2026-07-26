from abc import ABC, abstractmethod
from user.entity import User, UserMemory

class IRepository(ABC):
    @abstractmethod
    def get_user(self, id_external_user) -> User:
        pass

    @abstractmethod
    def get_user_by_id(self, id_user: str) -> User:
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        pass

class IService(ABC):
    @abstractmethod
    def get_mongo_user(self, id_external_user) -> User:
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        pass
