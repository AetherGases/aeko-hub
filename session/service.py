from datetime import datetime

from session.entity import Session, Message
from session.session import IService

from user.user import IRepository as IUserRepository

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

    def send_message(self, id_session: str, input: str, id_user: str, aeko_messenger, user_repository: IUserRepository) -> Message:
        try:
            if not id_session:
                id_session = self.repository.create_session(id_user, user_repository)
                aeko_messenger.set_alter_name(True)
                
            self._validate_session_and_user_allowance(id_session, id_user)

            aeko_messenger.prepare(id_user, id_session)
            response = aeko_messenger.send_message(input)
            message = _internal_message_from_aeko_message_dto(response)
            new_name = getattr(response, "name", None)

            self.repository.save_message(id_session, message)

            if new_name:
                self.repository.update_name(id_session, new_name)
                
            return message
        except ValueError as e:
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

def _internal_message_from_aeko_message_dto(dto) -> Message:
    return Message(
        input=dto.input,
        output=dto.output,
        submitted_at=getattr(dto, "submitted_at", None) or datetime.utcnow(),
        llm=dto.llm,
        input_tokens=dto.input_tokens,
        output_tokens=dto.output_tokens
    )