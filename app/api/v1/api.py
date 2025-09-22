from fastapi import APIRouter
from app.api.v1.endpoints import payment, monitoring, merchant, stats, refund
from app.api.v1.endpoints.admin import admin_router
from app.api.v1.endpoints.admin import admin_auth

api_router = APIRouter()
api_router.include_router(payment.router, prefix="/payment", tags=["payment"])
api_router.include_router(admin_router, tags=["admin"])
api_router.include_router(admin_auth.router, prefix="/admin-auth", tags=["admin-auth"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
api_router.include_router(merchant.router, prefix="/merchant", tags=["merchant"])
api_router.include_router(refund.router, prefix="/merchant", tags=["refund"])


