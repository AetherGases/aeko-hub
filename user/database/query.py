"""Build MongoDB filters and documents for users and memories."""

from datetime import datetime, timedelta

from internal.database.object_id import id_filter, normalize_id
from user.entity import UserMemory

USER_MEMORY_TTL_DAYS = 12


def get_user_query_filter(id_external_user: int) -> dict:
    """Build the user filter for an external identifier."""
    return {
        "id_external_user": id_external_user
    }

def get_user_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection for an internal user identifier."""
    return id_filter("_id", id_user), {}

def get_user_memories_query(id_user: str) -> dict:
    """Build the filter for memories belonging to a user."""
    return id_filter("id_user", id_user)

def create_user_memory_query(user_memory: UserMemory) -> dict:
    """Build a user memory document with normalized identifiers."""
    created_at = user_memory.created_at or datetime.utcnow()
    expires_at = user_memory.expires_at or (created_at + timedelta(days=USER_MEMORY_TTL_DAYS))

    return {
        "id_user": normalize_id(user_memory.id_user),
        "field": user_memory.field,
        "description": user_memory.description,
        "created_at": created_at,
        "expires_at": expires_at
    }
