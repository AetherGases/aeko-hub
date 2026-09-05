"""Expose HTTP endpoints and response models for HTTP request metrics."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from hub_metrics.database.repository import Repository
from hub_metrics.hub_metrics import IService
from hub_metrics.service import Service

router = APIRouter(tags=["Metrics"])

class MetricResponseData(BaseModel):
    id: str = Field(..., description="Identifier of the tracked request, answered to its caller in the X-Request-Id header.", json_schema_extra={"example": "65a8b3d6c0f8e1d7f4b2c0aa"})
    latency: str = Field(..., description="How long the request took, in milliseconds.", json_schema_extra={"example": "12.4ms"})
    response_status: int = Field(..., description="HTTP status the request answered with.", json_schema_extra={"example": 200})
    endpoint: str = Field(..., description="Route template the request matched.", json_schema_extra={"example": "/aether-api/v1/ai/user/{id_external_user}"})

    model_config = ConfigDict(frozen=True)


def get_hub_metrics_service(request: Request) -> IService:
    """Build the request metrics service from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return Service(Repository(database))


@router.get(
    "/aether-api/v1/ai/hub-metrics",
    response_model=list[MetricResponseData],
    summary="List every tracked request",
    description="Returns the whole event tracking base: one row per request served by the gateway, as the observability dashboard reads it.",
    responses={
        200: {
            "description": "Metrics found.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "65a8b3d6c0f8e1d7f4b2c0aa",
                            "latency": "12.4ms",
                            "response_status": 200,
                            "endpoint": "/aether-api/v1/ai/user/{id_external_user}",
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
    service: IService = Depends(get_hub_metrics_service),
) -> list[MetricResponseData]:
    """Retrieve all stored metrics."""
    try:
        return [
            MetricResponseData(
                id=metric.id,
                latency=metric.latency,
                response_status=metric.response_status,
                endpoint=metric.endpoint,
            )
            for metric in service.get_all_metrics()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {exc}") from exc
