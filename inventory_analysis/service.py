import sys
from unittest.mock import MagicMock

from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IService as IImprovementPlanService

from inventory_analysis.inventory_analysis import IService, IRepository
from user.user import IService as IUserService, UserMemory

# Mocks ai sdk

mock_aeko = MagicMock()

mock_aeko.AekoMessenger = MagicMock()

sys.modules["aeko_sdk"] = mock_aeko

from aeko_sdk import AekoInventoryAnalyzer # type: ignore
from aeko_sdk import AekoGasReductionDTO # type: ignore
from aeko_sdk import AekoInventoryImprovementPlanDTO # type: ignore

class Service(IService):
    def __init__(self, repository: IRepository):
        self.repository = repository

    def input_inventory(self, s3: str, id_user: str, id_external_inventory_4context: int | None, user_service: IUserService, improvement_plan_service: IImprovementPlanService) -> str:
        inventory_bytes = self.repository.get_excel_bytes(s3)

        aeko_inventory_analyzer = AekoInventoryAnalyzer()
        if id_external_inventory_4context is not None:
            inventory_data = self.repository.get_external_inventory_context(id_external_inventory_4context)
            context = AekoGasReductionDTO(**inventory_data)
            aeko_inventory_analyzer.set_context(context)

        inventory = aeko_inventory_analyzer.analyze(inventory_bytes)
        improvement_plan = inventory.generate_improvement_plan()

        improvement_plan_service.create(improvement_plan_from_aeko_dto(improvement_plan))
        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=str(improvement_plan)
            )
        )

        return str(improvement_plan)

def improvement_plan_from_aeko_dto(dto: AekoInventoryImprovementPlanDTO) -> ImprovementPlan:
    return ImprovementPlan(
        id=None,
        id_external_inventory=dto.id_external_inventory,
        defined_problem=dto.defined_problem,
        method=dto.method,
        reasoning=dto.reasoning,
        updated_at=None
    )