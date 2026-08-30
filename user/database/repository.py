from user.database import query as q
from user.entity import User, UserMemory
from user.user import IRepository

class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    def get_user(self, id_external_user) -> User:
        try:
            user_data = self.db.user.find_one(q.get_user_query_filter(id_external_user))
            if not user_data:
                raise ValueError(f"User with id_external_user {id_external_user} not found.")
            return user_from_data(user_data)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching user from database: {e}")

    def get_user_by_id(self, id_user: str) -> User:
        try:
            query, projection = q.get_user_query(id_user)
            user_data = self.db.user.find_one(query, projection)
            if not user_data:
                return None
            return user_from_data(user_data)
        except Exception as e:
            raise RuntimeError(f"Error fetching user by id from database: {e}")

    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        try:
            memories_data = self.db.user_memory.find(q.get_user_memories_query(id_user))
            return [
                UserMemory(
                    id=str(memory["_id"]),
                    id_user=str(memory["id_user"]),
                    field=memory["field"],
                    description=memory["description"],
                    created_at=memory.get("created_at"),
                    expires_at=memory.get("expires_at")
                ) for memory in memories_data
            ]
        except Exception as e:
            raise RuntimeError(f"Error fetching user memories from database: {e}")

    def create_user_memory(self, user_memory: UserMemory):
        try:
            memory_data = q.create_user_memory_query(user_memory)
            self.db.user_memory.insert_one(memory_data)
            return
        except Exception as e:
            raise RuntimeError(f"Error creating user memory in database: {e}")

def user_from_data(data: dict) -> User:
    return User(
        id=str(data["_id"]),
        id_external_user=data["id_external_user"],
        role=data["role"],
        usecase=data["usecase"]
    )