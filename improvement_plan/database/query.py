from improvement_plan.entity import ImprovementPlan


def get_by_id_external_inventory_query(id_external_inventory: int) -> tuple[dict, dict]:
	return {
		"id_external_inventory": id_external_inventory,
	}, {}


def create_improvement_plan_query(improvement_plan: ImprovementPlan) -> dict:
	return {
		"id_external_inventory": improvement_plan.id_external_inventory,
		"defined_problem": improvement_plan.defined_problem,
		"method": improvement_plan.method,
		"reasoning": improvement_plan.reasoning,
		"updated_at": improvement_plan.updated_at,
	}
