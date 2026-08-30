"""Unit tests for the session service business rules.

The service orchestrates the session repository and the messenger it receives
by injection. Both collaborators are replaced by local doubles so the rules
under test are the service ones: session creation, the message allowance, the
ownership check and the persistence of the exchange.
"""

import inspect
from datetime import datetime

import pytest

from session.entity import Message, Session
from session.service import Service
from session.session import IService

ID_SESSION = "s1"
ID_USER = "u1"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

MESSAGE = Message(
    input="Summarize this session.",
    output="Here is the summary.",
    submitted_at=SUBMITTED_AT,
    llm="fake-llm",
    input_tokens=10,
    output_tokens=20,
)


class StubResponse:
    """The exchange returned by the messenger, mapped into a `Message`."""

    def __init__(self, input, output, llm="fake-llm", input_tokens=1, output_tokens=2, **extra):
        self.input = input
        self.output = output
        self.llm = llm
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        for key, value in extra.items():
            setattr(self, key, value)


class StubMessenger:
    def __init__(self, response=None):
        self.response = response
        self.alter_name = None
        self.prepared_with = None
        self.sent = []

    def set_alter_name(self, alter_name):
        self.alter_name = alter_name

    def prepare(self, id_user, id_session):
        self.prepared_with = (id_user, id_session)

    def send_message(self, input):
        self.sent.append(input)
        return self.response or StubResponse(input=input, output=f"echo: {input}")


class FakeSessionRepository:
    def __init__(self, sessions=None, messages_count=0, error=None):
        self.sessions = sessions or {ID_SESSION: Session(id=ID_SESSION, id_user=ID_USER, name="", messages=[])}
        self.messages_count = messages_count
        self.error = error
        self.saved = []
        self.names = {}
        self.created_for = []

    def _guard(self):
        if self.error is not None:
            raise self.error

    def get_user_sessions(self, id_user):
        self._guard()
        return [session for session in self.sessions.values() if session.id_user == id_user]

    def get_session(self, id_session):
        self._guard()
        session = self.sessions.get(id_session)
        if session is None:
            raise ValueError(f"No session found with id_session {id_session}.")
        return session

    def get_session_messages(self, id_session):
        self._guard()
        return []

    def get_session_messages_count(self, id_session):
        self._guard()
        return self.messages_count

    def create_session(self, id_user, user_repository):
        self._guard()
        self.created_for.append((id_user, user_repository))
        id_session = f"session-{len(self.sessions) + 1}"
        self.sessions[id_session] = Session(id=id_session, id_user=id_user, name="", messages=[])
        return id_session

    def save_message(self, id_session, message):
        self._guard()
        self.saved.append((id_session, message))

    def update_name(self, id_session, name):
        self._guard()
        self.names[id_session] = name


class StubUserRepository:
    pass


def build_service(**kwargs):
    repository = FakeSessionRepository(**kwargs)
    return Service(repository), repository


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_service_implements_the_service_interface():
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_send_message_signature_matches_the_interface():
    interface = inspect.signature(IService.send_message).parameters
    implementation = inspect.signature(Service.send_message).parameters

    assert list(interface) == list(implementation)
    assert "user_repository" in interface


# ---------------------------------------------------------------------------
# get_user_sessions / get_session_messages
# ---------------------------------------------------------------------------
def test_get_user_sessions_delegates_to_the_repository():
    service, _ = build_service()

    sessions = service.get_user_sessions(ID_USER)

    assert [session.id for session in sessions] == [ID_SESSION]


def test_get_user_sessions_propagates_value_error():
    service, _ = build_service(error=ValueError("No sessions found."))

    with pytest.raises(ValueError, match="No sessions found."):
        service.get_user_sessions(ID_USER)


def test_get_user_sessions_wraps_unexpected_errors():
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_user_sessions(ID_USER)


def test_get_session_messages_delegates_to_the_repository():
    service, _ = build_service()

    assert service.get_session_messages(ID_SESSION) == []


def test_get_session_messages_propagates_value_error():
    service, _ = build_service(error=ValueError("Invalid session."))

    with pytest.raises(ValueError, match="Invalid session."):
        service.get_session_messages(ID_SESSION)


