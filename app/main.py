from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.config import settings, get_base_url
from app.core.middleware import BodyCacheMiddleware, LoggingMiddleware
from app.core.exception_handlers import setup_exception_handlers, RequestIDMiddleware
from app.core.logging_config import setup_logging
from app.services.realtime_monitoring_service import realtime_monitoring_service
from app.services.bank_alerts_service import bank_alerts_service
from app.services.two_phase_recovery_service import two_phase_recovery_service
from app.api.v1.api import api_router
from app.api.v1.endpoints.payment_page import router as payment_page_router

# Опциональный импорт симулятора банков (только для разработки)
import os
ENABLE_BANK_SIMULATOR = os.getenv("ENABLE_BANK_SIMULATOR", "false").lower() == "true"
if ENABLE_BANK_SIMULATOR:
    try:
        from simulation.simulation_router import router as simulation_router
        SIMULATION_AVAILABLE = True
        print("🏦 Симулятор банков подключен (режим разработки)")
        logger = setup_logging()
        logger.warning("🏦 Симулятор банков подключен (режим разработки)")
    except ImportError:
        SIMULATION_AVAILABLE = False
        print("⚠️ Симулятор банков недоступен (отсутствуют файлы)")
else:
    SIMULATION_AVAILABLE = False
    print("🔧 Симулятор банков отключен (ENABLE_BANK_SIMULATOR=false)")
    logger = setup_logging()
    logger.warning("🔧 Симулятор банков отключен (ENABLE_BANK_SIMULATOR=false)")
from app.database import engine, Base, SessionLocal
from app.services.timeline_service import TimelineService
from app.services.auth_service import BankAuthService
from app.models.payment import Bank
from app.database import engine, Base
from contextlib import asynccontextmanager
from app.models.settings import SystemSetting
from app.services.qr_security_service import QRSecurityService

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Инициализируем подробное логирование
    logger = setup_logging()
    
    # Startup - создаем таблицы
    logger.warning("🗄️ Инициализация базы данных...")
    Base.metadata.create_all(bind=engine)
    logger.warning("✅ База данных готова к работе")

    # Применяем сохранённые настройки QR безопасности из БД при старте
    try:
        with SessionLocal() as db:
            st = db.query(SystemSetting).filter(SystemSetting.key == "qr_security").first()
            if st:
                import json as _json
                cfg = _json.loads(st.value_json)
                QRSecurityService.MAX_QR_LIFETIME = int(cfg.get("max_qr_lifetime_minutes", QRSecurityService.MAX_QR_LIFETIME))
                QRSecurityService.MIN_QR_LIFETIME = int(cfg.get("min_qr_lifetime_minutes", QRSecurityService.MIN_QR_LIFETIME))
                QRSecurityService.ALLOWED_DOMAINS = cfg.get("allowed_domains", QRSecurityService.ALLOWED_DOMAINS)
                settings.QR_TOKEN_EXPIRE_MINUTES = int(cfg.get("default_expires_minutes", settings.QR_TOKEN_EXPIRE_MINUTES))
    except Exception:
        pass


    
    # Запускаем мониторинг в реальном времени
    logger.warning("📊 Запуск системы мониторинга...")
    realtime_monitoring_service.start_monitoring()
    logger.warning("✅ Мониторинг активен")
    
    # Запускаем систему алертов
    logger.warning("🚨 Запуск системы алертов...")
    bank_alerts_service.start_processing()
    logger.warning("✅ Система алертов активна")

    # Запускаем фоновый чекер просроченных ожиданий оплаты для таймлайна
    try:
        TimelineService.start_pending_checker(SessionLocal, timeout_minutes=15, interval_seconds=60)
        logger.warning("⏱️ Проверка ожидающих платежей активна")
    except Exception as e:
        logger.error(f"Не удалось запустить проверку ожидающих платежей: {e}")
    
    # Запускаем фоновый сервис восстановления двухфазных транзакций
    try:
        import asyncio
        asyncio.create_task(two_phase_recovery_service.start_background_recovery())
        logger.warning("🔄 Сервис восстановления транзакций активен")
    except Exception as e:
        logger.error(f"Не удалось запустить сервис восстановления: {e}")
    
    yield
    
    # Shutdown - останавливаем мониторинг и алерты
    logger.warning("🛑 Остановка системы...")
    realtime_monitoring_service.stop_monitoring()
    bank_alerts_service.stop_processing()
    two_phase_recovery_service.stop_background_recovery()
    logger.warning("✅ Система остановлена")

