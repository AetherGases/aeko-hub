from datetime import datetime

class ImprovementPlan:
    id: str | None
    id_external_inventory: int | None
    id_external_unit: int | None
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime | None

    def __init__(self, id: str | None = None, id_external_inventory: int | None = None, id_external_unit: int | None = None, defined_problem: str = "", method: str = "", reasoning: str = "", updated_at: datetime | None = None):
        self.id = id
        self.id_external_inventory = id_external_inventory
        # The unit the inventory belongs to, which is what ties a plan to the
        # ones written for the same place before it. The SDK never reads the
        # database, so it cannot carry this: it is filled in by this API.
        self.id_external_unit = id_external_unit
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning
        self.updated_at = updated_at

    def __str__(self) -> str:
        return (
            "ImprovementPlan("
            f"id={self.id}, "
            f"id_external_inventory={self.id_external_inventory}, "
            f"id_external_unit={self.id_external_unit}, "
            f"defined_problem={self.defined_problem!r}, "
            f"method={self.method!r}, "
            f"reasoning={self.reasoning!r}, "
            f"updated_at={self.updated_at!r}"
            ")"
        )