from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from user.database.repository import Repository
from user.service import Service
from user.user import IService

router = APIRouter()

class UserResponseData(BaseModel):
    id_external_user: int
    role: str
    usecase: str

    class Config:
        frozen = True


def get_user_service(request: Request) -> IService:
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get("/v1/ai/user/{id_external_user}", response_model=UserResponseData)
def get_user(
    id_external_user: int,
    service: IService = Depends(get_user_service),
) -> UserResponseData:
    try:
        user = service.getMongoUser(id_external_user)
        return UserResponseData(
            id_external_user=user.id_external_user,
            role=user.role,
            usecase=user.usecase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user: {exc}") from exc