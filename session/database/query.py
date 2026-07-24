from bson import ObjectId


def get_session_messages_count_query(id_session: str) -> tuple[dict, dict]:
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
    query = {
        "$push": {
            "messages": {
                "input": input,
                "output": output,
                "submitted_at": {"$currentDate": {"$type": "date"}},
                "llm": llm,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
        }
    }

    return query

def get_create_session_query(id_user: str) -> dict:
    query = {
        "id_user": id_user,
        "messages": []
    }

    return query