from datetime import datetime

class ImprovementPlan:
    id: str | None
    id_external_inventory: int | None
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime | None

    def __init__(self, id: str | None = None, id_external_inventory: int | None = None, defined_problem: str = "", method: str = "", reasoning: str = "", updated_at: datetime | None = None):
        """Build the plan the AI derived from a GHG inventory.

        Args:
            id: Internal identifier, `None` before the plan is stored.
            id_external_inventory: Inventory the plan was derived from.
            defined_problem: The emissions problem identified.
            method: The approach recommended to tackle it.
            reasoning: Why that approach was chosen.
            updated_at: When the plan was last revised.
        """
        self.id = id
        self.id_external_inventory = id_external_inventory
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning
        self.updated_at = updated_at

    def __str__(self) -> str:
        """Render every field, for logs and for storing the plan as a memory."""
        return (
            "ImprovementPlan("
            f"id={self.id}, "
            f"id_external_inventory={self.id_external_inventory}, "
            f"defined_problem={self.defined_problem!r}, "
            f"method={self.method!r}, "
            f"reasoning={self.reasoning!r}, "
            f"updated_at={self.updated_at!r}"
            ")"
        )
