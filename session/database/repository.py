from session.session import IRepository
from session.entity import Session, Message
from session.database import query as q

class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    def getUserSessions(self, id_user: str) -> list[Session]:
        try:
            query, projection = q.get_user_sessions_query(id_user)
            sessions_data = self.db["session"].find(query, projection)
            sessions = [session_from_data(data) for data in sessions_data]
            if not sessions:
                raise ValueError(f"No sessions found for user with id_user {id_user}.")
            return sessions
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching user sessions from database: {e}")
        
    def get_session_messages(self, id_session: str) -> list[Message]:
        try:
            query, projection = q.get_session_messages_query(id_session)
            session_data = self.db["session"].find_one(query, projection)
            if not session_data:
                raise ValueError(f"No session found with id_session {id_session}.")
            return [message_from_data(data) for data in session_data.get("messages", [])]
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching session messages from database: {e}")


def message_from_data(data: dict) -> Message:
    return Message(
        input=data.get("input_message", data.get("input", "")),
        output=data.get("output_message", data.get("output", data.get("ouput", ""))),
        submitted_at=data["submitted_at"],
        llm=data.get("llm", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0)
    )


def session_from_data(data: dict) -> Session:
    return Session(
        id=str(data["_id"]),
        id_user=str(data["id_user"]),
        name=data["name"],
        messages=data.get("messages", [])
    )