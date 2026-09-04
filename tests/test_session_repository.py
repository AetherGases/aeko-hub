"""Unit tests for the concrete session repository and its query helpers.

`session.service.Service` calls `get_user_sessions`, `get_session_messages`,
`get_session_messages_count`, `get_session`, `create_session`, `save_message`
and `update_name`. Every one of them must exist on the concrete repository and
be declared by `session.session.IRepository`.
"""

from datetime import datetime

import pytest
from bson import ObjectId

from session.database import query as q
from session.database.repository import Repository, message_from_data, session_from_data
from session.entity import Message, Session
from session.session import IRepository
from tests.mongo_doubles import StubCollection, StubDatabase

ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

SERVICE_METHODS = [
    "get_user_sessions",
    "get_session",
    "get_session_messages",
    "get_session_messages_count",
    "create_session",
    "save_message",
    "update_name",
]

SESSION_DOCUMENT = {
    "_id": ID_SESSION,
    "id_user": ID_USER,
    "name": "Weekly emissions review",
    "created_at": SUBMITTED_AT,
    "updated_at": SUBMITTED_AT,
}

MESSAGE_DOCUMENT = {
    "input": "Summarize this session.",
    "output": "Here is the summary.",
    "submitted_at": SUBMITTED_AT,
}


class StubUserRepository:
    def __init__(self, user=None):
        self.user = user
        self.calls = []

    def get_user_by_id(self, id_user):
        self.calls.append(id_user)
        return self.user


def build_repository(session=None):
    database = StubDatabase(session=session or StubCollection())
    return Repository(database), database


# ---------------------------------------------------------------------------
# Interface compatibility
# ---------------------------------------------------------------------------
def test_repository_implements_the_repository_interface():
    assert issubclass(Repository, IRepository)


def test_repository_has_no_unimplemented_abstract_method():
    assert Repository.__abstractmethods__ == frozenset()


def test_repository_can_be_instantiated():
    assert isinstance(Repository("db"), IRepository)


@pytest.mark.parametrize("method", SERVICE_METHODS)
def test_repository_exposes_every_method_called_by_the_service(method):
    assert callable(getattr(Repository, method, None))


@pytest.mark.parametrize("method", SERVICE_METHODS)
def test_interface_declares_every_method_called_by_the_service(method):
    assert callable(getattr(IRepository, method, None))


# ---------------------------------------------------------------------------
# get_user_sessions
# ---------------------------------------------------------------------------
def test_get_user_sessions_maps_every_document():
    repository, _ = build_repository(StubCollection(find_result=[SESSION_DOCUMENT]))

    sessions = repository.get_user_sessions(ID_USER)

    assert len(sessions) == 1
    assert isinstance(sessions[0], Session)
    assert sessions[0].id == ID_SESSION
    assert sessions[0].name == "Weekly emissions review"


def test_get_user_sessions_queries_by_the_user_identifier():
    collection = StubCollection(find_result=[SESSION_DOCUMENT])
    repository, _ = build_repository(collection)

    repository.get_user_sessions(ID_USER)

    query, _ = collection.call_args("find")[0]
    assert {"id_user": ID_USER} in query["$or"]


def test_get_user_sessions_raises_value_error_when_there_is_none():
    repository, _ = build_repository(StubCollection(find_result=[]))

    with pytest.raises(ValueError, match=ID_USER):
        repository.get_user_sessions(ID_USER)


def test_get_user_sessions_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_user_sessions(ID_USER)


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------
def test_get_session_returns_the_session_entity():
    repository, _ = build_repository(StubCollection(find_one_result=SESSION_DOCUMENT))

    session = repository.get_session(ID_SESSION)

    assert isinstance(session, Session)
    assert session.id == ID_SESSION
    assert session.id_user == ID_USER


def test_get_session_raises_value_error_when_not_found():
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session(ID_SESSION)


def test_get_session_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session(ID_SESSION)


# ---------------------------------------------------------------------------
# get_session_messages
# ---------------------------------------------------------------------------
def test_get_session_messages_maps_every_embedded_message():
    document = {"messages": [MESSAGE_DOCUMENT]}
    repository, _ = build_repository(StubCollection(find_one_result=document))

    messages = repository.get_session_messages(ID_SESSION)

    assert len(messages) == 1
    assert isinstance(messages[0], Message)
    assert messages[0].input == "Summarize this session."
    assert messages[0].output == "Here is the summary."
    assert messages[0].submitted_at == SUBMITTED_AT


