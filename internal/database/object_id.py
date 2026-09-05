"""Build MongoDB identifier filters supporting strings and ObjectId values."""

from bson import ObjectId


def normalize_id(identifier):
    """Convert a valid identifier to ObjectId, leaving other values unchanged."""
    if isinstance(identifier, str):
        try:
            return ObjectId(identifier)
        except Exception:
            return identifier
    return identifier


def id_filter(field: str, identifier) -> dict:
    """Match an identifier stored as either text or ObjectId."""
    return {
        "$or": [
            {field: identifier},
            {field: normalize_id(identifier)},
        ]
    }
