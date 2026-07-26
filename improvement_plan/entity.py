from datetime import datetime

class ImprovementPlan:
    id: str | None
    id_external_gas_reduction: int | None
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime | None

    def __init__(self, id: str | None = None, id_external_gas_reduction: int | None = None, defined_problem: str = "", method: str = "", reasoning: str = "", updated_at: datetime | None = None):
        self.id = id
        self.id_external_gas_reduction = id_external_gas_reduction
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning
        self.updated_at = updated_at

    def __str__(self) -> str:
        return (
            "ImprovementPlan("
            f"id={self.id}, "
            f"id_external_gas_reduction={self.id_external_gas_reduction}, "
            f"defined_problem={self.defined_problem!r}, "
            f"method={self.method!r}, "
            f"reasoning={self.reasoning!r}, "
            f"updated_at={self.updated_at!r}"
            ")"
        )