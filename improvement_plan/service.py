"""Coordinate domain operations for improvement plans."""

from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import (
    IInventoryRepository,
    IRepository,
    IService,
    PREVIOUS_PLANS_FOR_CONTEXT,
)
from internal.shared import current_id_request, record_aeko_metrics
from user.user import IService as IUserService, UserMemory

class Service(IService):
    def __init__(self, repository: IRepository, inventory_repository: IInventoryRepository):
        self.repository = repository

        self.inventory_repository = inventory_repository

    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        return self.repository.get_by_id_external_inventory(id_external_inventory)

    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        """Retrieve the latest plans for an external unit, up to the requested limit."""
        return self.repository.get_last_by_id_external_unit(id_external_unit, limit)

    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        return self.repository.create(improvement_plan)

    def input_inventory(
        self,
        id_external_inventory: int | None,
        id_external_unit: int | None,
        id_user: str,
        user_service: IUserService,
        aeko_inventory_analyzer_factory,
    ) -> ImprovementPlan:
        """Analyze an inventory with previous plans as context, then store its plan and user memory."""
        if id_external_inventory is None:
            raise ValueError("id_external_inventory is required to analyze an inventory.")
        if id_external_unit is None:
            raise ValueError("id_external_unit is required to analyze an inventory.")

        inventory_markdown = self.inventory_repository.get_inventory_markdown(id_external_inventory)

        aeko_inventory_analyzer = aeko_inventory_analyzer_factory()

        previous_plans = self.get_last_by_id_external_unit(
            id_external_unit, PREVIOUS_PLANS_FOR_CONTEXT
        )
        aeko_inventory_analyzer.set_context(_context_from(previous_plans))

        analysis = _analyze(
            aeko_inventory_analyzer,
            inventory_markdown,
            id_external_inventory,
            current_id_request(),
        )

        record_aeko_metrics(analysis.aeko_metrics)

        improvement_plan = self.create(
            improvement_plan_from_aeko_plan(analysis.plan, id_external_unit)
        )

        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=str(improvement_plan)
            )
        )

        return improvement_plan

def _analyze(analyzer, inventory_markdown: str, id_external_inventory: int, id_request: str):
    """Analyze an inventory and record metrics attached to any raised exception."""

    try:
        return analyzer.analyze(
            inventory_markdown,
            id_external_inventory=id_external_inventory,
            id_request=id_request,
        )
    except Exception as exc:
        record_aeko_metrics(getattr(exc, "aeko_metrics", None))
        raise


def improvement_plan_from_aeko_plan(plan, id_external_unit: int) -> ImprovementPlan:
    """Map an SDK plan and external unit identifier to a domain plan for persistence."""
    return ImprovementPlan(
        id=None,
        id_external_inventory=plan.id_external_inventory,
        id_external_unit=id_external_unit,
        defined_problem=plan.defined_problem,
        method=plan.method,
        reasoning=plan.reasoning,
        updated_at=None
    )

def _context_from(previous_plans: list[ImprovementPlan]) -> str:
    """Render previous plans in retrieval order as analysis context, or empty text when absent."""
    return "\n\n".join(
        "\n".join(
            [
                f"Relatório anterior (inventário {plan.id_external_inventory}, atualizado em {plan.updated_at}):",
                f"Problema identificado: {plan.defined_problem}",
                f"Método: {plan.method}",
                f"Justificativa: {plan.reasoning}",
            ]
        )
        for plan in previous_plans
    )
