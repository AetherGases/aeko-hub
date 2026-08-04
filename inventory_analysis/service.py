    
from inventory_analysis.inventory_analysis import IService
from io import BytesIO
import requests
import boto3

# Mocks ai sdk
from unittest.mock import MagicMock
import sys

mock_aeko = MagicMock()

mock_aeko.AekoMessenger = MagicMock()

sys.modules["aeko_sdk"] = mock_aeko

from aeko_sdk import AekoInventoryAnalyzer # type: ignore
from aeko_sdk import AekoGasReductionDTO # type: ignore
from aeko_sdk import AekoInventoryAnalysisDTO # type: ignore

s3_client = boto3.client("s3")

class Service(IService):
    def input_inventory(self, s3: str, id_user: str, id_inventory: int, user_service: IUserService, id_department: int, id_external_user_owner: int, id_external_user_validator: int, id_external_input_inventory: int) -> str:
        inventory_bytes = get_pdf_bytes(s3, id_user)

        aeko_inventory_analyzer = AekoInventoryAnalyzer()
        context = None
        id_external_inventory = id_inventory
        if id_inventory is not None:
            aeko_inventory_analyzer.set_context(context)
        else:
            inventory_data = requests.get(f"https://api.example.com/inventory/{id_inventory}").json()
            context = AekoGasReductionDTO(**inventory_data)
            aeko_inventory_analyzer.set_context(context)

        analysis_result, inventory, projections = aeko_inventory_analyzer.analyze(inventory_bytes)

        if id_external_inventory is None:
            id_external_inventory = requests.post("https://api.example.com/inventory", json=inventory.__dict__).json()["id"]

        improvement_plan = improvement_plan_from_aeko_inventory_analysis_dto(analysis_result)
        improvement_plan.id_external_inventory = id_external_inventory

        self.repository.create(improvement_plan)
        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=improvement_plan.__str__()
            )
        )


def get_pdf_bytes(bucket: str, key: str) -> bytes:
    response = s3_client.get_object(
        Bucket=bucket,
        Key=key
    )

    return response["Body"].read()

def improvement_plan_from_aeko_inventory_analysis_dto(aeko_inventory_analysis_dto: AekoinventoryAnalysisDTO) -> ImprovementPlan:
    improvement_plan = ImprovementPlan(
        defined_problem=aeko_inventory_analysis_dto.defined_problem,
        method=aeko_inventory_analysis_dto.method,
        reasoning=aeko_inventory_analysis_dto.reasoning,
        updated_at=datetime.now()
    )
    return improvement_plan