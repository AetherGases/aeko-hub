from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from session.database.repository import Repository
from session.service import Service
from session.session import IService

router = APIRouter()

class SessionResponseData(BaseModel):
    id: str
    name: str

    class Config:
        frozen = True

def get_session_service(request: Request) -> IService:
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get("/v1/ai/sessions/user/{id_user}", response_model=list[SessionResponseData])
def get_user_sessions(
    id_user: str,
    service: IService = Depends(get_session_service),
) -> list[SessionResponseData]:
    try:
        sessions = service.getUserSessions(id_user)
        return [SessionResponseData(id=session.id, name=session.name) for session in sessions]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user sessions: {exc}") from exc