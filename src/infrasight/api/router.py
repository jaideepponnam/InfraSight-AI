from fastapi import APIRouter, Depends

from infrasight.api import ai, analytics, etl, inventory
from infrasight.api.auth import require_read
from infrasight.api.schemas import ErrorResponse

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_read)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 500, 503)},
)
router.include_router(ai.router)
router.include_router(analytics.router)
router.include_router(inventory.router)
router.include_router(etl.router)
