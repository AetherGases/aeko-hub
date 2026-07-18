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

    def __init__(self, id: str, id_user: str, field: str, description: str):
        self.id = id
        self.id_user = id_user
        self.field = field
        self.description = description