from improvement_plan.entity import ImprovementPlan


def get_by_id_external_gas_reduction_query(id_external_gas_reduction: int) -> tuple[dict, dict]:
	return {
		"id_external_gas_reduction": id_external_gas_reduction,
	}, {}


def create_improvement_plan_query(improvement_plan: ImprovementPlan) -> dict:
	return {
		"id_external_gas_reduction": improvement_plan.id_external_gas_reduction,
		"defined_problem": improvement_plan.defined_problem,
		"method": improvement_plan.method,
		"reasoning": improvement_plan.reasoning,
		"updated_at": improvement_plan.updated_at,
	}
