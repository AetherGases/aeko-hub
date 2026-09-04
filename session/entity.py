from datetime import datetime


class Message:
    """One exchanged turn: what was asked, what was answered, and when.

    What the turn *cost* used to live here too. Since SDK 3.1 it does not: the
    model that served it and the tokens it burned are reported per agent
    invocation on the request's own tracking, which the `aeko_metrics` domain
    stores. Keeping a rolled-up copy on the turn as well would be two records
    of one fact, free to drift apart and impossible to tell apart once they had.
    """

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