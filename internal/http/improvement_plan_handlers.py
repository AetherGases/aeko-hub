"""Expose HTTP endpoints and response models for improvement plans."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from improvement_plan.database.repository import Repository
from improvement_plan.improvement_plan import IService, MalformedPlanError
from improvement_plan.integration.ms_inventory import Repository as InventoryRepository
from improvement_plan.service import Service

from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

router = APIRouter(tags=["Reports"])

class ImprovementPlanResponseData(BaseModel):
    id: str | None = Field(..., description="Identifier of the stored improvement plan.", example="65a8b3d6c0f8e1d7f4b2c020")
    id_external_inventory: int | None = Field(..., description="Analyzed inventory identifier in the Aether platform.", example=502)
    id_external_unit: int | None = Field(..., description="Unit the analyzed inventory belongs to.", example=77)
    defined_problem: str = Field(..., description="Problem the analysis identified.", example="high scope 1 emissions")
    method: str = Field(..., description="What the plan proposes doing about it.", example="replace the boiler fleet")
    reasoning: str = Field(..., description="Why that method addresses that problem.", example="direct combustion dominates the inventory")

    class Config:
        frozen = True


def get_improvement_plan_service(request: Request) -> IService:
    """Build the plan service with database and inventory repositories, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")

    return Service(Repository(database), InventoryRepository())

@router.post(
    "/aether-api/v1/ai/report",
    response_model=ImprovementPlanResponseData,
    summary="Generate an improvement plan report",
    description=(
        "Resolves the inventory as Markdown through the ms-inventory microservice, runs it "
        "through the Aeko analyst flow with the unit's last two plans as context, and stores "
        "and returns the improvement plan that came out."
    ),
    responses={
        200: {
            "description": "Improvement plan generated and stored.",
            "content": {
                "application/json": {
                    "example": {
                        "id": "65a8b3d6c0f8e1d7f4b2c020",
                        "id_external_inventory": 502,
                        "id_external_unit": 77,
                        "defined_problem": "high scope 1 emissions",
                        "method": "replace the boiler fleet",
                        "reasoning": "direct combustion dominates the inventory",
                    }
                }
            },
        },
        400: {"description": "One or more request parameters are invalid, or the inventory has no content."},
        502: {"description": "The analysis produced no plan under the three headings a report is stored in."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "The Aeko SDK is not initialized or an unexpected error occurred."},
    },
)
async def input_report(
    request: Request,
    id_external_inventory: int = Query(..., description="Inventory identifier in the Aether platform, resolved through ms-inventory and filed against the resulting plan.", example=502),
    id_external_unit: int = Query(..., description="Unit the inventory belongs to, which is what the previous plans are read by.", example=77),
    id_user: str = Query(..., description="Internal user identifier responsible for the report.", example="65a8b3d6c0f8e1d7f4b2c010"),
    service: IService = Depends(get_improvement_plan_service),
) -> ImprovementPlanResponseData:
    """Generate an improvement report in a worker thread and translate domain errors to HTTP responses."""
    aeko_inventory_analyzer_factory = request.app.state._state.get("aeko_inventory_analyzer_factory")

    if not aeko_inventory_analyzer_factory:
        raise HTTPException(status_code=500, detail="Aeko SDK is not initialized")

    try:
        improvement_plan = await run_in_threadpool(
            service.input_inventory,
            id_external_inventory,
            id_external_unit,
            id_user,
            UserService(UserRepository(request.app.state.db)),
            aeko_inventory_analyzer_factory,
        )
        return ImprovementPlanResponseData(
            id=improvement_plan.id,
            id_external_inventory=improvement_plan.id_external_inventory,
            id_external_unit=improvement_plan.id_external_unit,
            defined_problem=improvement_plan.defined_problem,
            method=improvement_plan.method,
            reasoning=improvement_plan.reasoning,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MalformedPlanError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing report: {exc}") from exc
