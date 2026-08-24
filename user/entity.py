from datetime import datetime


class User:
    id: str
    id_external_user: int
    role: str
    usecase: str

    def __init__(self, id: str, id_external_user: int, role: str, usecase: str):
        """Build a user profile.

        Args:
            id: Our own internal identifier.
            id_external_user: The identifier the core system knows them by.
            role: Role assigned to the user.
            usecase: User use case or profile category.
        """
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
        """Build one durable fact about a user, fed to the AI as context.

        Args:
            id: Internal identifier, `None` before the memory is stored.
            id_user: Internal identifier of the user it belongs to.
            field: What kind of fact this is, e.g. `improvement_plan`.
            description: The fact itself.
            created_at: When it was recorded. Defaults to write time.
            expires_at: When it stops being relevant. Defaults to the TTL.
        """
        self.id = id
        self.id_user = id_user
        self.field = field
        self.description = description
        self.created_at = created_at
        self.expires_at = expires_at