app = FastAPI(
    title="QRPayHub API",
    description="Межбанковская платформа для приёма платежей через QR-коды без комиссий",
    version="1.0.0",
    lifespan=lifespan
)

# Настройка шаблонов
templates = Jinja2Templates(directory="templates")

def get_template_context(request: Request) -> dict:
    """Генерация контекста для шаблонов с глобальными переменными"""
    base = get_base_url()
    return {
        "request": request,
        "BASE_URL": base,
        "PAYMENT_URL_TEMPLATE": f"{base}/pay?token=" if base else "/pay?token=",
        "SIMULATION_URL_TEMPLATE": f"{base}/simulation/" if base else "/simulation/",
        "BANK_API_URL": f"{base}/simulation/bank-api" if base else "/simulation/bank-api"
    }

# Настройка глобальных обработчиков исключений
setup_exception_handlers(app)

# Настройка middleware (порядок важен!)
# BodyCacheMiddleware должен выполняться ПЕРВЫМ, чтобы прочитать тело до других middleware
app.add_middleware(BodyCacheMiddleware)   # Кеширование body для HMAC (ПЕРВЫМ!)
app.add_middleware(RequestIDMiddleware)   # Добавление request_id к каждому запросу
app.add_middleware(LoggingMiddleware)     # Логирование всех запросов
# app.add_middleware(AdminAuthMiddleware)   # Защита админ панели - ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ДЕМО

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="templates/static"), name="static")

# Подключение роутеров
app.include_router(api_router, prefix="/api/v1")
app.include_router(payment_page_router)  # Без префикса для /pay

# Подключение симулятора банков (только в режиме разработки)
if SIMULATION_AVAILABLE:
    try:
        app.include_router(simulation_router)
        print("✅ Роутер симулятора банков подключен к приложению")
    except Exception as e:
        print(f"❌ Ошибка при подключении роутера симулятора: {e}")
        print(f"🔍 Детали ошибки: {type(e).__name__}: {str(e)}")
        SIMULATION_AVAILABLE = False
else:
    print("🔧 Роутер симулятора банков не подключен (SIMULATION_AVAILABLE=False)")

"""Статические страницы MVP"""

@app.get("/")
async def root():
    """Простая главная страница MVP (демо функциональности)"""
    return FileResponse("templates/index.html")

# === АДМИН-ПАНЕЛЬ (новая компонентная архитектура) ===

@app.get("/admin")
async def admin_redirect():
    """Перенаправление на дашборд"""
    return RedirectResponse(url=f"{get_base_url()}/admin/dashboard", status_code=302)

@app.get("/admin/login")
async def admin_login():
    """Минимальная страница входа для админов"""
    return FileResponse("templates/admin_login.html")

@app.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    """Дашборд администратора"""
    return templates.TemplateResponse("admin/pages/dashboard.html", get_template_context(request))

@app.get("/admin/banks")
async def admin_banks(request: Request):
    """Управление банками"""
    return templates.TemplateResponse("admin/pages/banks.html", get_template_context(request))

@app.get("/admin/transactions")
async def admin_transactions(request: Request):
    """Просмотр транзакций"""
    return templates.TemplateResponse("admin/pages/transactions.html", get_template_context(request))

