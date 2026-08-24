from datetime import datetime

from bson import ObjectId


def get_session_messages_count_query(id_session: str) -> tuple[dict, dict]:
    """Build the filter and projection that count a session's messages.

    The identifier is matched both as the raw string and as an `ObjectId`,
    because sessions created by different paths store it either way.

    Returns:
        The `(filter, projection)` pair; the projection computes
        `messages_count` server-side instead of returning the history.
    """
    normalized_id_session = id_session
    if isinstance(id_session, str):
        try:
            normalized_id_session = ObjectId(id_session)
        except Exception:
            normalized_id_session = id_session

    query = {
        "$or": [
            {"_id": id_session},
            {"_id": normalized_id_session},
        ]
    }

    return query, {
        "_id": 0,
        "messages_count": {
            "$size": "$messages"
        },
    }

def get_session_messages_query(id_session: str) -> tuple[dict, dict]:
    """Build the filter and projection that read a session's message history.

    The identifier is matched both as the raw string and as an `ObjectId`.

    Returns:
        The `(filter, projection)` pair; the projection keeps only the
        fields the API exposes.
    """
    normalized_id_session = id_session
    if isinstance(id_session, str):
        try:
            normalized_id_session = ObjectId(id_session)
        except Exception:
            normalized_id_session = id_session

    query = {
        "$or": [
            {"_id": id_session},
            {"_id": normalized_id_session},
        ]
    }

    return query, {
        "_id": 0,
        "messages.input": 1,
        "messages.output": 1,
        "messages.submitted_at": 1,
    }

def get_user_amount_of_messages_query(id_user: str, id_session: str) -> tuple[dict, dict]:
    """Build the filter and projection that count a user's messages.

    Returns:
        The `(filter, projection)` pair, matching the user identifier both
        as the raw string and as an `ObjectId`.
    """
    normalized_id_user = id_user
    if isinstance(id_user, str):
        try:
            normalized_id_user = ObjectId(id_user)
        except Exception:
            normalized_id_user = id_user

    query = {
        "$or": [
            {"id_user": id_user},
            {"id_user": normalized_id_user},
        ]
    }

    return query, {
        "count": { "$sum": 1 }
    }

def get_save_message_query(input: str, output: str, llm: str, input_tokens: int, output_tokens: int) -> dict:
    """Build the update that appends one exchange to a session.

    Pushes the message onto `messages` and bumps `updated_at` in the same
    write, so both always move together.
    """
    now = datetime.utcnow()

    query = {
        "$push": {
            "messages": {
                "input": input,
                "output": output,
                "submitted_at": now,
                "llm": llm,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
        },
        "$set": {
            "updated_at": now
        }
    }

    return query

def get_create_session_query(id_user: str) -> dict:
    """Build the document that opens an empty session for a user."""
    now = datetime.utcnow()

    query = {
        "id_user": id_user,
        "messages": [],
        "created_at": now,
        "updated_at": now
    }

    return query
