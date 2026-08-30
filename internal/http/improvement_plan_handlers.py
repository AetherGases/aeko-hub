from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from session.database.repository import Repository
from session.service import Service
from session.session import IService

from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

router = APIRouter(tags=["Reports"])

class ReportResponseData(BaseModel):
    s3_path: str = Field(..., description="S3 URI of the generated report.", example="s3://reports-bucket/reports/output/65a8b3d6c0f8e1d7f4b2c010/202607261430.pdf")
    file_name: str = Field(..., description="Generated PDF file name.", example="202607261430.pdf")

    class Config:
        frozen = True



def get_session_service(request: Request) -> IService:
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))

@router.post(
    "/aether-api/v1/ai/report",
    response_model=ReportResponseData,
    summary="Generate an improvement plan report",
    description="Analyzes an input report, persists the derived improvement plan, and stores the generated output report in S3.",
    responses={
        200: {
            "description": "Report generated successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "s3_path": "s3://reports-bucket/reports/output/65a8b3d6c0f8e1d7f4b2c010/202607261430.pdf",
                        "file_name": "202607261430.pdf",
                    }
                }
            },
        },
        400: {"description": "One or more request parameters are invalid."},
        500: {"description": "Unexpected server error during report processing."},
    },
)
def input_report(
    request: Request,
    s3: str = Query(..., description="Input report bucket or S3 path used to load the source file.", example="reports/input/65a8b3d6c0f8e1d7f4b2c010/input.pdf"),
    id_user: str = Query(..., description="Internal user identifier responsible for the report.", example="65a8b3d6c0f8e1d7f4b2c010"),
    id_gas_reduction: int | None = Query(None, description="Optional external gas reduction identifier used as context.", example=9001),
    id_department: int | None = Query(None, description="Optional department identifier associated with the output report.", example=12),
    id_external_user_owner: int | None = Query(None, description="Optional external owner identifier for the output report.", example=12345),
    id_external_user_validator: int | None = Query(None, description="Optional external validator identifier for the output report.", example=12346),
    id_external_input_report: int | None = Query(None, description="Optional external input report identifier.", example=777),
    service: IService = Depends(get_session_service),
) -> ReportResponseData:
    try:
        user_service = UserService(UserRepository(request.app.state.db))
        s3_path = service.input_report(
            s3, 
            id_user, 
            id_gas_reduction, 
            user_service, 
            id_department, 
            id_external_user_owner, 
            id_external_user_validator, 
            id_external_input_report
        )
        file_name = s3_path.split("/")[-1]
        return ReportResponseData(s3_path=s3_path, file_name=file_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing report: {exc}") from exc 