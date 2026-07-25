from pydantic import BaseModel

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request

from session.database.repository import Repository
from session.service import Service
from session.session import IService

from fastapi import APIRouter, Depends, HTTPException, Request
from user.database.repository import Repository as UserRepository

router = APIRouter()

class SessionResponseData(BaseModel):
    id: str
    name: str

    class Config:
        frozen = True

class MessageResponseData(BaseModel):
    input_message: str
    output_message: str
    submitted_at: datetime

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
        sessions = service.get_user_sessions(id_user)
        return [SessionResponseData(id=session.id, name=session.name) for session in sessions]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user sessions: {exc}") from exc

@router.get("/v1/ai/session/{id_session}/messages", response_model=list[MessageResponseData])
def get_session_messages(
    id_session: str,
    service: IService = Depends(get_session_service),
) -> list[MessageResponseData]:
    try:
        messages = service.get_session_messages(id_session)
        return [
            MessageResponseData(
                input_message=message.input,
                output_message=message.output,
                submitted_at=message.submitted_at
            )
            for message in messages
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving session messages: {exc}") from exc

from fastapi import APIRouter, Depends, HTTPException, Request

@router.post("/aether-api/v1/ai/user/session/message")
async def send_message(
    request: Request,
    service: IService = Depends(get_session_service),
):
    body = await request.json()

    id_session = body.get("id_session")
    input = body.get("input", "")
    id_user = body.get("id_user", "")
    aeko_messenger = request.app.state._state.get("aeko_messenger")

    if not aeko_messenger:
        raise HTTPException(status_code=500, detail="Aeko messenger is not initialized")

    try:
        message = service.send_message(id_session, input, id_user, aeko_messenger, UserRepository(request.app.state.db))
        return MessageResponseData(
            input_message=message.input,
            output_message=message.output,
            submitted_at=message.submitted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error sending message: {exc}") from exc