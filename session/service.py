from datetime import datetime

from session.entity import Session, Message
from session.session import GuardrailRejectedError, IService

from user.user import IRepository as IUserRepository

# How much of a first message becomes the session's name. The SDK stopped
# proposing one in 2.0, so the API names a conversation after what started it.
SESSION_NAME_MAX_LENGTH = 60

class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def get_user_sessions(self, id_user) -> list[Session]:
        try:
            return self.repository.get_user_sessions(id_user)
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

    def send_message(
        self,
        id_session: str,
        input: str,
        id_user: str,
        aeko_messenger_factory,
        aeko_session_factory,
        user_repository: IUserRepository,
    ) -> Message:
        try:
            is_new_session = not id_session
            if is_new_session:
                id_session = self.repository.create_session(id_user, user_repository)

            self._validate_session_and_user_allowance(id_session, id_user)

            user = user_repository.get_user_by_id(id_user)
            if not user:
                raise ValueError(f"User with id_user {id_user} does not exist.")

            # The SDK renders every memory it is handed, so the expired ones
            # have to be dropped here.
            memories = [
                memory
                for memory in user_repository.get_user_memories(id_user)
                if memory.is_valid()
            ]

            # The conversation is the session document itself: the SDK keeps
            # nothing between calls, so it is rehydrated on every request.
            session = self.repository.get_session(id_session)
            session.messages = self.repository.get_session_messages(id_session)

            messenger = aeko_messenger_factory(user, memories)
            response = messenger.send_message(input, aeko_session_factory(session))

            message = _internal_message_from_aeko_message(response.message)

            # A run the guardrail never approved answers with an empty output.
            # That is a successful run with nothing to persist.
            if not message.output:
                raise GuardrailRejectedError(
                    "The output guardrail rejected every draft. Please rephrase."
                )

            self.repository.save_message(id_session, message)

            if is_new_session:
                self.repository.update_name(id_session, _session_name_from(input))

            return message
        except (ValueError, GuardrailRejectedError) as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error sending message: {e}")

    def _validate_session_and_user_allowance(self, id_session: str, id_user: str) -> bool:
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

def _internal_message_from_aeko_message(message) -> Message:
    """Map one entry of `AekoMessageResponse.message` onto the stored turn."""
    return Message(
        input=message.input,
        output=message.output,
        submitted_at=getattr(message, "submitted_at", None) or datetime.utcnow(),
        llm=message.llm,
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens
    )

def _session_name_from(input: str) -> str:
    name = " ".join(input.split())
    if len(name) <= SESSION_NAME_MAX_LENGTH:
        return name
    return name[:SESSION_NAME_MAX_LENGTH].rstrip() + "..."
