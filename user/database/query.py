from user.entity import UserMemory

def get_user_query_filter(id_external_user: int) -> dict:
    return {
        "id_external_user": id_external_user
    }

def get_user_query(id_user: str) -> tuple[dict, dict]:
    return {
        "_id": id_user
    }, {}

def get_user_memories_query(id_user: str) -> dict:
    return {
        "id_user": id_user
    }

def create_user_memory_query(user_memory: UserMemory) -> dict:
    return {
        "id_user": user_memory.id_user,
        "field": user_memory.field,
        "description": user_memory.description
    }