"""Build MongoDB filters and documents for conversations and messages."""

from datetime import datetime

from internal.database.object_id import id_filter, normalize_id

SESSION_PROJECTION = {
    "_id": 1,
    "id_user": 1,
    "name": 1,
    "created_at": 1,
    "updated_at": 1,
}

def get_session_filter(id_session: str) -> dict:
    """Match a session identifier stored as text or ObjectId."""
    return id_filter("_id", id_session)

def get_session_query(id_session: str) -> tuple[dict, dict]:
    """Build the filter and projection for one session."""
    return get_session_filter(id_session), SESSION_PROJECTION

def get_user_sessions_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection for a user's sessions."""
    return id_filter("id_user", id_user), SESSION_PROJECTION

def get_session_messages_count_query(id_session: str) -> tuple[dict, dict]:
    """Build a projection that counts messages in the matching session."""
    return get_session_filter(id_session), {
        "_id": 0,
        "messages_count": {
            "$size": "$messages"
        },
    }

def get_session_messages_query(id_session: str) -> tuple[dict, dict]:
    """Build a projection for the matching session's message history."""
    return get_session_filter(id_session), {
        "_id": 0,
        "messages.input": 1,
        "messages.output": 1,
        "messages.submitted_at": 1,
    }

def get_save_message_query(input: str, output: str, submitted_at: datetime | None = None) -> dict:
    """Build an update that appends a message and uses its timestamp for the session."""
    now = submitted_at or datetime.utcnow()

    return {
        "$push": {
            "messages": {
                "input": input,
                "output": output,
                "submitted_at": now
            }
        },
        "$set": {
            "updated_at": now
        }
    }

def get_update_name_query(name: str) -> dict:
    """Build an update for the session name and current modification time."""
    return {
        "$set": {
            "name": name,
            "updated_at": datetime.utcnow()
        }
    }

def get_create_session_query(id_user: str) -> dict:
    """Build an empty session document with a normalized user identifier and timestamps."""
    now = datetime.utcnow()

    return {
        "id_user": normalize_id(id_user),
        "name": "",
        "messages": [],
        "created_at": now,
        "updated_at": now
    }
