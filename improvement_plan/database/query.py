from improvement_plan.entity import ImprovementPlan


def get_by_id_external_inventory_query(id_external_inventory: int) -> tuple[dict, dict]:
	"""Build the filter and projection that match a plan by its inventory.

	Returns:
		The `(filter, projection)` pair; the empty projection returns the
		whole document.
	"""
	return {
		"id_external_inventory": id_external_inventory,
	}, {}


def create_improvement_plan_query(improvement_plan: ImprovementPlan) -> dict:
	"""Build the document that stores one improvement plan."""
	return {
		"id_external_inventory": improvement_plan.id_external_inventory,
		"defined_problem": improvement_plan.defined_problem,
		"method": improvement_plan.method,
		"reasoning": improvement_plan.reasoning,
		"updated_at": improvement_plan.updated_at,
	}
