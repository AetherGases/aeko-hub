from pydantic import BaseModel

from datetime import datetime

from session.database.repository import Repository
from session.service import Service
from session.session import IService

from fastapi import APIRouter, Depends, HTTPException, Request

from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

router = APIRouter()

class ReportResponseData(BaseModel):
    s3_path: str
    file_name: str

    class Config:
        frozen = True



def get_session_service(request: Request) -> IService:
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))

@router.post("/aether-api/v1/ai/report", response_model=ReportResponseData)
def input_report(
    request: Request,
    s3: str,
    id_user: str,
    id_gas_reduction: int | None = None,
    id_department: int | None = None,
    id_external_user_owner: int | None = None,
    id_external_user_validator: int | None = None,
    id_external_input_report: int | None = None,
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