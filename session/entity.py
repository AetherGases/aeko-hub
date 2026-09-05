"""Define the domain entities for conversations and messages."""

from datetime import datetime


class Message:
    """One exchanged turn: what was asked, what was answered, and when."""

    input: str
    output: str
    submitted_at: datetime

    def __init__(self, input: str, output: str, submitted_at: datetime):
        self.input = input
        self.output = output
        self.submitted_at = submitted_at


class Session:
    id: str
    id_user: str
    name: str
    messages: list[Message]
    created_at: datetime | None
    updated_at: datetime | None

    def __init__(self, id: str, id_user: str, name: str, messages: list[Message], created_at: datetime | None = None, updated_at: datetime | None = None):
        self.id = id
        self.id_user = id_user
        self.name = name
        self.messages = messages
        self.created_at = created_at
        self.updated_at = updated_at