def test_get_session_messages_returns_an_empty_list_when_there_is_none():
    repository, _ = build_repository(StubCollection(find_one_result={"messages": []}))

    assert repository.get_session_messages(ID_SESSION) == []


def test_get_session_messages_raises_value_error_when_the_session_is_unknown():
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session_messages(ID_SESSION)


def test_get_session_messages_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session_messages(ID_SESSION)


# ---------------------------------------------------------------------------
# get_session_messages_count
# ---------------------------------------------------------------------------
def test_get_session_messages_count_returns_the_size():
    repository, _ = build_repository(StubCollection(find_one_result={"messages_count": 3}))

    assert repository.get_session_messages_count(ID_SESSION) == 3


def test_get_session_messages_count_raises_value_error_when_not_found():
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session_messages_count(ID_SESSION)


def test_get_session_messages_count_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session_messages_count(ID_SESSION)


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------
def test_create_session_returns_the_new_identifier():
    collection = StubCollection(inserted_id=ObjectId(ID_SESSION))
    repository, _ = build_repository(collection)

    assert repository.create_session(ID_USER, StubUserRepository(user=object())) == ID_SESSION


def test_create_session_stores_the_owner_and_an_empty_history():
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.create_session(ID_USER, StubUserRepository(user=object()))

    document = collection.call_args("insert_one")[0][0]
    assert document["id_user"] == ObjectId(ID_USER)
    assert document["messages"] == []


def test_create_session_raises_value_error_for_an_unknown_user():
    repository, _ = build_repository(StubCollection())

    with pytest.raises(ValueError, match=ID_USER):
        repository.create_session(ID_USER, StubUserRepository(user=None))


def test_create_session_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create_session(ID_USER, StubUserRepository(user=object()))


# ---------------------------------------------------------------------------
# save_message / update_name
# ---------------------------------------------------------------------------
def test_save_message_pushes_the_message_into_the_session():
    collection = StubCollection()
    repository, _ = build_repository(collection)
    message = Message(
        input="What is scope 3?",
        output="Indirect emissions.",
        submitted_at=SUBMITTED_AT,
    )

    repository.save_message(ID_SESSION, message)

    query, update = collection.call_args("update_one")[0]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]
    assert update["$push"]["messages"]["input"] == "What is scope 3?"
    assert update["$push"]["messages"]["output"] == "Indirect emissions."
    assert update["$push"]["messages"]["submitted_at"] == SUBMITTED_AT
    assert "ouput" not in update["$push"]["messages"]


def test_a_pushed_turn_is_only_the_exchange_and_its_time():
    """3.1 moved what a turn cost onto the request's `aeko_metrics`; the three
    fields it used to carry are no longer written here."""
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.save_message(
        ID_SESSION, Message(input="a", output="b", submitted_at=SUBMITTED_AT)
    )

    _, update = collection.call_args("update_one")[0]
    assert set(update["$push"]["messages"]) == {"input", "output", "submitted_at"}


def test_save_message_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))
    message = Message(input="a", output="b", submitted_at=SUBMITTED_AT)

    with pytest.raises(RuntimeError, match="boom"):
        repository.save_message(ID_SESSION, message)


def test_update_name_sets_the_new_name():
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.update_name(ID_SESSION, "Scope 3 questions")

    query, update = collection.call_args("update_one")[0]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]
    assert update["$set"]["name"] == "Scope 3 questions"


def test_update_name_wraps_database_failures_in_runtime_error():
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.update_name(ID_SESSION, "new name")


# ---------------------------------------------------------------------------
# mappers
# ---------------------------------------------------------------------------
def test_message_from_data_reads_the_stored_field_names():
    message = message_from_data(MESSAGE_DOCUMENT)

    assert (message.input, message.output) == ("Summarize this session.", "Here is the summary.")
    assert message.submitted_at == SUBMITTED_AT


def test_message_from_data_ignores_what_a_turn_used_to_carry():
    """Documents written before 3.1 still hold `llm` and the token counts. They
    are not read back: the cost of a run lives in `aeko_metrics` now, and a
    turn that quoted its own would be a second account of it."""
    message = message_from_data({**MESSAGE_DOCUMENT, "llm": "m", "input_tokens": 1, "output_tokens": 2})

    assert set(vars(message)) == {"input", "output", "submitted_at"}


