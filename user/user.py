"""Define service and repository contracts for users and memories."""

from abc import ABC, abstractmethod
from user.entity import User, UserMemory

class IRepository(ABC):
    @abstractmethod
    def get_user(self, id_external_user) -> User:
        """Retrieve a user by external identifier."""
        pass

    @abstractmethod
    def get_user_by_id(self, id_user: str) -> User:
        """Retrieve a user by internal identifier, returning None when absent."""
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        pass

class IService(ABC):
    @abstractmethod
    def get_mongo_user(self, id_external_user) -> User:
        """Retrieve the stored user matching an external identifier."""
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        pass
