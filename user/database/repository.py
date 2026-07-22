from user.user import IRepository
from user.entity import User
from user.database import query as q

class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    def get_user(self, id_external_user) -> User:
        try:
            user_data = self.db.user.find_one(q.get_user_query_filter(id_external_user))
            if not user_data:
                raise ValueError(f"User with id_external_user {id_external_user} not found.")
            return User(
                id=str(user_data["_id"]),
                id_external_user=user_data["id_external_user"],
                role=user_data["role"],
                usecase=user_data["usecase"]
            )
        except Exception as e:
            raise RuntimeError(f"Error fetching user from database: {e}")