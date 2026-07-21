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