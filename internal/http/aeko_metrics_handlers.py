"""Expose HTTP endpoints and response models for SDK run metrics."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from aeko_metrics.aeko_metrics import IService
from aeko_metrics.database.repository import Repository
from aeko_metrics.service import Service

router = APIRouter(tags=["Metrics"])

class AgentMetricResponseData(BaseModel):
    name: str = Field(..., description="Agent that was invoked, under the exact name the SDK's graph routes it by.", example="Analista de Poluentes")
    input_tokens: int = Field(..., description="Prompt tokens this single invocation consumed, its whole tool-calling loop included.", example=11)
    output_tokens: int = Field(..., description="Completion tokens this single invocation produced.", example=22)
    llm: str = Field(..., description="Model that served the invocation. More than one name when the SDK's cross-model fallback fired inside the call.", example="gemini-3.5-flash")
    used_tools: list[str] = Field(..., description="Tools the agent actually called, in call order — not the ones registered for it.", example=["climatiq_search", "calculator"])

    class Config:
        frozen = True


class AekoMetricResponseData(BaseModel):
    id: str = Field(..., description="Identifier of the stored row.", example="65a8b3d6c0f8e1d7f4b2c0bb")
    id_request: str = Field(..., description="The request this run belongs to, answered to its caller in the X-Request-Id header and stored as the identifier of its hub_metrics row.", example="65a8b3d6c0f8e1d7f4b2c0aa")
    latency: int = Field(..., description="How long the whole SDK run took, in whole milliseconds.", example=4823)
    error_description: str | None = Field(None, description="Why the run failed, or null when it did not. A conversational turn no reviewer approved is one of these: it delivers nothing, and this row is the only account left of what it cost.", example=None)
    flow: str = Field(..., description="Which entry point served it: conversational for a chat turn, analytical for an inventory analysis.", example="conversational")
    used_agents: list[AgentMetricResponseData] = Field(..., description="One entry per agent invocation, in call order. An agent a reviewer's retry loop called again is listed again.")

    class Config:
        frozen = True


def get_aeko_metrics_service(request: Request) -> IService:
    """Build the SDK metrics service from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get(
    "/aether-api/v1/ai/aeko-metrics",
    response_model=list[AekoMetricResponseData],
    summary="List what every AI run cost",
    description="Returns the whole Aeko event tracking base: one row per SDK run served by the gateway, with the agents it invoked, as the observability dashboard reads it.",
    responses={
        200: {
            "description": "Metrics found.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "65a8b3d6c0f8e1d7f4b2c0bb",
                            "id_request": "65a8b3d6c0f8e1d7f4b2c0aa",
                            "latency": 4823,
                            "error_description": None,
                            "flow": "conversational",
                            "used_agents": [
                                {
                                    "name": "Analista de Poluentes",
                                    "input_tokens": 11,
                                    "output_tokens": 22,
                                    "llm": "gemini-3.5-flash",
                                    "used_tools": ["climatiq_search", "calculator"],
                                }
                            ],
                        }
                    ]
                }
            },
        },
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_all_metrics(
    service: IService = Depends(get_aeko_metrics_service),
) -> list[AekoMetricResponseData]:
    """Retrieve all stored metrics."""
    try:
        return [
            AekoMetricResponseData(
                id=metric.id,
                id_request=metric.id_request,
                latency=metric.latency,
                error_description=metric.error_description,
                flow=metric.flow,
                used_agents=[
                    AgentMetricResponseData(
                        name=agent.name,
                        input_tokens=agent.input_tokens,
                        output_tokens=agent.output_tokens,
                        llm=agent.llm,
                        used_tools=agent.used_tools,
                    )
                    for agent in metric.used_agents
                ],
            )
            for metric in service.get_all_metrics()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving aeko metrics: {exc}") from exc
