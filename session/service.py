from datetime import datetime

from session.entity import Session, Message
from session.session import GuardrailRejectedError, IService

from user.user import IRepository as IUserRepository

MAX_SESSION_NAME_LENGTH = 60

class Service(IService):
    def __init__(self, repository):
        """Hold the repository every call below delegates its storage to."""
        self.repository = repository

    def get_user_sessions(self, id_user) -> list[Session]:
        """List every session belonging to a user.

        Raises:
            ValueError: the user owns no sessions.
            RuntimeError: the lookup itself failed.
        """
        try:
            return self.repository.get_user_sessions(id_user)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error retrieving user sessions: {e}")

    def get_session_messages(self, id_session: str) -> list[Message]:
        """Retrieve the message history stored for a session.

        Raises:
            ValueError: the session identifier is invalid or unknown.
            RuntimeError: the lookup itself failed.
        """
        try:
            return self.repository.get_session_messages(id_session)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error retrieving session messages: {e}")

    def send_message(self, id_session: str, input: str, id_user: str, aeko_messenger_factory, user_repository: IUserRepository) -> Message:
        """Run one conversational turn through the AI and persist it.

        Creates the session when `id_session` is empty, rehydrates the prior
        turns into the SDK, sends the message and stores the exchange. A
        brand new session is named after this first input.

        Args:
            id_session: Session to continue. Falsy creates a new one.
            input: Message text from the user.
            id_user: Internal identifier of the sender.
            aeko_messenger_factory: Builds a messenger for this request.
            user_repository: Source of the profile and memories sent as context.

        Returns:
            The persisted exchange.

        Raises:
            ValueError: the session is capped or does not belong to this user.
            GuardrailRejectedError: the AI produced no approved answer.
            RuntimeError: anything else went wrong along the way.
        """
        try:
            is_new_session = not id_session
            if is_new_session:
                id_session = self.repository.create_session(id_user, user_repository)

            self._validate_session_and_user_allowance(id_session, id_user)

            # A messenger per request, never a shared one: the SDK keeps session
            # memory in process-wide state, so the history this worker needs is
            # rehydrated from our own storage on every call.
            aeko_messenger = aeko_messenger_factory()
            aeko_messenger.prepare(
                session_id=id_session,
                user_info=_build_user_info(id_user, user_repository),
                history=_history_from_messages(self.repository.get_session_messages(id_session)),
            )

            response = aeko_messenger.send_message(input)

            # A rejected answer is a successful run, not an exception: there is
            # simply nothing to persist or hand back.
            if not response.approved or not response.answer:
                raise GuardrailRejectedError(guardrail_retries=response.guardrail_retries)

            message = _internal_message_from_aeko_response(input, response)
            self.repository.save_message(id_session, message)

            if is_new_session:
                self.repository.update_name(id_session, _session_name_from_input(input))

            return message
        except (ValueError, GuardrailRejectedError) as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error sending message: {e}")

    def _validate_session_and_user_allowance(self, id_session: str, id_user: str) -> bool:
        """Check the session is under its message cap and owned by this user.

        Returns:
            `True` when both checks pass.

        Raises:
            ValueError: the cap was reached, or the session belongs elsewhere.
            RuntimeError: the checks themselves failed.
        """
        try:
            messages_amount = self.repository.get_session_messages_count(id_session)
            if messages_amount >= 50:
                raise ValueError("Session has reached the maximum number of messages allowed.")

            session = self.repository.get_session(id_session)
            if session.id_user != id_user:
                raise ValueError("User is not allowed to access this session.")
            return True
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error validating session and user allowance: {e}")

def _internal_message_from_aeko_response(input: str, response) -> Message:
    """Turn one SDK `MessageResponse` into the exchange we store.

    `llm`, `input_tokens` and `output_tokens` are not part of
    `MessageResponse` yet; they are read defensively so the fields start
    being persisted the moment the SDK exposes them.
    """
    return Message(
        input=input,
        output=response.answer,
        submitted_at=datetime.utcnow(),
        llm=getattr(response, "llm", ""),
        input_tokens=getattr(response, "input_tokens", 0),
        output_tokens=getattr(response, "output_tokens", 0),
    )

def _build_user_info(id_user: str, user_repository: IUserRepository) -> str:
    """Free-form company context forwarded to every agent by `prepare()`.

    Combines the user's role and use case with every memory recorded about
    them. The richer this is, the more grounded the AI's answers.
    """
    facts = []

    user = user_repository.get_user_by_id(id_user)
    if user is not None:
        facts.append(f"role: {user.role}")
        facts.append(f"usecase: {user.usecase}")

    for memory in user_repository.get_user_memories(id_user) or []:
        facts.append(f"{memory.field}: {memory.description}")

    return "\n".join(facts)

def _history_from_messages(messages) -> list[dict]:
    """Prior turns in the `{"role", "content"}` shape `prepare()` accepts.

    Each stored exchange expands into two turns — the user's input and the
    AI's output — oldest first, as the SDK requires.
    """
    history = []
    for message in messages or []:
        history.append({"role": "user", "content": message.input})
        history.append({"role": "assistant", "content": message.output})
    return history

def _session_name_from_input(input: str) -> str:
    """Name a freshly created session after its opening message.

    The SDK has no naming call, so the first input is what we have. Long
    inputs are collapsed to a single line and truncated with an ellipsis.
    """
    name = " ".join((input or "").split())
    if not name:
        return "New session"
    if len(name) > MAX_SESSION_NAME_LENGTH:
        name = name[: MAX_SESSION_NAME_LENGTH - 1].rstrip() + "…"
    return name
