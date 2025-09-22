# Admin API endpoints package

from fastapi import APIRouter
from .payments import router as payments_router
from .banks import router as banks_router
from .merchants import router as merchants_router
from .audit import router as audit_router
from .rate_limits import router as rate_limits_router
from .billing import router as billing_router
from .validation import router as validation_router
from .webhook_security import router as webhook_security_router
from .qr_security import router as qr_security_router
from .error_handling import router as error_handling_router
from .bank_adapters import router as bank_adapters_router
from .dashboard import router as dashboard_router
from .alerts import router as alerts_router
from .transactions import router as transactions_router
from .system import router as system_router
from .statistics import router as statistics_router
from .test import router as test_router
from .admins import router as admins_router
from .qr_codes import router as qr_codes_router
from .refund_admin import router as refund_admin_router

# Создаем главный роутер для admin
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Подключаем все подроутеры БЕЗ префиксов (они уже есть в самих роутерах)
admin_router.include_router(payments_router, tags=["admin-payments"])
admin_router.include_router(banks_router, tags=["admin-banks"])
admin_router.include_router(merchants_router, tags=["admin-merchants"])
admin_router.include_router(audit_router, tags=["admin-audit"])
admin_router.include_router(rate_limits_router, tags=["admin-rate-limits"])
admin_router.include_router(billing_router, tags=["admin-billing"])
admin_router.include_router(validation_router, tags=["admin-validation"])
admin_router.include_router(webhook_security_router, tags=["admin-webhook"])
admin_router.include_router(qr_security_router, tags=["admin-qr"])
admin_router.include_router(error_handling_router, tags=["admin-errors"])
admin_router.include_router(bank_adapters_router, tags=["admin-adapters"])
admin_router.include_router(dashboard_router, tags=["admin-dashboard"])
admin_router.include_router(alerts_router, tags=["admin-alerts"])
admin_router.include_router(transactions_router, tags=["admin-transactions"])
admin_router.include_router(system_router, tags=["admin-system"])

admin_router.include_router(statistics_router, tags=["admin-statistics"])
admin_router.include_router(test_router, tags=["admin-test"])
admin_router.include_router(admins_router, tags=["admin-admins"])
admin_router.include_router(qr_codes_router, prefix="/qr-codes", tags=["admin-qr-codes"])
admin_router.include_router(refund_admin_router, tags=["admin-refunds"])

__all__ = ["admin_router"]
