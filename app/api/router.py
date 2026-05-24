from fastapi import APIRouter

from app.api.v1.orchestration import router as orchestration_router
from app.api.v1.webhook import router as webhook_router

api_router = APIRouter()

api_router.include_router(
    webhook_router,
    prefix="/api/v1",
    tags=["WhatsApp Webhook"],
)

api_router.include_router(
    orchestration_router,
    prefix="/api/v1",
    tags=["Orchestration"],
)
