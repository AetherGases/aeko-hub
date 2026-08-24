from datetime import datetime, timedelta

from user.entity import UserMemory

USER_MEMORY_TTL_DAYS = 12

def get_user_query_filter(id_external_user: int) -> dict:
    """Build the filter that matches a user by their external identifier."""
    return {
        "id_external_user": id_external_user
    }

def get_user_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection that match a user by internal id.

    Returns:
        The `(filter, projection)` pair; the empty projection returns the
        whole document.
    """
    return {
        "_id": id_user
    }, {}

def get_user_memories_query(id_user: str) -> dict:
    """Build the filter that matches every memory belonging to a user."""
    return {
        "id_user": id_user
    }

def create_user_memory_query(user_memory: UserMemory) -> dict:
    """Build the document that stores one user memory.

    Timestamps left unset are filled in here: `created_at` becomes now, and
    `expires_at` becomes `USER_MEMORY_TTL_DAYS` after it.
    """
    created_at = user_memory.created_at or datetime.utcnow()
    expires_at = user_memory.expires_at or (created_at + timedelta(days=USER_MEMORY_TTL_DAYS))

    return {
        "id_user": user_memory.id_user,
        "field": user_memory.field,
        "description": user_memory.description,
        "created_at": created_at,
        "expires_at": expires_at
    }
