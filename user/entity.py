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

    def is_valid(self, now: datetime | None = None) -> bool:
        """Whether this memory may still be shown to the agents.

        Deciding it is the API's job: the SDK renders every memory it is
        handed, `expires_at` included, so an expired row would go on being
        remembered until something here filters it out.
        """
        if self.expires_at is None:
            return True
        return self.expires_at > (now or datetime.utcnow())