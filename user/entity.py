from datetime import datetime


class User:
    id: str
    id_external_user: int
    role: str
    usecase: str

    def __init__(self, id: str, id_external_user: int, role: str, usecase: str):
        self.id = id
        self.id_external_user = id_external_user
        self.role = role
        self.usecase = usecase

class UserMemory:
    id: str
    id_user: str
    field: str
    description: str
    created_at: datetime | None
    expires_at: datetime | None

    def __init__(self, id: str, id_user: str, field: str, description: str, created_at: datetime | None = None, expires_at: datetime | None = None):
        self.id = id
        self.id_user = id_user
        self.field = field
        self.description = description
        self.created_at = created_at
        self.expires_at = expires_at