from improvement_plan.improvement_plan import IService
from improvement_plan.entity import ImprovementPlan

from io import BytesIO
import boto3
from datetime import datetime
import requests

s3_client = boto3.client("s3")

from io import BytesIO

from reportlab.platypus import SimpleDocTemplate, Paragraph

from user.user import IService as IUserService
from user.entity import UserMemory

# Mocks ai sdk
from unittest.mock import MagicMock
import sys

mock_aeko = MagicMock()

mock_aeko.AekoMessenger = MagicMock()

sys.modules["aeko_sdk"] = mock_aeko

from aeko_sdk import AekoReportAnalyzer # type: ignore
from aeko_sdk import AekoReportBuilder # type: ignore

from aeko_sdk import AekoGasReductionDTO # type: ignore
from aeko_sdk import AekoReportAnalysisDTO # type: ignore


class Service(IService):
    def __init__(self, repository):
        self.repository = repository

    def get_by_id_external_gas_reduction(self, id_external_gas_reduction) -> ImprovementPlan:
        return self.repository.get_by_id_external_gas_reduction(id_external_gas_reduction)

    def input_report(self, s3: str, id_user: str, id_gas_reduction: int, user_service: IUserService, id_department: int, id_external_user_owner: int, id_external_user_validator: int, id_external_input_report: int) -> str:
        report_bytes = get_pdf_bytes(s3, id_user)

        aeko_report_analyzer = AekoReportAnalyzer()
        context = None
        id_external_gas_reduction = id_gas_reduction
        if id_gas_reduction is None:
            aeko_report_analyzer.set_context(context)
        else:
            gas_reduction_data = requests.get(f"https://api.example.com/gas_reduction/{id_gas_reduction}").json()
            context = AekoGasReductionDTO(**gas_reduction_data)
            aeko_report_analyzer.set_context(context)

        analysis_result, gas_reduction, projections = aeko_report_analyzer.analyze(report_bytes)

        if id_external_gas_reduction is None:
            id_external_gas_reduction = requests.post("https://api.example.com/gas_reduction", json=gas_reduction.__dict__).json()["id"]

        improvement_plan = improvement_plan_from_aeko_report_analysis_dto(analysis_result)
        improvement_plan.id_external_gas_reduction = id_external_gas_reduction

        self.repository.create(improvement_plan)
        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=id_user,
                field="improvement_plan",
                description=improvement_plan.__str__()
            )
        )


        # build output report
        aeko_report_builder = AekoReportBuilder()
        aeko_report_builder.set_result(analysis_result)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer)

        aeko_report_builder.build(doc)

        buffer.seek(0)

        time = datetime.now().strftime("%Y%m%d%H%M")

        id_storage_file = requests.post(
            "https://api.example.com/storage",
            json={
                "name": aeko_report_builder.get_report_name(),
                "path": f"s3://{s3}/reports/output/{id_user}/{time}.pdf",
            }
        ).json()["id"]

        requests.post(
            "https://api.example.com/reports",
            json={
                "name": aeko_report_builder.get_report_name(),
                "description": aeko_report_builder.get_report_description(),
                "type": "output",
                "id_storage_file": id_storage_file,
                "id_department": id_department,
                "id_owner_employee": id_external_user_owner,
                "id_validator_employee": id_external_user_validator,
                "id_input_report": id_external_input_report
            }
        )

        s3_client.put_object(
            Bucket=s3,
            Key=f"reports/output/{id_user}/{time}.pdf",
            Body=buffer,
            ContentType="application/pdf"
        )

        return f"s3://{s3}/reports/output/{id_user}/{time}.pdf"
        

def get_pdf_bytes(bucket: str, key: str) -> bytes:
    response = s3_client.get_object(
        Bucket=bucket,
        Key=key
    )

    return response["Body"].read()

def improvement_plan_from_aeko_report_analysis_dto(aeko_report_analysis_dto: AekoReportAnalysisDTO) -> ImprovementPlan:
    improvement_plan = ImprovementPlan(
        defined_problem=aeko_report_analysis_dto.defined_problem,
        method=aeko_report_analysis_dto.method,
        reasoning=aeko_report_analysis_dto.reasoning,
        updated_at=datetime.now()
    )
    return improvement_plan