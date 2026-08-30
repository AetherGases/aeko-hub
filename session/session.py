from abc import ABC, abstractmethod

from session.entity import Message, Session


class GuardrailRejectedError(Exception):
    """Raised when the SDK returned a run the output guardrail never approved.

    Not a failure of the run: the agents answered, the `Guardrail de Saida`
    sent every draft back, and `AekoMessageResponse.message.output` came back
    empty. There is no answer to persist and none to return, so the exchange
    stops here instead of storing a turn the user never saw.
    """


class IRepository(ABC):
    @abstractmethod
    def get_user_sessions(self, id_user: str) -> list[Session]:
        pass

    @abstractmethod
    def get_session(self, id_session: str) -> Session:
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        pass

    @abstractmethod
    def get_session_messages_count(self, id_session: str) -> int:
        pass

    @abstractmethod
    def create_session(self, id_user: str, user_repository) -> str:
        pass

    @abstractmethod
    def save_message(self, id_session: str, message: Message) -> None:
        pass

    @abstractmethod
    def update_name(self, id_session: str, name: str) -> None:
        pass

class IService(ABC):
    @abstractmethod
    def get_user_sessions(self, id_external_user) -> list[Session]:
        pass

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        pass

    @abstractmethod
    def send_message(
        self,
        id_session: str,
        input: str,
        id_user: str,
        aeko_messenger_factory,
        aeko_session_factory,
        user_repository,
    ) -> Message:
        pass

    @abstractmethod
    def _validate_session_and_user_allowance(self, id_session: str, id_user: str) -> bool:
        pass