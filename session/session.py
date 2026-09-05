from abc import ABC, abstractmethod

from session.entity import Message, Session


class GuardrailRejectedError(Exception):
    """Raised when no reviewer of the SDK approved an answer for the turn.

    Not a failure of the run: the agents answered, and one of the two
    reviewers sent every draft back — the `Guardrail de Saida`, which asks
    whether the draft is grounded in the analyses, or the `Verificador de
    Resposta`, which asks whether it answers what was asked. Two rejections
    each is as far as either goes.

    Since SDK 3.2 that outcome arrives as `MalformedAgentOutputError` rather
    than as an empty output, and is translated into this error by
    `cmd/api/main.py` — the one file that may know the SDK's names. Either way
    there is no answer to persist and none to return, so the exchange stops
    here instead of storing a turn the user never saw.
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