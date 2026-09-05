"""Build MongoDB filters and documents for improvement plans."""

from datetime import datetime

from improvement_plan.entity import ImprovementPlan


PREVIOUS_PLANS_SORT = [("updated_at", -1)]


def get_by_id_external_inventory_query(id_external_inventory: int) -> tuple[dict, dict]:
    """Build the filter and projection for a plan associated with an external inventory."""
    return {
        "id_external_inventory": id_external_inventory,
    }, {}


def get_last_by_id_external_unit_query(id_external_unit: int, limit: int) -> tuple[dict, dict, list, int]:
    """Build the filter and projection for plans belonging to an external unit."""
    return {
        "id_external_unit": id_external_unit,
    }, {}, list(PREVIOUS_PLANS_SORT), limit


def create_improvement_plan_query(improvement_plan: ImprovementPlan) -> dict:
    """Build a plan document with the persistence timestamp."""
    document = {
        "id_external_inventory": improvement_plan.id_external_inventory,
        "id_external_unit": improvement_plan.id_external_unit,
        "defined_problem": improvement_plan.defined_problem,
        "method": improvement_plan.method,
        "reasoning": improvement_plan.reasoning,
        "updated_at": improvement_plan.updated_at or datetime.utcnow(),
    }

    return {field: value for field, value in document.items() if value is not None}
