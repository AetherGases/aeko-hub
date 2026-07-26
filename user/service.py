from user.user import IService
from user.entity import User, UserMemory

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def get_mongo_user(self, id_external_user) -> User:
        try:
            return self.repository.get_user(id_external_user)
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(f"Error retrieving user: {e}")

    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        try:
            return self.repository.get_user_memories(id_user)
        except Exception as e:
            raise RuntimeError(f"Error retrieving user memories: {e}")

    def create_user_memory(self, user_memory: UserMemory):
        try:
            self.repository.create_user_memory(user_memory)
        except Exception as e:
            raise RuntimeError(f"Error creating user memory: {e}")