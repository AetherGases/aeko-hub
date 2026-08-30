"""Unit tests for the session service business rules.

The service orchestrates the session repository and the two SDK factories it
receives by injection. Every collaborator is replaced by a local double, so
the rules under test are the service ones: session creation and naming, the
message allowance, the ownership check, the documents handed to the SDK, and
the persistence of an approved turn.
"""

import inspect
from datetime import datetime, timedelta

import pytest

from session.entity import Message, Session
from session.service import Service
from session.session import GuardrailRejectedError, IService
from user.entity import User, UserMemory

ID_SESSION = "s1"
ID_USER = "u1"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

USER = User(id=ID_USER, id_external_user=12345, role="analyst", usecase="report_generation")


class StubTurn:
    """One entry of `session.messages`, as `AekoMessageResponse.message`."""

    def __init__(self, input, output, submitted_at=None, llm="fake-llm", input_tokens=1, output_tokens=2):
        self.input = input
        self.output = output
        self.submitted_at = submitted_at
        self.llm = llm
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class StubResponse:
    def __init__(self, message, approved=True, agents_called=None, guardrail_retries=0):
        self.message = message
        self.id_session = ID_SESSION
        self.id_user = ID_USER
        self.approved = approved
        self.agents_called = agents_called or ["FAQ"]
        self.guardrail_retries = guardrail_retries


class StubMessenger:
    def __init__(self, user, memories, turn=None, approved=True, error=None):
        self.user = user
        self.memories = memories
        self.turn = turn
        self.approved = approved
        self.error = error
        self.sent = []

    def send_message(self, message, session):
        self.sent.append((message, session))
        if self.error is not None:
            raise self.error
        turn = self.turn or StubTurn(
            input=message,
            output=f"echo: {message}" if self.approved else "",
        )
        return StubResponse(turn, approved=self.approved)


class StubMessengerFactory:
    """Stands in for the factory the lifespan publishes on `app.state`."""

    def __init__(self, turn=None, approved=True, error=None):
        self.turn = turn
        self.approved = approved
        self.error = error
        self.built = []

    def __call__(self, user, memories):
        messenger = StubMessenger(user, memories, self.turn, self.approved, self.error)
        self.built.append(messenger)
        return messenger

    @property
    def last(self):
        return self.built[-1]


class StubSessionDocument:
    """Stands in for the `AekoSession` the factory builds from the entity."""

    def __init__(self, session):
        self.id = session.id
        self.id_user = session.id_user
        self.name = session.name
        self.messages = list(session.messages)


class StubSessionFactory:
    def __init__(self):
        self.built = []

    def __call__(self, session):
        document = StubSessionDocument(session)
        self.built.append(document)
        return document

    @property
    def last(self):
        return self.built[-1]


class FakeSessionRepository:
    def __init__(self, sessions=None, messages=None, messages_count=0, error=None):
        self.sessions = sessions or {ID_SESSION: Session(id=ID_SESSION, id_user=ID_USER, name="", messages=[])}
        self.messages = messages or {}
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
        return self.messages.get(id_session, [])

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
    def __init__(self, user=USER, memories=None):
        self.user = user
        self.memories = list(memories or [])

    def get_user(self, id_external_user):
        return self.user

    def get_user_by_id(self, id_user):
        return self.user

    def get_user_memories(self, id_user):
        return self.memories

    def create_user_memory(self, user_memory):
        self.memories.append(user_memory)


def build_service(**kwargs):
    repository = FakeSessionRepository(**kwargs)
    return Service(repository), repository


def send(service, id_session=ID_SESSION, input="hi", id_user=ID_USER,
         messengers=None, sessions=None, users=None):
    return service.send_message(
        id_session,
        input,
        id_user,
        messengers or StubMessengerFactory(),
        sessions or StubSessionFactory(),
        users or StubUserRepository(),
    )


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
    assert "aeko_messenger_factory" in interface
    assert "aeko_session_factory" in interface
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
# send_message — the exchange
# ---------------------------------------------------------------------------
def test_send_message_returns_the_exchange():
    service, _ = build_service()

    message = send(service, input="What is scope 3?")

    assert isinstance(message, Message)
    assert message.input == "What is scope 3?"
    assert message.output == "echo: What is scope 3?"
    assert message.llm == "fake-llm"
    assert (message.input_tokens, message.output_tokens) == (1, 2)


def test_send_message_reads_the_turn_out_of_the_response_message():
    """v2 returns the turn nested under `.message`, not flattened on the response."""
    messengers = StubMessengerFactory(
        turn=StubTurn(input="hi", output="ho", llm="fast,slow", input_tokens=7, output_tokens=9)
    )
    service, _ = build_service()

    message = send(service, messengers=messengers)

    assert (message.llm, message.input_tokens, message.output_tokens) == ("fast,slow", 7, 9)


def test_send_message_stamps_the_exchange_when_the_turn_carries_no_time():
    service, _ = build_service()

    assert isinstance(send(service).submitted_at, datetime)


def test_send_message_keeps_the_submission_time_the_sdk_produced():
    messengers = StubMessengerFactory(turn=StubTurn(input="hi", output="ho", submitted_at=SUBMITTED_AT))
    service, _ = build_service()

    assert send(service, messengers=messengers).submitted_at == SUBMITTED_AT


