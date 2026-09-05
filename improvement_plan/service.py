from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import (
    IInventoryRepository,
    IRepository,
    IService,
    PREVIOUS_PLANS_FOR_CONTEXT,
)
from shared import current_id_request, record_aeko_metrics
from user.user import IService as IUserService, UserMemory

class Service(IService):
    def __init__(self, repository: IRepository, inventory_repository: IInventoryRepository):
        self.repository = repository
        # The inventory lives in another microservice, so reading it is a
        # second repository rather than a second method of the first one.
        self.inventory_repository = inventory_repository

    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        return self.repository.get_by_id_external_inventory(id_external_inventory)

    def get_last_by_id_external_unit(self, id_external_unit, limit) -> list[ImprovementPlan]:
        return self.repository.get_last_by_id_external_unit(id_external_unit, limit)

    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        return self.repository.create(improvement_plan)

    def input_inventory(
        self,
        id_external_inventory: int | None,
        id_external_unit: int | None,
        id_user: str,
        user_service: IUserService,
        aeko_inventory_analyzer_factory,
    ) -> ImprovementPlan:
        # The plan is filed against the inventory it came from and stored under
        # the unit it was written for, and the SDK never reads the database, so
        # neither id can be derived downstream.
        if id_external_inventory is None:
            raise ValueError("id_external_inventory is required to analyze an inventory.")
        if id_external_unit is None:
            raise ValueError("id_external_unit is required to analyze an inventory.")

        inventory_markdown = self.inventory_repository.get_inventory_markdown(id_external_inventory)

        # A fresh analyzer per report: `set_context()` is instance state, and a
        # shared one would carry a unit's previous report into the next run.
        aeko_inventory_analyzer = aeko_inventory_analyzer_factory()

        # Always called, even for a unit's first report: what the analysis
        # builds on is a decision of this flow, and "nothing yet" is one of its
        # answers rather than a step to skip.
        previous_plans = self.get_last_by_id_external_unit(
            id_external_unit, PREVIOUS_PLANS_FOR_CONTEXT
        )
        aeko_inventory_analyzer.set_context(_context_from(previous_plans))

        # The same identifier the request is already tracked under, and the
        # same recording the conversational flow does — an analysis is the
        # other kind of run this API pays the SDK for.
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
    """Run the analysis, and record what it cost even when it raised.

    `analyze()` raises when the coordinator never writes the plan's three
    sections, and the run it did make — every analyst before it included — is
    exactly the one worth having recorded. The exception is re-raised untouched.
    """

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
    """Map an `AekoImprovementPlan` onto the document this API persists.

    `_id` and `updated_at` are left to the database: the SDK hands back three
    content fields the coordinator actually wrote, and nothing else about the
    plan is its to decide. The unit comes from the request instead of from the
    SDK for the same reason — it reads no database, and was never told which
    unit the inventory belongs to. Since 3.x the plan arrives inside an
    `AekoAnalysisResponse`, beside what producing it cost — read off `.plan`.
    """
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
    """Render a unit's previous plans as the free-form text `set_context()` takes.

    Most recent first, which is the order they were read in: the last report is
    what this one builds on, and the one before it is what that one already
    answered. A unit with no history renders to an empty string — the call
    still happens, and the SDK reads that as no previous report.
    """
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
