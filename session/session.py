from abc import ABC, abstractmethod

from session.entity import Message, Session


class GuardrailRejectedError(Exception):
    """The SDK ran successfully but its output guardrail approved no draft.

    Not an SDK failure: `MessageResponse.answer` comes back empty with
    `approved is False` after the retry cap. There is no answer to persist or
    return, so the request cannot be fulfilled.
    """

    def __init__(self, message: str = "The output guardrail rejected every draft.", guardrail_retries: int = 0):
        """Build the error.

        Args:
            message: Text handed to the caller as the failure detail.
            guardrail_retries: How many drafts the guardrail sent back.
        """
        super().__init__(message)
        self.guardrail_retries = guardrail_retries


class IRepository(ABC):
    @abstractmethod
    def get_user_sessions(self, id_user: str) -> list[Session]:
        """List every session belonging to a user.

        Raises:
            ValueError: the user owns no sessions.
        """

    @abstractmethod
    def get_session_messages_count(self, id_session: str) -> list[Message]:
        """Count the messages already exchanged in a session.

        Used to enforce the per-session message cap without loading the
        whole history.
        """

    @abstractmethod
    def save_message(self, id_session: str, message: Message) -> None:
        """Append one exchange to a session's history."""

class IService(ABC):
    @abstractmethod
    def get_user_sessions(self, id_external_user) -> list[Session]:
        """List every session belonging to a user."""

    @abstractmethod
    def get_session_messages(self, id_session: str) -> list[Message]:
        """Retrieve the message history stored for a session."""

    @abstractmethod
    def send_message(self, id_session: str, input: str, id_user: str, aeko_messenger_factory, user_repository) -> Message:
        """Run one conversational turn through the AI and persist it.

        Args:
            id_session: Session to continue. Falsy creates a new one.
            input: Message text from the user.
            id_user: Internal identifier of the sender.
            aeko_messenger_factory: Builds a messenger for this request.
            user_repository: Source of the profile and memories sent as context.

        Raises:
            GuardrailRejectedError: the AI produced no approved answer.
        """

    @abstractmethod
    def _validate_session_and_user_allowance(self, id_session: str, id_user: str) -> bool:
        """Check the session is under its message cap and owned by this user.

        Raises:
            ValueError: either check failed.
        """