def test_message_from_data_ignores_the_response_field_names():
    """`input_message`/`output_message` belong to the HTTP response model.

    Mongo never stores them, so the mapper reads the collection field names
    only and a document without them is a programming error, not a default.
    """
    with pytest.raises(KeyError):
        message_from_data({"input_message": "in", "output_message": "out", "submitted_at": SUBMITTED_AT})


def test_message_from_data_ignores_the_legacy_misspelled_output():
    with pytest.raises(KeyError):
        message_from_data({"input": "in", "ouput": "out", "submitted_at": SUBMITTED_AT})


def test_session_from_data_maps_the_document():
    session = session_from_data(SESSION_DOCUMENT)

    assert (session.id, session.id_user, session.name) == (ID_SESSION, ID_USER, "Weekly emissions review")
    assert session.messages == []


def test_session_from_data_maps_embedded_messages_into_entities():
    """`Session.messages` is typed `list[Message]`, so the mapper has to
    convert the embedded documents instead of forwarding the raw dicts."""
    session = session_from_data({**SESSION_DOCUMENT, "messages": [MESSAGE_DOCUMENT]})

    assert len(session.messages) == 1
    assert isinstance(session.messages[0], Message)
    assert session.messages[0].input == "Summarize this session."
    assert session.messages[0].output == "Here is the summary."
    assert session.messages[0].submitted_at == SUBMITTED_AT


def test_session_from_data_renders_an_object_id_owner_as_text():
    session = session_from_data({**SESSION_DOCUMENT, "_id": ObjectId(ID_SESSION), "id_user": ObjectId(ID_USER)})

    assert (session.id, session.id_user) == (ID_SESSION, ID_USER)


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------
def test_session_filter_accepts_both_string_and_object_id():
    query = q.get_session_filter(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]


def test_session_filter_accepts_an_identifier_that_is_already_an_object_id():
    object_id = ObjectId(ID_SESSION)

    assert q.get_session_filter(object_id)["$or"] == [{"_id": object_id}, {"_id": object_id}]


def test_session_filter_keeps_identifiers_that_are_not_object_ids():
    query = q.get_session_filter("not-an-object-id")

    assert query["$or"] == [{"_id": "not-an-object-id"}, {"_id": "not-an-object-id"}]


def test_get_user_sessions_query_projects_the_session_fields():
    query, projection = q.get_user_sessions_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert {"id_user": ObjectId(ID_USER)} in query["$or"]
    assert projection["name"] == 1
    assert projection["id_user"] == 1


def test_get_session_query_projects_the_session_fields():
    query, projection = q.get_session_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["name"] == 1


def test_get_session_messages_query_projects_the_message_fields():
    query, projection = q.get_session_messages_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["messages.input"] == 1
    assert projection["messages.output"] == 1
    assert projection["messages.submitted_at"] == 1
    assert "messages.ouput" not in projection


def test_get_session_messages_count_query_projects_the_size():
    query, projection = q.get_session_messages_count_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["messages_count"] == {"$size": "$messages"}


def test_get_save_message_query_stores_the_turns_own_timestamp():
    """The SDK stamps the turn; the API stores what it was handed."""
    update = q.get_save_message_query("in", "out", SUBMITTED_AT)

    assert update["$push"]["messages"]["submitted_at"] == SUBMITTED_AT
    assert update["$set"]["updated_at"] == SUBMITTED_AT


def test_get_save_message_query_pushes_and_timestamps():
    update = q.get_save_message_query("in", "out")

    assert update["$push"]["messages"]["input"] == "in"
    assert update["$push"]["messages"]["output"] == "out"
    assert "ouput" not in update["$push"]["messages"]
    assert update["$set"]["updated_at"] == update["$push"]["messages"]["submitted_at"]


def test_get_create_session_query_starts_an_empty_named_session():
    document = q.get_create_session_query(ID_USER)

    assert document["id_user"] == ObjectId(ID_USER)
    assert document["messages"] == []
    assert document["name"] == ""
    assert document["created_at"] == document["updated_at"]


def test_get_create_session_query_keeps_an_owner_that_is_not_an_object_id():
    assert q.get_create_session_query("u1")["id_user"] == "u1"


def test_get_update_name_query_sets_the_name():
    update = q.get_update_name_query("Scope 3 questions")

    assert update["$set"]["name"] == "Scope 3 questions"
    assert isinstance(update["$set"]["updated_at"], datetime)
