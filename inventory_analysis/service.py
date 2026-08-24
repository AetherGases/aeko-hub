from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IService as IImprovementPlanService

from inventory_analysis.inventory_analysis import IService, IRepository
from user.user import IService as IUserService, UserMemory

class Service(IService):
    def __init__(self, repository: IRepository):
        """Hold the repository the inventory and its context are loaded from."""
        self.repository = repository

    def input_inventory(
        self,
        s3: str,
        id_user: str,
        id_external_inventory_4context: int | None,
        user_service: IUserService,
        improvement_plan_service: IImprovementPlanService,
        aeko_inventory_analyzer_factory,
        build_gas_reduction_context,
    ) -> str:
        """Run a GHG inventory through the AI and persist the plan it returns.

        Loads the inventory, optionally primes the analyzer with a previous
        report, analyzes it, then stores the plan both as an improvement plan
        and as a user memory.

        Args:
            s3: Where the inventory file lives.
            id_user: Internal identifier of whoever submitted it.
            id_external_inventory_4context: Previous inventory to use as
                context. `None` for a company's first report.
            user_service: Records the resulting plan as a user memory.
            improvement_plan_service: Persists the plan itself.
            aeko_inventory_analyzer_factory: Builds an analyzer for this run.
            build_gas_reduction_context: Renders the previous report as the
                plain text `set_context()` expects.

        Returns:
            The improvement plan, as text.
        """
        inventory_bytes = self.repository.get_excel_bytes(s3)

        # TODO: `analyze()` expects the inventory rendered as Markdown (a table
        # is the natural shape), not the raw XLSX bytes stored in S3. The API
        # owns that conversion; it is not wired up yet.
        inventory_markdown = _inventory_to_markdown(inventory_bytes)

        # An analyzer per request: `set_context()` mutates instance state, so a
        # shared one would carry one company's previous report into the next.
        aeko_inventory_analyzer = aeko_inventory_analyzer_factory()

        if id_external_inventory_4context is not None:
            inventory_data = self.repository.get_external_inventory_context(id_external_inventory_4context)
            context = build_gas_reduction_context(inventory_data)
            aeko_inventory_analyzer.set_context(context)

        report = aeko_inventory_analyzer.analyze(inventory_markdown)

        improvement_plan = improvement_plan_from_aeko_response(report, id_external_inventory_4context)
        improvement_plan_service.create(improvement_plan)
        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=report.answer
            )
        )

        return report.answer

def _inventory_to_markdown(inventory_bytes: bytes) -> str:
    """Render the stored inventory as the Markdown `analyze()` expects."""
    # TODO: render the XLSX workbook as a Markdown table. Until then the object
    # is assumed to already hold text.
    if isinstance(inventory_bytes, bytes):
        return inventory_bytes.decode("utf-8", errors="replace")
    return str(inventory_bytes)

def improvement_plan_from_aeko_response(response, id_external_inventory: int | None) -> ImprovementPlan:
    """Turn one SDK `InventoryAnalysisResponse` into the plan we store."""
    # `InventoryAnalysisResponse` returns the whole plan as one block of text.
    # TODO: the SDK does not break it into problem/method/reasoning yet, so the
    # same answer fills all three until it does.
    return ImprovementPlan(
        id=None,
        id_external_inventory=id_external_inventory,
        defined_problem=response.answer,
        method=response.answer,
        reasoning=response.answer,
        updated_at=None
    )