def test_get_session_messages_wraps_unexpected_errors():
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_session_messages(ID_SESSION)


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------
def test_send_message_returns_the_exchange():
    service, _ = build_service()

    message = service.send_message(ID_SESSION, "What is scope 3?", ID_USER, StubMessenger(), StubUserRepository())

    assert isinstance(message, Message)
    assert message.input == "What is scope 3?"
    assert message.output == "echo: What is scope 3?"
    assert message.llm == "fake-llm"
    assert (message.input_tokens, message.output_tokens) == (1, 2)


def test_send_message_stamps_the_exchange_with_a_submission_time():
    service, _ = build_service()

    message = service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())

    assert isinstance(message.submitted_at, datetime)


def test_send_message_keeps_a_submission_time_provided_by_the_response():
    messenger = StubMessenger(response=StubResponse(input="hi", output="ho", submitted_at=SUBMITTED_AT))
    service, _ = build_service()

    message = service.send_message(ID_SESSION, "hi", ID_USER, messenger, StubUserRepository())

    assert message.submitted_at == SUBMITTED_AT


def test_send_message_prepares_the_messenger_with_the_session_and_user():
    messenger = StubMessenger()
    service, _ = build_service()

    service.send_message(ID_SESSION, "hi", ID_USER, messenger, StubUserRepository())

    assert messenger.prepared_with == (ID_USER, ID_SESSION)
    assert messenger.sent == ["hi"]


def test_send_message_persists_the_exchange():
    service, repository = build_service()

    message = service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())

    assert repository.saved == [(ID_SESSION, message)]


def test_send_message_creates_a_session_when_none_is_given():
    messenger = StubMessenger()
    service, repository = build_service()
    user_repository = StubUserRepository()

    service.send_message("", "hi", ID_USER, messenger, user_repository)

    assert repository.created_for == [(ID_USER, user_repository)]
    assert messenger.alter_name is True
    assert messenger.prepared_with == (ID_USER, "session-2")


def test_send_message_keeps_the_existing_session_untouched():
    messenger = StubMessenger()
    service, repository = build_service()

    service.send_message(ID_SESSION, "hi", ID_USER, messenger, StubUserRepository())

    assert repository.created_for == []
    assert messenger.alter_name is None


def test_send_message_renames_the_session_when_the_response_carries_a_name():
    messenger = StubMessenger(response=StubResponse(input="hi", output="ho", name="Scope 3 questions"))
    service, repository = build_service()

    service.send_message(ID_SESSION, "hi", ID_USER, messenger, StubUserRepository())

    assert repository.names == {ID_SESSION: "Scope 3 questions"}


def test_send_message_does_not_rename_the_session_without_a_name():
    service, repository = build_service()

    service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())

    assert repository.names == {}


def test_send_message_rejects_a_session_that_reached_the_message_limit():
    service, _ = build_service(messages_count=50)

    with pytest.raises(ValueError, match="maximum number of messages"):
        service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())


def test_send_message_accepts_a_session_below_the_message_limit():
    service, repository = build_service(messages_count=49)

    service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())

    assert len(repository.saved) == 1


def test_send_message_rejects_a_session_owned_by_another_user():
    service, _ = build_service()

    with pytest.raises(ValueError, match="not allowed"):
        service.send_message(ID_SESSION, "hi", "someone-else", StubMessenger(), StubUserRepository())


def test_send_message_propagates_a_value_error_from_the_repository():
    service, _ = build_service(error=ValueError("User with id_user u1 does not exist."))

    with pytest.raises(ValueError, match="does not exist"):
        service.send_message("", "hi", ID_USER, StubMessenger(), StubUserRepository())


def test_send_message_wraps_unexpected_errors():
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.send_message(ID_SESSION, "hi", ID_USER, StubMessenger(), StubUserRepository())


# ---------------------------------------------------------------------------
# _validate_session_and_user_allowance
# ---------------------------------------------------------------------------
def test_validation_returns_true_for_an_allowed_user():
    service, _ = build_service()

    assert service._validate_session_and_user_allowance(ID_SESSION, ID_USER) is True


def test_validation_wraps_unexpected_errors():
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        service._validate_session_and_user_allowance(ID_SESSION, ID_USER)
