from abc import ABC, abstractmethod
from session.entity import Session, Message

class IRepository(ABC):
    @abstractmethod
    def getUserSessions(self, id_user: str) -> list[Session]:
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        pass

class IService(ABC):
    @abstractmethod
    def getUserSessions(self, id_external_user) -> list[Session]:
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        pass