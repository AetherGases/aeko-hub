"""Identifier helpers shared by the concrete repositories.

Mongo stores `_id` and every owner reference (`session.id_user`,
`user_memory.id_user`) as an `ObjectId`, while the identifiers that cross the
HTTP boundary are plain strings. Reads therefore have to match both shapes and
writes have to store the `ObjectId`.

External identifiers (`id_external_user`, `id_external_inventory`) reference
Postgres, not Mongo, and are never normalized here.
"""

from bson import ObjectId


def normalize_id(identifier):
    """The `ObjectId` for a valid identifier, or the value left untouched."""
    if isinstance(identifier, str):
        try:
            return ObjectId(identifier)
        except Exception:
            return identifier
    return identifier


def id_filter(field: str, identifier) -> dict:
    """A filter matching the identifier stored either as text or as `ObjectId`."""
    return {
        "$or": [
            {field: identifier},
            {field: normalize_id(identifier)},
        ]
    }