def test_send_message_persists_the_exchange():
    service, repository = build_service()

    message = send(service)

    assert repository.saved == [(ID_SESSION, message)]


# ---------------------------------------------------------------------------
# send_message — what the SDK is handed
# ---------------------------------------------------------------------------
def test_send_message_builds_the_messenger_for_the_asking_user():
    messengers = StubMessengerFactory()
    service, _ = build_service()

    send(service, messengers=messengers)

    assert messengers.last.user is USER


def test_send_message_hands_over_the_session_and_the_text():
    messengers, sessions = StubMessengerFactory(), StubSessionFactory()
    service, _ = build_service()

    send(service, input="What is scope 3?", messengers=messengers, sessions=sessions)

    text, document = messengers.last.sent[0]
    assert text == "What is scope 3?"
    assert document is sessions.last
    assert document.id == ID_SESSION


def test_send_message_rehydrates_the_conversation_into_the_session():
    stored = Message(
        input="Summarize this session.",
        output="Here is the summary.",
        submitted_at=SUBMITTED_AT,
        llm="fake-llm",
        input_tokens=10,
        output_tokens=20,
    )
    sessions = StubSessionFactory()
    service, _ = build_service(messages={ID_SESSION: [stored]})

    send(service, sessions=sessions)

    assert [turn.input for turn in sessions.last.messages] == ["Summarize this session."]


def test_send_message_hands_over_only_the_memories_that_are_still_valid():
    valid = UserMemory(id="m1", id_user=ID_USER, field="preferred_language", description="pt-BR")
    expiring = UserMemory(
        id="m2", id_user=ID_USER, field="soon", description="still valid",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    expired = UserMemory(
        id="m3", id_user=ID_USER, field="stale", description="gone",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    messengers = StubMessengerFactory()
    service, _ = build_service()

    send(service, messengers=messengers, users=StubUserRepository(memories=[valid, expiring, expired]))

    assert [memory.field for memory in messengers.last.memories] == ["preferred_language", "soon"]


def test_send_message_rejects_an_unknown_user():
    service, _ = build_service()

    with pytest.raises(ValueError, match="does not exist"):
        send(service, users=StubUserRepository(user=None))


# ---------------------------------------------------------------------------
# send_message — session creation and naming
# ---------------------------------------------------------------------------
def test_send_message_creates_a_session_when_none_is_given():
    messengers, sessions = StubMessengerFactory(), StubSessionFactory()
    service, repository = build_service()
    users = StubUserRepository()

    send(service, id_session="", messengers=messengers, sessions=sessions, users=users)

    assert repository.created_for == [(ID_USER, users)]
    assert sessions.last.id == "session-2"


def test_send_message_names_a_brand_new_session_after_its_first_message():
    service, repository = build_service()

    send(service, id_session="", input="How do I cut boiler emissions?")

    assert repository.names == {"session-2": "How do I cut boiler emissions?"}


def test_send_message_shortens_a_long_first_message_into_the_session_name():
    service, repository = build_service()

    send(service, id_session="", input="scope 1 " * 40)

    name = repository.names["session-2"]
    assert len(name) <= 63
    assert name.endswith("...")


def test_send_message_does_not_rename_an_existing_session():
    service, repository = build_service()

    send(service)

    assert repository.names == {}


# ---------------------------------------------------------------------------
# send_message — the guardrail
# ---------------------------------------------------------------------------
def test_send_message_raises_when_the_guardrail_rejected_every_draft():
    service, _ = build_service()

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))


def test_send_message_persists_nothing_when_the_guardrail_rejected_every_draft():
    service, repository = build_service()

    with pytest.raises(GuardrailRejectedError):
        send(service, messengers=StubMessengerFactory(approved=False))

    assert repository.saved == []


# ---------------------------------------------------------------------------
# send_message — the allowance rules
# ---------------------------------------------------------------------------
def test_send_message_rejects_a_session_that_reached_the_message_limit():
    service, _ = build_service(messages_count=50)

    with pytest.raises(ValueError, match="maximum number of messages"):
        send(service)


def test_send_message_accepts_a_session_below_the_message_limit():
    service, repository = build_service(messages_count=49)

    send(service)

    assert len(repository.saved) == 1


def test_send_message_rejects_a_session_owned_by_another_user():
    service, _ = build_service()

    with pytest.raises(ValueError, match="not allowed"):
        send(service, id_user="someone-else", users=StubUserRepository(
            user=User(id="someone-else", id_external_user=999, role="r", usecase="u")
        ))


def test_send_message_propagates_a_value_error_from_the_repository():
    service, _ = build_service(error=ValueError("User with id_user u1 does not exist."))

    with pytest.raises(ValueError, match="does not exist"):
        send(service, id_session="")


def test_send_message_wraps_unexpected_errors():
    service, _ = build_service(error=OSError("mongo down"))

    with pytest.raises(RuntimeError, match="mongo down"):
        send(service)


def test_send_message_wraps_an_sdk_failure():
    service, _ = build_service()

    with pytest.raises(RuntimeError, match="gemini down"):
        send(service, messengers=StubMessengerFactory(error=OSError("gemini down")))


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
