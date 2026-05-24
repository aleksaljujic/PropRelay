from fastapi import APIRouter

from app.api.v1.webhook import router as webhook_router

api_router = APIRouter()

api_router.include_router(
    webhook_router,
    prefix="/api/v1",
    tags=["WhatsApp Webhook"],
)
