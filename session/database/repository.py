from session.session import IRepository
from session.entity import Session
from session.database import query as q

class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    def getUserSessions(self, id_user: str) -> list[Session]:
        try:
            query, projection = q.get_user_sessions_query(id_user)
            sessions_data = self.db["session"].find(query, projection)
            sessions = [from_data(data) for data in sessions_data]
            if not sessions:
                raise ValueError(f"No sessions found for user with id_user {id_user}.")
            return sessions
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching user sessions from database: {e}")


def from_data(data: dict) -> Session:
    return Session(
        id=str(data["_id"]),
        id_user=str(data["id_user"]),
        name=data["name"],
        messages=data.get("messages", [])
    )