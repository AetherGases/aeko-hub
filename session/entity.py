from datetime import datetime


class Message:
    input: str
    output: str
    submitted_at: datetime
    llm: str
    input_tokens: int
    output_tokens: int

    def __init__(self, input: str, output: str, submitted_at: datetime, llm: str, input_tokens: int, output_tokens: int):
        """Build one exchange between a user and the AI.

        Args:
            input: Text the user sent.
            output: Answer the AI returned.
            submitted_at: When the exchange happened.
            llm: Model that produced the answer.
            input_tokens: Tokens consumed by the prompt.
            output_tokens: Tokens produced in the answer.
        """
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
    messages: list
    created_at: datetime | None
    updated_at: datetime | None

    def __init__(self, id: str, id_user: str, name: str, messages: list[Message], created_at: datetime | None = None, updated_at: datetime | None = None):
        """Build a conversation between one user and the AI.

        Args:
            id: Internal session identifier.
            id_user: Internal identifier of the owner.
            name: Human-readable session name.
            messages: Exchanges recorded so far, oldest first.
            created_at: When the session was opened.
            updated_at: When it last received a message.
        """
        self.id = id
        self.id_user = id_user
        self.name = name
        self.messages = messages
        self.created_at = created_at
        self.updated_at = updated_at