@app.get("/admin/monitoring")
async def admin_monitoring(request: Request):
    """Мониторинг системы"""
    return templates.TemplateResponse("admin/pages/monitoring.html", get_template_context(request))

@app.get("/admin/alerts")
async def admin_alerts(request: Request):
    """Управление алертами"""
    return templates.TemplateResponse("admin/pages/alerts.html", get_template_context(request))

@app.get("/admin/audit")
async def admin_audit(request: Request):
    """Журнал аудита"""
    return templates.TemplateResponse("admin/pages/audit.html", get_template_context(request))

@app.get("/admin/settings")
async def admin_settings(request: Request):
    """Настройки системы"""
    return templates.TemplateResponse("admin/pages/settings.html", get_template_context(request))

@app.get("/admin/admins")
async def admin_admins(request: Request):
    """Управление администраторами"""
    return templates.TemplateResponse("admin/pages/admins.html", get_template_context(request))

@app.get("/admin/merchants")
async def admin_merchants(request: Request):
    """Управление продавцами"""
    return templates.TemplateResponse("admin/pages/merchants.html", get_template_context(request))

@app.get("/admin/profile")
async def admin_profile(request: Request):
    """Профиль администратора"""
    return templates.TemplateResponse("admin/pages/profile.html", get_template_context(request))

@app.get("/admin/qr-codes")
async def admin_qr_codes(request: Request):
    """QR-коды администратора"""
    return templates.TemplateResponse("admin/pages/qr-codes.html", get_template_context(request))

# Симулятор банков (только если включен)
if SIMULATION_AVAILABLE:
    @app.get("/admin/simulator")
    async def admin_simulator():
        """Перенаправление на симулятор банков"""
        return RedirectResponse(url=f"{get_base_url()}/simulation", status_code=302)



# === КАБИНЕТ ПРОДАВЦА (новая компонентная архитектура) ===

@app.get("/merchant-login")
async def merchant_login_page(request: Request):
    return templates.TemplateResponse("merchant_login.html", get_template_context(request))

@app.get("/merchant-register")
async def merchant_register_page(request: Request):
    """Страница регистрации продавцов (MVP)"""
    return templates.TemplateResponse("merchant_register.html", get_template_context(request))



# Новые маршруты кабинета продавца
@app.get("/merchant")
async def merchant_redirect():
    """Перенаправление на дашборд"""
    return RedirectResponse(url=f"{get_base_url()}/merchant/dashboard", status_code=302)

@app.get("/merchant/dashboard")
async def merchant_dashboard(request: Request):
    """Дашборд продавца"""
    return templates.TemplateResponse("merchant/pages/dashboard.html", get_template_context(request))

@app.get("/merchant/qr-codes")
async def merchant_qr_codes(request: Request):
    """QR-коды продавца"""
    return templates.TemplateResponse("merchant/pages/qr-codes.html", get_template_context(request))

@app.get("/merchant/payments")
async def merchant_payments(request: Request):
    """Платежи продавца"""
    return templates.TemplateResponse("merchant/pages/payments.html", get_template_context(request))

@app.get("/merchant/refunds")
async def merchant_refunds(request: Request):
    """Возвраты продавца"""
    return templates.TemplateResponse("merchant/pages/refunds.html", get_template_context(request))

@app.get("/merchant/outlets")
async def merchant_outlets(request: Request):
    """Торговые точки"""
    return templates.TemplateResponse("merchant/pages/outlets.html", get_template_context(request))

@app.get("/merchant/statistics")
async def merchant_statistics(request: Request):
    return templates.TemplateResponse("merchant/pages/statistics.html", get_template_context(request))

@app.get("/merchant/settings")
async def merchant_settings(request: Request):
    """Настройки продавца"""
    return templates.TemplateResponse("merchant/pages/settings.html", get_template_context(request))

# Статические файлы для админки
app.mount("/static", StaticFiles(directory="templates/static"), name="static")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

