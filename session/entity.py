class Message:
    input: str
    output: str
    submitted_at: str
    llm: str
    input_tokens: int
    output_tokens: int

    def __init__(self, input: str, output: str, submitted_at: str, llm: str, input_tokens: int, output_tokens: int):
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

    def __init__(self, id: str, id_user: str, name: str, messages: list[Message]):
        self.id = id
        self.id_user = id_user
        self.name = name
        self.messages = messages