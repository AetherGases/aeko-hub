def get_user_query_filter(id_external_user: int) -> dict:
    return {
        "id_external_user": id_external_user
    }

def get_user_query(id_user: str) -> tuple[dict, dict]:
    return {
        "_id": id_user
    }, {}
