from bson import ObjectId


def get_user_sessions_query(id_user: str) -> tuple[dict, dict]:
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
        "name": 1,
        "id_user": 1,
    }

def get_session_messages_query(id_session: str) -> tuple[dict, dict]:
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