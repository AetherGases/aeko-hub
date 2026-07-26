from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from user.database.repository import Repository
from user.service import Service
from user.user import IService

router = APIRouter(tags=["Users"])

class UserResponseData(BaseModel):
    id_external_user: int = Field(..., description="External identifier of the user.", example=12345)
    role: str = Field(..., description="Role assigned to the user.", example="analyst")
    usecase: str = Field(..., description="User use case or profile category.", example="report_generation")

    class Config:
        frozen = True


def get_user_service(request: Request) -> IService:
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get(
    "/v1/ai/user/{id_external_user}",
    response_model=UserResponseData,
    summary="Get user by external identifier",
    description="Retrieves a user profile using the external user identifier stored in the core database.",
    responses={
        200: {
            "description": "User profile found.",
            "content": {
                "application/json": {
                    "example": {
                        "id_external_user": 12345,
                        "role": "analyst",
                        "usecase": "report_generation",
                    }
                }
            },
        },
        404: {"description": "User not found."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_user(
    id_external_user: int = Path(..., description="External user identifier.", example=12345),
    service: IService = Depends(get_user_service),
) -> UserResponseData:
    try:
        user = service.get_mongo_user(id_external_user)
        return UserResponseData(
            id_external_user=user.id_external_user,
            role=user.role,
            usecase=user.usecase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user: {exc}") from exc