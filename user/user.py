from abc import ABC, abstractmethod
from user.entity import User, UserMemory

class IRepository(ABC):
    @abstractmethod
    def get_user(self, id_external_user) -> User:
        """Fetch a user by the external identifier the core system knows them by.

        Raises:
            ValueError: no user carries that external identifier.
        """

    @abstractmethod
    def get_user_by_id(self, id_user: str) -> User:
        """Fetch a user by our own internal identifier.

        Returns:
            The user, or `None` when the identifier matches nobody.
        """

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """List the durable facts recorded about a user.

        These are fed to the AI as company context, and expire on their own TTL.
        """

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Record one durable fact about a user."""

class IService(ABC):
    @abstractmethod
    def get_mongo_user(self, id_external_user) -> User:
        """Retrieve the profile behind an external user identifier."""

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve every memory recorded about a user."""

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Record one durable fact about a user."""
