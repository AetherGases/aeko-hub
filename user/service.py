from user.entity import User, UserMemory
from user.user import IService

class Service(IService):
    def __init__(self, repository):
        """Hold the repository every call below delegates its storage to."""
        self.repository = repository

    def get_mongo_user(self, id_external_user) -> User:
        """Retrieve the profile behind an external user identifier.

        Raises:
            ValueError: no user carries that external identifier.
            RuntimeError: the lookup itself failed.
        """
        try:
            return self.repository.get_user(id_external_user)
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(f"Error retrieving user: {e}")

    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve every memory recorded about a user.

        Raises:
            RuntimeError: the lookup failed.
        """
        try:
            return self.repository.get_user_memories(id_user)
        except Exception as e:
            raise RuntimeError(f"Error retrieving user memories: {e}")

    def create_user_memory(self, user_memory: UserMemory):
        """Record one durable fact about a user.

        Raises:
            RuntimeError: the write failed.
        """
        try:
            self.repository.create_user_memory(user_memory)
        except Exception as e:
            raise RuntimeError(f"Error creating user memory: {e}")
