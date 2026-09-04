from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IService as IImprovementPlanService

from inventory_analysis.inventory_analysis import IService, IRepository
from inventory_analysis.inventory_markdown import inventory_markdown_from_xlsx
from shared import current_id_request, record_aeko_metrics
from user.user import IService as IUserService, UserMemory

class Service(IService):
    def __init__(self, repository: IRepository):
        self.repository = repository

    def input_inventory(
        self,
        s3: str,
        id_user: str,
        id_external_inventory_4context: int | None,
        user_service: IUserService,
        improvement_plan_service: IImprovementPlanService,
        aeko_inventory_analyzer_factory,
    ) -> str:
        # The plan is filed against the inventory it came from, and the SDK
        # never reads the database, so the id cannot be derived downstream.
        if id_external_inventory_4context is None:
            raise ValueError("id_external_inventory_4context is required to analyze an inventory.")

        inventory_bytes = self.repository.get_excel_bytes(s3)
        inventory_markdown = inventory_markdown_from_xlsx(inventory_bytes)

        # A fresh analyzer per report: `set_context()` is instance state, and a
        # shared one would carry a company's previous report into the next run.
        aeko_inventory_analyzer = aeko_inventory_analyzer_factory()

        inventory_data = self.repository.get_external_inventory_context(id_external_inventory_4context)
        if inventory_data:
            aeko_inventory_analyzer.set_context(_context_from(inventory_data))

        # The same identifier the request is already tracked under, and the
        # same recording the conversational flow does — an analysis is the
        # other kind of run this API pays the SDK for.
        analysis = _analyze(
            aeko_inventory_analyzer,
            inventory_markdown,
            id_external_inventory_4context,
            current_id_request(),
        )

        record_aeko_metrics(analysis.aeko_metrics)

        improvement_plan = improvement_plan_from_aeko_plan(analysis.plan)

        improvement_plan_service.create(improvement_plan)
        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=str(improvement_plan)
            )
        )

        return str(improvement_plan)

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


def improvement_plan_from_aeko_plan(plan) -> ImprovementPlan:
    """Map an `AekoImprovementPlan` onto the document this API persists.

    `_id` and `updated_at` are left to the database: the SDK hands back three
    content fields the coordinator actually wrote, and nothing else about the
    plan is its to decide. Since 3.x the plan arrives inside an
    `AekoAnalysisResponse`, beside what producing it cost — read off `.plan`.
    """
    return ImprovementPlan(
        id=None,
        id_external_inventory=plan.id_external_inventory,
        defined_problem=plan.defined_problem,
        method=plan.method,
        reasoning=plan.reasoning,
        updated_at=None
    )

def _context_from(inventory_data: dict) -> str:
    """Render the previous report as the free-form text 2.0 takes as context."""
    return "\n".join(f"{field}: {value}" for field, value in inventory_data.items())
