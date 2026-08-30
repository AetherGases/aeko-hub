from datetime import datetime


class Message:
    input: str
    output: str
    submitted_at: datetime
    llm: str
    input_tokens: int
    output_tokens: int

    def __init__(self, input: str, output: str, submitted_at: datetime, llm: str, input_tokens: int, output_tokens: int):
        self.input = input
        self.output = output
        self.submitted_at = submitted_at
        self.llm = llm
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


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