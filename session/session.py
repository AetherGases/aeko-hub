from abc import ABC, abstractmethod
from session.entity import Session

class IRepository(ABC):
    @abstractmethod
    def getUserSessions(self, id_user: str) -> list[Session]:
        pass

class IService(ABC):
    @abstractmethod
    def getUserSessions(self, id_external_user) -> list[Session]:
        pass