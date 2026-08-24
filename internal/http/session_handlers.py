from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from session.database.repository import Repository
from session.service import Service
from session.session import GuardrailRejectedError, IService

from user.database.repository import Repository as UserRepository

router = APIRouter(tags=["Sessions"])

class SessionResponseData(BaseModel):
    id: str = Field(..., description="Internal session identifier.", example="65a8b3d6c0f8e1d7f4b2c001")
    name: str = Field(..., description="Human-readable session name.", example="Weekly emissions review")

    class Config:
        frozen = True

class MessageResponseData(BaseModel):
    input_message: str = Field(..., description="Input text sent to the AI agent.", example="Summarize this session.")
    output_message: str = Field(..., description="Output returned by the AI agent.", example="Here is the summary.")
    submitted_at: datetime = Field(..., description="Timestamp when the message was submitted.", example="2026-07-26T14:30:00Z")

def get_session_service(request: Request) -> IService:
    """Build the session service for this request, on the app's database.

    Raises:
        HTTPException: 503 when the lifespan never opened a connection.
    """
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get(
    "/v1/ai/sessions/user/{id_user}",
    response_model=list[SessionResponseData],
    summary="List sessions for a user",
    description="Returns all sessions associated with the internal user identifier.",
    responses={
        200: {
            "description": "Sessions found for the user.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "65a8b3d6c0f8e1d7f4b2c001",
                            "name": "Weekly emissions review",
                        }
                    ]
                }
            },
        },
        404: {"description": "No sessions found for the given user."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_user_sessions(
    id_user: str = Path(..., description="Internal user identifier.", example="65a8b3d6c0f8e1d7f4b2c010"),
    service: IService = Depends(get_session_service),
) -> list[SessionResponseData]:
    """Return every session belonging to a user.

    Maps `ValueError` to 404 and anything unexpected to 500.
    """
    try:
        sessions = service.get_user_sessions(id_user)
        return [SessionResponseData(id=session.id, name=session.name) for session in sessions]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user sessions: {exc}") from exc

@router.get(
    "/v1/ai/session/{id_session}/messages",
    response_model=list[MessageResponseData],
    summary="List messages for a session",
    description="Returns the message history stored for a specific session.",
    responses={
        200: {
            "description": "Messages found for the session.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "input_message": "Summarize this session.",
                            "output_message": "Here is the summary.",
                            "submitted_at": "2026-07-26T14:30:00Z",
                        }
                    ]
                }
            },
        },
        400: {"description": "The session identifier is invalid or unavailable."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_session_messages(
    id_session: str = Path(..., description="Internal session identifier.", example="65a8b3d6c0f8e1d7f4b2c001"),
    service: IService = Depends(get_session_service),
) -> list[MessageResponseData]:
    """Return the message history stored for a session.

    Maps `ValueError` to 400 and anything unexpected to 500.
    """
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

@router.post(
    "/aether-api/v1/ai/user/session/message",
    summary="Send a message to the AI session",
    description="Creates or continues a session message exchange using the current Aeko messenger instance.",
    tags=["Sessions"],
    responses={
        200: {
            "description": "Message processed successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "input_message": "Summarize this session.",
                        "output_message": "Here is the summary.",
                        "submitted_at": "2026-07-26T14:30:00Z",
                    }
                }
            },
        },
        400: {"description": "The request body is missing required fields or is invalid."},
        500: {"description": "Aeko messenger is not initialized or an unexpected error occurred."},
        502: {"description": "The AI output guardrail rejected every draft, so there is no answer."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["id_session", "input", "id_user"],
                        "properties": {
                            "id_session": {
                                "type": "string",
                                "description": "Optional session identifier. Omit or send an empty value to create a new session.",
                                "example": "65a8b3d6c0f8e1d7f4b2c001",
                            },
                            "input": {
                                "type": "string",
                                "description": "Message text to send to the AI agent.",
                                "example": "Summarize this session.",
                            },
                            "id_user": {
                                "type": "string",
                                "description": "Internal user identifier.",
                                "example": "65a8b3d6c0f8e1d7f4b2c010",
                            },
                        },
                    },
                    "example": {
                        "id_session": "65a8b3d6c0f8e1d7f4b2c001",
                        "input": "Summarize this session.",
                        "id_user": "65a8b3d6c0f8e1d7f4b2c010",
                    },
                }
            },
        }
    },
)
async def send_message(
    request: Request,
    service: IService = Depends(get_session_service),
):
    """Run one conversational turn through the AI and persist it.

    The body carries `id_session` (empty to open a new session), `input` and
    `id_user`. The messenger factory comes off `app.state`, published there
    by the lifespan.

    Maps a rejected guardrail to 502, `ValueError` to 400, and anything
    unexpected to 500.
    """
    body = await request.json()

    id_session = body.get("id_session")
    input = body.get("input", "")
    id_user = body.get("id_user", "")
    aeko_messenger_factory = request.app.state._state.get("aeko_messenger_factory")

    if not aeko_messenger_factory:
        raise HTTPException(status_code=500, detail="Aeko messenger is not initialized")

    try:
        message = service.send_message(id_session, input, id_user, aeko_messenger_factory, UserRepository(request.app.state.db))
        return MessageResponseData(
            input_message=message.input,
            output_message=message.output,
            submitted_at=message.submitted_at,
        )
    except GuardrailRejectedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error sending message: {exc}") from exc