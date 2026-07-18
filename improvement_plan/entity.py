from datetime import datetime

class Improvement_plan:
    id: str
    id_external_gas_reduction: int
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime

    def __init__(self, id: str, id_external_gas_reduction: int, defined_problem: str, method: str, reasoning: str, updated_at: datetime):
        self.id = id
        self.id_external_gas_reduction = id_external_gas_reduction
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning
        self.updated_at = updated_at