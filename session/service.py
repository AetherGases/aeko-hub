from session.session import IService
from session.entity import Session, Message

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def getUserSessions(self, id_user) -> list[Session]:
        try:
            return self.repository.getUserSessions(id_user)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error retrieving user sessions: {e}")
        
    def get_session_messages(self, id_session: str) -> list[Message]:
        try:
            return self.repository.get_session_messages(id_session)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error retrieving session messages: {e}")