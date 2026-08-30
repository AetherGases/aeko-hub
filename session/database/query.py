from datetime import datetime

from bson import ObjectId

SESSION_PROJECTION = {
    "_id": 1,
    "id_user": 1,
    "name": 1,
    "created_at": 1,
    "updated_at": 1,
}

def _normalize(identifier):
    if isinstance(identifier, str):
        try:
            return ObjectId(identifier)
        except Exception:
            return identifier
    return identifier

def get_session_filter(id_session: str) -> dict:
    return {
        "$or": [
            {"_id": id_session},
            {"_id": _normalize(id_session)},
        ]
    }

def get_session_query(id_session: str) -> tuple[dict, dict]:
    return get_session_filter(id_session), SESSION_PROJECTION

def get_user_sessions_query(id_user: str) -> tuple[dict, dict]:
    query = {
        "$or": [
            {"id_user": id_user},
            {"id_user": _normalize(id_user)},
        ]
    }

    return query, SESSION_PROJECTION

def get_session_messages_count_query(id_session: str) -> tuple[dict, dict]:
    return get_session_filter(id_session), {
        "_id": 0,
        "messages_count": {
            "$size": "$messages"
        },
    }

def get_session_messages_query(id_session: str) -> tuple[dict, dict]:
    return get_session_filter(id_session), {
        "_id": 0,
        "messages.input": 1,
        "messages.output": 1,
        "messages.submitted_at": 1,
    }

def get_save_message_query(input: str, output: str, llm: str, input_tokens: int, output_tokens: int) -> dict:
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

def get_update_name_query(name: str) -> dict:
    query = {
        "$set": {
            "name": name,
            "updated_at": datetime.utcnow()
        }
    }

    return query

def get_create_session_query(id_user: str) -> dict:
    now = datetime.utcnow()

    query = {
        "id_user": id_user,
        "name": "",
        "messages": [],
        "created_at": now,
        "updated_at": now
    }

    return query
