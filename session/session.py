from abc import ABC, abstractmethod

from session.entity import Message, Session


class IRepository(ABC):
    @abstractmethod
    def get_user_sessions(self, id_user: str) -> list[Session]:
        pass

    @abstractmethod
    def get_session_messages_count(self, id_session: str) -> list[Message]:
        pass

    @abstractmethod
    def save_message(self, id_session: str, message: Message) -> None:
        pass

class IService(ABC):
    @abstractmethod
    def get_user_sessions(self, id_external_user) -> list[Session]:
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        pass

    @abstractmethod
    def send_message(self, id_session: str, input: str, id_user: str, aeko_messenger) -> Message:
        pass

    @abstractmethod
    def _validate_session_and_user_allowance(self, id_session: str, id_user: str) -> bool:
        pass