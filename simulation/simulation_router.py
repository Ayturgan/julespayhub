"""
Независимый симулятор банков для демонстрации двухфазных транзакций
Этот модуль можно легко удалить в продакшене без влияния на основное приложение
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import asyncio
import logging
import secrets
import time
from typing import Optional

from app.database import get_db
from app.models.unified import UnifiedPayment as PaymentRequest, UnifiedQRCode as QRCode
from app.models.enums import TransactionStatus
from app.models.payment import TwoPhaseOperation, Bank
from app.models.merchant import TradingPoint
from app.schemas.payment import PaymentInfo
from app.schemas.bank import (
    TransactionPrepareRequest, TransactionPrepareResponse,
    TransactionCommitRequest, TransactionCommitResponse,
    TransactionAbortRequest, TransactionAbortResponse,
    TwoPhaseOperationStatus, BankRole
)
from app.schemas.refund import (
    RefundPrepareRequest, RefundPrepareResponse,
    RefundCommitRequest, RefundCommitResponse,
    RefundAbortRequest, RefundAbortResponse
)
from app.services.token_service import SecureTokenService
from app.services.two_phase_commit_service import two_phase_commit_service
from app.services.timeline_service import TimelineService
from app.core.config import get_simulation_url, get_base_url
from simulation.bank_api import router as bank_api_router

# Настройка шаблонов для симулятора
import os
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

def get_simulation_template_context(request: Request, **kwargs) -> dict:
    """Генерация контекста для шаблонов симулятора с глобальными переменными"""
    base = get_base_url()
    base_context = {
        "request": request,
        "BASE_URL": base,
        "PAYMENT_URL_TEMPLATE": f"{base}/pay?token=" if base else "/pay?token=",
        "SIMULATION_URL_TEMPLATE": f"{base}/simulation/" if base else "/simulation/",
        "BANK_API_URL": f"{base}/simulation/bank-api" if base else "/simulation/bank-api"
    }
    base_context.update(kwargs)
    return base_context

# Логгер для симулятора
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Добавляем обработчик, если его нет
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Основной роутер
router = APIRouter(prefix="/simulation", tags=["Bank Simulator"])

@router.get("/", response_class=HTMLResponse)
async def simulation_dashboard(request: Request, db: Session = Depends(get_db)):
    """Главная страница симулятора с выбором режима"""
    
    # Получаем статистику для отображения
    total_payments = db.query(PaymentRequest).count()
    active_transactions = db.query(PaymentRequest).filter(
        PaymentRequest.status.in_(["preparing", "prepared", "committing"])
    ).count()
    
    banks = db.query(Bank).all()
    
    # Получаем список продавцов для выбора в симуляторе
    from app.models.merchant import Merchant
    merchants_data = []
    merchants = db.query(Merchant).filter(Merchant.is_active == True).limit(10).all()
    for merchant in merchants:
        merchants_data.append({
            "id": merchant.id,
            "name": merchant.name,
            "email": merchant.email,
            "bank_name": merchant.bank_name,
            "is_verified": merchant.is_verified
        })
    
    return templates.TemplateResponse("simulation/dashboard.html", get_simulation_template_context(
        request=request,
        total_payments=total_payments,
        active_transactions=active_transactions,
        banks=banks,
        merchants=merchants,
        merchants_data=merchants_data,
        page_title="Симулятор Банков - QRPayHub"
    ))

@router.get("/bank-selection", response_class=HTMLResponse)
async def bank_selection_page(
    request: Request,
    token: str = Query(..., description="QR token"),
    db: Session = Depends(get_db)
):
    """
    Страница выбора банка для оплаты
    """
    try:
        # Пытаемся найти QR по прямому токену или по UUID из защищенного токена
        logger.info(f"Поиск QR кода по токену: {token[:20]}...")
        qr_code = db.query(QRCode).filter(QRCode.qr_token == token).first()
        if not qr_code:
            token_uuid = SecureTokenService.extract_uuid_from_token(token)
            if token_uuid:
                qr_code = db.query(QRCode).filter(QRCode.qr_token == token_uuid).first()

        # Проверяем срок действия QR-кода
        if qr_code and qr_code.expires_at:
            current_time = datetime.now(timezone.utc)
            # Приводим expires_at к UTC, если у него нет часового пояса
            expires_at_utc = qr_code.expires_at
            if expires_at_utc.tzinfo is None:
                expires_at_utc = expires_at_utc.replace(tzinfo=timezone.utc)
            logger.info(f"Проверка QR кода: expires_at={expires_at_utc}, current_time={current_time}")
            if expires_at_utc < current_time:
                logger.info(f"QR код истек: {qr_code.name}")
                return templates.TemplateResponse("simulation/qr_expired.html", get_simulation_template_context(
                    request=request,
                    qr_code=qr_code,
                    page_title="QR код истек - QRPayHub"
                ))
        
        # Проверяем количество использований
        if qr_code and qr_code.max_uses and qr_code.current_uses >= qr_code.max_uses:
            print(f"⚠️ DEBUG: QR код уже использован максимальное количество раз: {qr_code.name}")
            logger.warning(f"QR код уже использован максимальное количество раз: {qr_code.name}, max_uses={qr_code.max_uses}, current_uses={qr_code.current_uses}")
            return templates.TemplateResponse("simulation/qr_used.html", get_simulation_template_context(
                request=request,
                qr_code=qr_code,
                page_title="QR код уже использован - QRPayHub"
            ))
        
        print(f"🎯 DEBUG: QR код прошел все проверки, показываем страницу выбора банка")
        logger.info("QR код прошел все проверки, показываем страницу выбора банка")
        return templates.TemplateResponse("simulation/bank_selection.html", get_simulation_template_context(
            request=request,
            token=token,
            page_title="Выбор банка - QRPayHub"
        ))
        
    except Exception as e:
        print(f"💥 DEBUG: Ошибка при проверке QR кода: {e}")
        logger.error(f"Ошибка при проверке QR кода: {e}")
        return templates.TemplateResponse("simulation/qr_expired.html", get_simulation_template_context(
            request=request,
            qr_code=None,
            page_title="QR код истек - QRPayHub"
        ))

@router.get("/payment", response_class=HTMLResponse)
async def payment_page(
    request: Request,
    token: str = Query(..., description="QR token"),
    bank: Optional[str] = Query(None, description="Selected bank code"),
    db: Session = Depends(get_db)
):
    """
    Эндпоинт симуляции сканирования QR-кода банком-отправителем
    Отображает интерфейс банка-отправителя для инициации платежа
    """
    
    logger.info(f"🔍 Симуляция сканирования QR: {token[:20]}...")
    
    try:
        # Инициализируем переменные
        token_uuid = None
        payment_request = None
        
        # Ищем QR-код (merchant/admin unified)
        qr_code = db.query(QRCode).filter(QRCode.qr_token == token).first()
        if not qr_code:
            token_uuid = SecureTokenService.extract_uuid_from_token(token)
            if token_uuid:
                qr_code = db.query(QRCode).filter(QRCode.qr_token == token_uuid).first()
        
        # Проверяем срок действия QR кодов
        if qr_code and qr_code.expires_at:
            current_time = datetime.now(timezone.utc)
            # Приводим expires_at к UTC, если у него нет часового пояса
            expires_at_utc = qr_code.expires_at
            if expires_at_utc.tzinfo is None:
                expires_at_utc = expires_at_utc.replace(tzinfo=timezone.utc)
            
            logger.info(f"Проверка QR кода в payment_page: expires_at={expires_at_utc}, current_time={current_time}")
            if expires_at_utc < current_time:
                logger.info(f"QR код истек в payment_page: {qr_code.name}")
                return templates.TemplateResponse("simulation/qr_expired.html", get_simulation_template_context(
                    request=request,
                    qr_code=qr_code,
                    page_title="QR код истек - QRPayHub"
                ))
            else:
                logger.info(f"QR код действителен в payment_page: {qr_code.name}")
        
        elif qr_code and qr_code.expires_at:
            current_time = datetime.now(timezone.utc)
            # Приводим expires_at к UTC, если у него нет часового пояса
            expires_at_utc = qr_code.expires_at
            if expires_at_utc.tzinfo is None:
                expires_at_utc = expires_at_utc.replace(tzinfo=timezone.utc)
            
            logger.info(f"Проверка QR кода в payment_page: expires_at={expires_at_utc}, current_time={current_time}")
            if expires_at_utc < current_time:
                logger.info(f"QR код истек в payment_page: {qr_code.name}")
                return templates.TemplateResponse("simulation/qr_expired.html", get_simulation_template_context(
                    request=request,
                    qr_code=qr_code,
                    page_title="QR код истек - QRPayHub"
                ))
            else:
                logger.info(f"QR код действителен в payment_page: {qr_code.name}")
        
        # Проверяем количество использований QR кодов
        if qr_code and qr_code.max_uses and qr_code.current_uses >= qr_code.max_uses:
            logger.warning(f"QR код уже использован максимальное количество раз в payment_page: {qr_code.name}, max_uses={qr_code.max_uses}, current_uses={qr_code.current_uses}")
            return templates.TemplateResponse("simulation/qr_used.html", get_simulation_template_context(
                request=request,
                qr_code=qr_code,
                page_title="QR код уже использован - QRPayHub"
            ))
        
        if qr_code and qr_code.max_uses and qr_code.current_uses >= qr_code.max_uses:
            logger.warning(f"QR код уже использован максимальное количество раз в payment_page: {qr_code.name}, max_uses={qr_code.max_uses}, current_uses={qr_code.current_uses}")
            return templates.TemplateResponse("simulation/qr_used.html", get_simulation_template_context(
                request=request,
                qr_code=qr_code,
                page_title="QR код уже использован - QRPayHub"
            ))
        
        # Обрабатываем QR-код (merchant или admin — единая модель)
        if qr_code:
            logger.info(f"🎯 Обрабатываем обычный QR-код: {qr_code.name}, токен: {qr_code.qr_token[:20]}...")
            logger.info(f"QR-код expires_at: {qr_code.expires_at}, текущее время: {datetime.now()}")
            logger.info(f"QR-код активен: {qr_code.is_active}, max_uses: {qr_code.max_uses}, current_uses: {qr_code.current_uses}")
            
            # Логируем событие сканирования QR-кода
            TimelineService.record_event(
                db=db,
                payment_token=qr_code.qr_token,
                event_type="qr_scanned",
                title="QR-код отсканирован",
                description=f"QR-код '{qr_code.name}' отсканирован в симуляторе банка",
                actor="bank",
                source="simulation",
                status="success"
            )
            
            # Проверяем, не использован ли уже QR-код
            if qr_code.max_uses and qr_code.current_uses >= qr_code.max_uses:
                logger.warning(f"QR-код уже использован максимальное количество раз: {qr_code.name}, max_uses={qr_code.max_uses}, current_uses={qr_code.current_uses}")
                return templates.TemplateResponse("simulation/qr_used.html", get_simulation_template_context(
                    request=request,
                    qr_code=qr_code,
                    page_title="QR код уже использован - QRPayHub"
                ))
            
            # Временно отключаем проверку срока действия
            # now = datetime.now()  # Используем naive datetime для сравнения
            # if qr_code.expires_at and qr_code.expires_at < now:
            #     logger.warning(f"QR-код истек: expires_at={qr_code.expires_at}, now={now}")
            #     raise HTTPException(status_code=400, detail="QR-код истек")
            
            # Проверяем, не создан ли уже PaymentRequest для этого QR-кода
            existing_payment = db.query(PaymentRequest).filter(
                PaymentRequest.token == qr_code.qr_token
            ).first()
            
            if existing_payment:
                logger.info(f"Используем существующий PaymentRequest: {existing_payment.payment_reference}")
                payment_request = existing_payment
            else:
                logger.info(f"Создаем новый PaymentRequest для QR-кода: {qr_code.name}")
                # Создаем PaymentRequest на основе QR-кода (unified)
                receiver_bank_code = qr_code.receiver_bank_code if hasattr(qr_code, 'receiver_bank_code') else None
                if not receiver_bank_code and getattr(qr_code, 'merchant', None) and qr_code.merchant.bank_name:
                    receiver_bank = db.query(Bank).filter(Bank.name == qr_code.merchant.bank_name).first()
                    receiver_bank_code = receiver_bank.code if receiver_bank else "DEMO"

                # Устанавливаем expires_at с значением по умолчанию, если оно None
                expires_at = qr_code.expires_at
                if expires_at is None:
                    expires_at = datetime.now() + timedelta(hours=24)  # 24 часа по умолчанию
                
                payment_request = PaymentRequest(
                    token=qr_code.qr_token,  # Используем qr_token как token
                    receiver_account=(qr_code.merchant.bank_account if getattr(qr_code, 'merchant', None) else (getattr(qr_code, 'receiver_account', None) or "0000000000000000")),
                    receiver_bank_code=receiver_bank_code or "DEMO",
                    receiver_name=(qr_code.merchant.name if getattr(qr_code, 'merchant', None) else getattr(qr_code, 'name', 'Получатель')),
                    description=qr_code.description or f"Платеж по QR-коду {qr_code.name}",
                    amount=qr_code.amount,
                    currency=qr_code.currency or "KGS",
                    payment_reference=f"QR_{qr_code.qr_token[:8]}",
                    expires_at=expires_at,
                    merchant_id=qr_code.merchant_id,
                    admin_id=getattr(qr_code, 'admin_id', None),
                    status=TransactionStatus.PENDING,
                    sender_bank_code=bank,  # Банк отправителя из параметра
                    payer_bank_code=bank,   # Банк плательщика = банк отправителя
                    sender_account="1234567890123456"  # Счет плательщика
                )
                
                # Сохраняем в БД для использования в симуляторе
                db.add(payment_request)
                db.commit()
                db.refresh(payment_request)
                
                logger.info(f"Создан PaymentRequest: ID={payment_request.id}, банк получателя={receiver_bank_code}")
                
                # Логируем создание платежного запроса
                TimelineService.record_event(
                    db=db,
                    payment_token=payment_request.token,
                    transaction_id=f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
                    event_type="payment_request_created",
                    title="Создание платежного запроса",
                    description=f"Создан платеж на сумму {payment_request.amount} {payment_request.currency}",
                    actor="system",
                    source="simulation",
                    status="success"
                )
        
        # Если QR-код не найден, пробуем найти в PaymentRequest (для защищенных токенов)
        if not qr_code and not admin_qr_code:
            logger.info(f"QR код не найден, пробуем найти в PaymentRequest для токена: {token[:20]}...")
            
            # Пробуем найти в PaymentRequest (для защищенных токенов)
            token_uuid = SecureTokenService.extract_uuid_from_token(token)
            if not token_uuid:
                logger.error(f"Неверный формат токена: {token[:20]}...")
                raise HTTPException(status_code=400, detail="Invalid token format")
            
            payment_request = db.query(PaymentRequest).filter(
                PaymentRequest.token == token_uuid
            ).first()
            
            if not payment_request:
                logger.error(f"PaymentRequest не найден для токена: {token_uuid}")
                raise HTTPException(status_code=404, detail="Payment request not found")
            
            # В симуляторе отключаем валидацию токена для упрощения
            logger.info(f"Найден PaymentRequest: ID={payment_request.id}, пропускаем валидацию токена в симуляторе")
            
            # Проверяем валидность токена (только для информации, не блокируем)
            validation_result = SecureTokenService.validate_token(token, payment_request)
            if not validation_result["valid"]:
                logger.warning(f"Токен не прошел валидацию, но продолжаем в симуляторе: {validation_result.get('error')}")
            else:
                logger.info("Токен прошел валидацию")
        
        # Проверяем, что payment_request определен
        if not payment_request:
            logger.error("payment_request не определен")
            raise HTTPException(status_code=500, detail="Internal server error: payment_request not defined")
        
        logger.info(f"✅ payment_request определен: ID={payment_request.id}, token={payment_request.token[:20]}...")
        
        # Получаем информацию о банке-получателе из профиля продавца
        receiver_bank = None
        if payment_request.merchant_id:
            from app.models.merchant import Merchant
            merchant = db.query(Merchant).filter(Merchant.id == payment_request.merchant_id).first()
            if merchant and merchant.bank_name:
                # Ищем банк по названию из профиля продавца
                receiver_bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
                if receiver_bank:
                    # Обновляем код банка в payment_request
                    payment_request.receiver_bank_code = receiver_bank.code
                    db.commit()
        
        # Если банк не найден по профилю продавца, используем код из payment_request
        if not receiver_bank:
            receiver_bank = db.query(Bank).filter(
                Bank.code == payment_request.receiver_bank_code
            ).first()
        
        # Если банк все еще не найден, используем DEMO банк
        if not receiver_bank:
            receiver_bank = db.query(Bank).filter(Bank.code == "DEMO").first()
            if receiver_bank:
                # Обновляем код банка в payment_request
                payment_request.receiver_bank_code = "DEMO"
                db.commit()
        
        # Получаем информацию о выбранном банке-отправителе
        sender_bank = None
        if bank:
            sender_bank = db.query(Bank).filter(Bank.code == bank).first()
        
        # Если банк не выбран или не найден, используем DEMO банк
        if not sender_bank:
            sender_bank = db.query(Bank).filter(Bank.code == "DEMO").first()
            if sender_bank:
                bank = "DEMO"  # Обновляем код банка
        
        return templates.TemplateResponse("simulation/payment_page.html", get_simulation_template_context(
            request=request,
            payment_request=payment_request,
            receiver_bank=receiver_bank,
            sender_bank=sender_bank,
            selected_bank_code=bank,
            full_token=token,
            page_title=f"Оплата QR-кодом - {payment_request.payment_reference}"
        ))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке QR токена: {e}")
        logger.error(f"Детали ошибки: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/sender-bank", response_class=HTMLResponse)
async def sender_bank_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Страница банка-отправителя для мониторинга запросов
    """
    
    logger.info("🏦 Открыта страница банка-отправителя")
    
    # Получаем информацию о банке
    receiver_bank = db.query(Bank).filter(Bank.code == "DEMO").first()
    
    return templates.TemplateResponse("simulation/sender_bank.html", get_simulation_template_context(
        request=request,
        receiver_bank=receiver_bank,
        page_title="Банк Отправителя - Мониторинг"
    ))

@router.get("/receiver-account/{merchant_id}", response_class=HTMLResponse)
async def receiver_bank_account(
    request: Request,
    merchant_id: int,
    bank: Optional[str] = Query(None, description="Bank ID or code"),
    db: Session = Depends(get_db)
):
    """
    Интерфейс банка-получателя - личный кабинет продавца или админа
    Показывает баланс и последние операции
    """
    
    logger.info(f"🏦 Открыт интерфейс банка-получателя для ID {merchant_id}")
    
    from app.models.merchant import Merchant, MerchantPayment
    from app.models.admin import Admin
    from app.models.unified import UnifiedQRCode as AdminQRCode
    
    # Проверяем, есть ли активный PaymentRequest с merchant_id=None (админский платеж)
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.merchant_id.is_(None),
        PaymentRequest.status.in_(["PENDING", "COMPLETED"])
    ).order_by(PaymentRequest.created_at.desc()).first()
    
    if payment_request and payment_request.payment_reference.startswith("ADMIN_QR_"):
        # Это админский платеж
        logger.info(f"🏦 Обнаружен админский платеж: {payment_request.payment_reference}")
        
        # Получаем данные админа из QR-кода
        admin_qr_code = db.query(AdminQRCode).filter(
            AdminQRCode.qr_token == payment_request.token
        ).first()
        
        if admin_qr_code:
            admin = admin_qr_code.admin
            admin_data = {
                "name": admin.organization_name or admin.full_name,
                "bank_name": admin.bank_name or "Демо Банк",
                "email": admin.email,
                "phone": admin.phone or "+996700123456",
                "is_admin": True
            }
            
            return templates.TemplateResponse("simulation/receiver_bank.html", get_simulation_template_context(
                request=request,
                merchant=admin_data,  # Передаем данные админа как merchant
                recent_payments=[],  # Для админа пока пустой список
                total_balance=50000.0,  # Больший баланс для админа
                page_title=f"Банк Получателя - {admin_data['name']}",
                is_admin=True
            ))
    
    # Обычный мерчантский платеж
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Получаем информацию о банке
    receiver_bank = None
    
    # Если передан параметр банка, используем его
    if bank:
        try:
            # Пробуем найти банк по ID
            bank_id = int(bank)
            receiver_bank = db.query(Bank).filter(Bank.id == bank_id).first()
        except ValueError:
            # Если не ID, то пробуем по коду
            receiver_bank = db.query(Bank).filter(Bank.code == bank).first()
    
    # Если банк не найден по параметру, используем банк из профиля продавца
    if not receiver_bank and merchant.bank_name:
        receiver_bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
    
    # Если банк все еще не найден, используем DEMO банк
    if not receiver_bank:
        receiver_bank = db.query(Bank).filter(Bank.code == "DEMO").first()
    
    # Получаем последние платежи (Unified)
    recent_payments = db.query(PaymentRequest).filter(
        PaymentRequest.merchant_id == merchant_id,
        PaymentRequest.status == TransactionStatus.COMPLETED
    ).order_by(PaymentRequest.created_at.desc()).limit(10).all()
    
    # Базовый баланс 10500 KGS
    total_balance = 10500.0
    
    # Создаем данные мерчанта с правильной информацией о банке
    merchant_data = {
        "id": merchant.id,
        "name": merchant.name,
        "bank_name": receiver_bank.name if receiver_bank else "Демо Банк",
        "bank_code": receiver_bank.code if receiver_bank else "DEMO",
        "email": merchant.email,
        "phone": merchant.phone,
        "is_admin": False
    }
    
    return templates.TemplateResponse("simulation/receiver_bank.html", get_simulation_template_context(
        request=request,
        merchant=merchant_data,
        recent_payments=recent_payments,
        total_balance=total_balance,
        page_title=f"Банк Получателя - {merchant.name}",
        is_admin=False
    ))

# === MOCK API БАНКОВ ===

@router.post("/bank-api/api/v1/banks/transactions/prepare")
async def mock_bank_prepare(
    request: TransactionPrepareRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    simulate_error: bool = Query(False, description="Simulate error response"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Подготовка транзакции (prepare phase)
    Симулирует ответ реального банка на запрос подготовки
    """
    
    logger.info(f"🏦 Mock Bank API: PREPARE для транзакции {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(1.0)
    
    # Симуляция ошибки
    if simulate_error:
        return TransactionPrepareResponse(
            status=TwoPhaseOperationStatus.ABORTED,
            transaction_id=request.transaction_id,
            message="Simulated bank error",
            error_code="INSUFFICIENT_FUNDS",
            error_details={"reason": "Account balance too low"}
        )
    
    # Успешный ответ
    reservation_id = f"RES_{secrets.token_hex(8)}"
    
    # Определяем тип банка для добавления в хранилище
    bank_type = "sender_bank" if request.bank_role == BankRole.SENDER else "receiver_bank"
    
    # Добавляем запрос в хранилище для отображения на страницах банков
    request_data = {
        "transaction_id": request.transaction_id,
        "amount": request.amount,
        "currency": request.currency,
        "phase": "prepare",
        "bank_role": request.bank_role.value,
        "payer_phone": getattr(request, 'payer_phone', '+996700123456'),
        "sender_account": getattr(request, 'sender_account', '1234567890123456'),
        "receiver_account": getattr(request, 'receiver_account', '0000000000000000')
    }
    
    # Добавляем запрос только если его еще нет
    request_id = add_bank_request(bank_type, request_data)
    
    # Логируем запрос для отображения на страницах банков
    logger.info(f"🏦 PREPARE запрос получен: {request.bank_role.value} банк, транзакция {request.transaction_id}, сумма {request.amount}")
    
    # Логируем событие PREPARE в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_prepare",
        title=f"PREPARE запрос - {request.bank_role.value} банк",
        description=f"Банк {request.bank_role.value} получил PREPARE запрос на сумму {request.amount} {request.currency}",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    response = TransactionPrepareResponse(
        status=TwoPhaseOperationStatus.PREPARED,
        transaction_id=request.transaction_id,
        message=f"Successfully prepared transaction for {request.bank_role.value} bank",
        reserved_amount=request.amount,
        reservation_id=reservation_id,
        expires_at=datetime.now()
    )
    
    logger.info(f"✅ Mock Bank PREPARE success: {request.bank_role.value} - {reservation_id}")
    return response

@router.post("/bank-api/api/v1/banks/transactions/commit")
async def mock_bank_commit(
    request: TransactionCommitRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    simulate_error: bool = Query(False, description="Simulate error response"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Фиксация транзакции (commit phase)
    Симулирует ответ реального банка на команду выполнения
    """
    
    logger.info(f"🏦 Mock Bank API: COMMIT для транзакции {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(0.7)
    
    # Симуляция ошибки
    if simulate_error:
        return TransactionCommitResponse(
            status=TwoPhaseOperationStatus.ERROR,
            transaction_id=request.transaction_id,
            message="Simulated commit error",
            error_code="NETWORK_ERROR",
            error_details={"reason": "Connection timeout"}
        )
    
    # Определяем тип банка для добавления в хранилище
    bank_type = "sender_bank" if request.bank_role == BankRole.SENDER else "receiver_bank"
    
    # Добавляем COMMIT запрос в хранилище
    request_data = {
        "transaction_id": request.transaction_id,
        "amount": request.prepared_amount,
        "currency": "KGS",
        "phase": "commit",
        "bank_role": request.bank_role.value,
        "payer_phone": "+996700123456",
        "sender_account": "1234567890123456",
        "receiver_account": "0000000000000000"
    }
    
    add_bank_request(bank_type, request_data)
    
    # Успешный ответ
    bank_tx_id = f"BTX_{secrets.token_hex(8)}"
    
    logger.info(f"🏦 COMMIT запрос получен: {request.bank_role.value} банк, транзакция {request.transaction_id}")
    
    # Логируем событие COMMIT в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_commit",
        title=f"COMMIT запрос - {request.bank_role.value} банк",
        description=f"Банк {request.bank_role.value} получил COMMIT запрос на сумму {request.prepared_amount} KGS",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    response = TransactionCommitResponse(
        status=TwoPhaseOperationStatus.COMMITTED,
        transaction_id=request.transaction_id,
        message=f"Successfully committed transaction for {request.bank_role.value} bank",
        actual_amount=request.prepared_amount,
        bank_transaction_id=bank_tx_id,
        completed_at=datetime.now()
    )
    
    logger.info(f"✅ Mock Bank COMMIT success: {request.bank_role.value} - {bank_tx_id}")
    return response

@router.post("/bank-api/api/v1/banks/transactions/abort")
async def mock_bank_abort(
    request: TransactionAbortRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Отмена транзакции (abort phase)
    Симулирует ответ реального банка на команду отмены
    """
    
    logger.info(f"🏦 Mock Bank API: ABORT для транзакции {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(0.3)
    
    # Успешный ответ (abort почти всегда успешен)
    response = TransactionAbortResponse(
        status=TwoPhaseOperationStatus.ABORTED,
        transaction_id=request.transaction_id,
        message=f"Successfully aborted transaction for {request.bank_role.value} bank",
        released_amount=1000.0,  # Placeholder
        released_at=datetime.now()
    )
    
    # Логируем событие ABORT в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_abort",
        title=f"ABORT запрос - {request.bank_role.value} банк",
        description=f"Банк {request.bank_role.value} получил ABORT запрос",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    logger.info(f"✅ Mock Bank ABORT success: {request.bank_role.value}")
    return response

# === MOCK API ДЛЯ ВОЗВРАТОВ ===

@router.post("/bank-api/api/v1/banks/refunds/prepare")
async def mock_bank_refund_prepare(
    request: RefundPrepareRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    simulate_error: bool = Query(False, description="Simulate error response"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Подготовка возврата (prepare phase)
    Симулирует ответ реального банка на запрос подготовки возврата
    """
    
    logger.info(f"🏦 Mock Bank API: REFUND PREPARE для возврата {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(1.0)
    
    # Симуляция ошибки
    if simulate_error:
        return RefundPrepareResponse(
            status=TwoPhaseOperationStatus.ABORTED,
            transaction_id=request.transaction_id,
            message="Simulated refund error",
            error_code="INSUFFICIENT_FUNDS",
            error_details={"reason": "Account balance too low for refund"}
        )
    
    # Успешный ответ
    reservation_id = f"REFUND_RES_{secrets.token_hex(8)}"
    
    # Определяем тип банка для добавления в хранилище
    bank_role_str = request.bank_role.value if hasattr(request.bank_role, 'value') else str(request.bank_role)
    bank_type = "sender_bank" if request.bank_role == BankRole.SENDER else "receiver_bank"
    
    # Добавляем запрос в хранилище для отображения на страницах банков
    request_data = {
        "transaction_id": request.transaction_id,
        "refund_token": request.refund_token,
        "original_payment_id": request.original_payment_id,
        "reason": request.reason,
        "amount": request.amount,
        "currency": request.currency,
        "phase": "refund_prepare",
        "bank_role": bank_role_str,
        "payer_phone": getattr(request, 'payer_phone', '+996700123456'),
        "sender_account": getattr(request, 'sender_account', '1234567890123456'),
        "receiver_account": getattr(request, 'receiver_account', '0000000000000000')
    }
    
    # Добавляем запрос только если его еще нет
    request_id = add_bank_request(bank_type, request_data)
    
    # Логируем запрос для отображения на страницах банков
    logger.info(f"🏦 REFUND PREPARE запрос получен: {bank_role_str} банк, возврат {request.transaction_id}, сумма {request.amount}")
    
    # Логируем событие PREPARE в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_refund_prepare",
        title=f"REFUND PREPARE запрос - {bank_role_str} банк",
        description=f"Банк {bank_role_str} получил REFUND PREPARE запрос на сумму {request.amount} {request.currency}",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    response = RefundPrepareResponse(
        status=TwoPhaseOperationStatus.PREPARED,
        transaction_id=request.transaction_id,
        message=f"Successfully prepared refund for {bank_role_str} bank",
        reserved_amount=request.amount,
        reservation_id=reservation_id,
        expires_at=datetime.now()
    )
    
    logger.info(f"✅ Mock Bank REFUND PREPARE success: {bank_role_str} - {reservation_id}")
    return response

@router.post("/bank-api/api/v1/banks/refunds/commit")
async def mock_bank_refund_commit(
    request: RefundCommitRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    simulate_error: bool = Query(False, description="Simulate error response"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Фиксация возврата (commit phase)
    Симулирует ответ реального банка на команду выполнения возврата
    """
    
    logger.info(f"🏦 Mock Bank API: REFUND COMMIT для возврата {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(0.7)
    
    # Симуляция ошибки
    if simulate_error:
        return RefundCommitResponse(
            status=TwoPhaseOperationStatus.ERROR,
            transaction_id=request.transaction_id,
            message="Simulated refund commit error",
            error_code="NETWORK_ERROR",
            error_details={"reason": "Connection timeout during refund"}
        )
    
    # Определяем тип банка для добавления в хранилище
    bank_role_str = request.bank_role.value if hasattr(request.bank_role, 'value') else str(request.bank_role)
    bank_type = "sender_bank" if request.bank_role == BankRole.SENDER else "receiver_bank"
    
    # Добавляем COMMIT запрос в хранилище
    request_data = {
        "transaction_id": request.transaction_id,
        "refund_token": request.refund_token,
        "original_payment_id": request.original_payment_id,
        "amount": request.prepared_amount,
        "currency": "KGS",
        "phase": "refund_commit",
        "bank_role": bank_role_str,
        "payer_phone": "+996700123456",
        "sender_account": "1234567890123456",
        "receiver_account": "0000000000000000"
    }
    
    add_bank_request(bank_type, request_data)
    
    # Успешный ответ
    bank_tx_id = f"REFUND_BTX_{secrets.token_hex(8)}"
    
    logger.info(f"🏦 REFUND COMMIT запрос получен: {bank_role_str} банк, возврат {request.transaction_id}")
    
    # Логируем событие COMMIT в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_refund_commit",
        title=f"REFUND COMMIT запрос - {bank_role_str} банк",
        description=f"Банк {bank_role_str} получил REFUND COMMIT запрос на сумму {request.prepared_amount} KGS",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    response = RefundCommitResponse(
        status=TwoPhaseOperationStatus.COMMITTED,
        transaction_id=request.transaction_id,
        message=f"Successfully committed refund for {bank_role_str} bank",
        actual_amount=request.prepared_amount,
        bank_transaction_id=bank_tx_id,
        completed_at=datetime.now()
    )
    
    logger.info(f"✅ Mock Bank REFUND COMMIT success: {bank_role_str} - {bank_tx_id}")
    return response

@router.post("/bank-api/api/v1/banks/refunds/abort")
async def mock_bank_refund_abort(
    request: RefundAbortRequest,
    simulate_delay: bool = Query(False, description="Simulate network delay"),
    db: Session = Depends(get_db)
):
    """
    Mock API: Отмена возврата (abort phase)
    Симулирует ответ реального банка на команду отмены возврата
    """
    
    logger.info(f"🏦 Mock Bank API: REFUND ABORT для возврата {request.transaction_id}")
    
    # Симуляция сетевой задержки
    if simulate_delay:
        await asyncio.sleep(0.3)
    
    # Успешный ответ (abort почти всегда успешен)
    bank_role_str = request.bank_role.value if hasattr(request.bank_role, 'value') else str(request.bank_role)
    response = RefundAbortResponse(
        status=TwoPhaseOperationStatus.ABORTED,
        transaction_id=request.transaction_id,
        message=f"Successfully aborted refund for {bank_role_str} bank",
        released_amount=1000.0,  # Placeholder
        released_at=datetime.now()
    )
    
    # Логируем событие ABORT в таймлайн
    TimelineService.record_event(
        db=db,
        transaction_id=request.transaction_id,
        event_type="bank_refund_abort",
        title=f"REFUND ABORT запрос - {bank_role_str} банк",
        description=f"Банк {bank_role_str} получил REFUND ABORT запрос",
        actor="bank",
        source="simulation",
        status="success"
    )
    
    logger.info(f"✅ Mock Bank REFUND ABORT success: {bank_role_str}")
    return response

# === API ДЛЯ ПОЛУЧЕНИЯ ЛОГОВ ===

# Глобальное хранилище активных запросов для симулятора
active_requests = {
    "sender_bank": [],
    "receiver_bank": []
}

def add_bank_request(bank_type, request_data):
    """Добавляет запрос в список активных для банка"""
    # Проверяем, не существует ли уже запрос с таким transaction_id и phase
    existing_request = next(
        (req for req in active_requests[bank_type] 
         if req.get("transaction_id") == request_data.get("transaction_id") 
         and req.get("phase") == request_data.get("phase")), 
        None
    )
    
    if existing_request:
        logger.info(f"📝 Запрос уже существует для {bank_type}: {request_data.get('transaction_id')} {request_data.get('phase')}")
        return existing_request["id"]
    
    request_id = f"REQ_{secrets.token_hex(4)}"
    request_data["id"] = request_id
    request_data["timestamp"] = datetime.now().isoformat()
    request_data["status"] = "pending"
    
    active_requests[bank_type].append(request_data)
    logger.info(f"📝 Добавлен запрос {request_id} для {bank_type}: {request_data}")
    return request_id

def update_request_status(bank_type, request_id, status, response_data=None):
    """Обновляет статус запроса"""
    for req in active_requests[bank_type]:
        if req["id"] == request_id:
            req["status"] = status
            if response_data:
                req["response"] = response_data
            logger.info(f"📝 Обновлен статус запроса {request_id} для {bank_type}: {status}")
            break

def cleanup_old_requests():
    """Очищает старые запросы (старше 1 часа)"""
    current_time = datetime.now()
    for bank_type in active_requests:
        active_requests[bank_type] = [
            req for req in active_requests[bank_type]
            if (current_time - datetime.fromisoformat(req["timestamp"])).total_seconds() < 3600
        ]

@router.get("/api/payment/{payment_token}/logs")
async def get_transaction_logs(
    payment_token: str,
    db: Session = Depends(get_db)
):
    """
    API для получения логов двухфазной транзакции в реальном времени
    Используется JavaScript'ом на странице симулятора для live-обновлений
    """
    
    # Извлекаем UUID из токена
    token_uuid = SecureTokenService.extract_uuid_from_token(payment_token)
    if not token_uuid:
        token_uuid = payment_token  # Если это уже UUID
    
    # Получаем все операции для данного платежа
    operations = db.query(TwoPhaseOperation).filter(
        TwoPhaseOperation.payment_token == token_uuid
    ).order_by(TwoPhaseOperation.started_at.asc()).all()
    
    # Получаем информацию о платеже
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.token == token_uuid
    ).first()
    
    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Формируем логи для фронтенда
    logs = []
    
    # Добавляем статус самого платежа
    logs.append({
        "timestamp": payment_request.created_at.isoformat() if payment_request.created_at else None,
        "level": "info",
        "message": f"Платежный запрос создан: {payment_request.payment_reference}",
        "details": {
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "status": payment_request.status.value if payment_request.status else "unknown"
        }
    })
    
    # Добавляем логи операций
    for op in operations:
        level = "success" if op.response_status in ["prepared", "committed", "aborted"] else "error"
        if op.error_message:
            level = "error"
        
        message = f"{op.phase.upper()} {op.operation_type} -> {op.bank_code} ({op.bank_role})"
        if op.response_status:
            message += f" = {op.response_status}"
        
        logs.append({
            "timestamp": op.started_at.isoformat() if op.started_at else None,
            "level": level,
            "message": message,
            "details": {
                "phase": op.phase,
                "operation_type": op.operation_type,
                "bank_code": op.bank_code,
                "bank_role": op.bank_role,
                "response_status": op.response_status,
                "duration_ms": op.duration_ms,
                "error_message": op.error_message
            }
        })
    
    return {
        "payment_reference": payment_request.payment_reference,
        "current_status": payment_request.status.value if payment_request.status else "unknown",
        "transaction_id": f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
        "logs": logs,
        "total_logs": len(logs),
        "last_updated": datetime.now().isoformat()
    }

@router.get("/api/bank-requests/{bank_type}")
async def get_bank_requests(bank_type: str):
    """
    API для получения активных запросов для банка
    """
    if bank_type not in active_requests:
        raise HTTPException(status_code=400, detail="Invalid bank type")
    
    # Очищаем старые запросы
    cleanup_old_requests()
    
    return {
        "bank_type": bank_type,
        "requests": active_requests[bank_type],
        "total_requests": len(active_requests[bank_type])
    }

@router.post("/api/bank-requests/{bank_type}/{request_id}/respond")
async def respond_to_request(
    bank_type: str,
    request_id: str,
    response: dict
):
    """
    API для ответа на запрос банка (принять/отклонить)
    """
    if bank_type not in active_requests:
        raise HTTPException(status_code=400, detail="Invalid bank type")
    
    # Находим запрос
    request_found = False
    for req in active_requests[bank_type]:
        if req["id"] == request_id:
            req["status"] = response.get("status", "accepted")
            req["response"] = response
            # Добавляем флаг подтверждения для мониторинга
            if response.get("confirmed", False):
                req["confirmed"] = True
            request_found = True
            break
    
    if not request_found:
        raise HTTPException(status_code=404, detail="Request not found")
    
    logger.info(f"🏦 Ответ на запрос {request_id} от {bank_type}: {response}")
    
    return {"success": True, "message": "Response recorded"}

@router.get("/api/merchant/{merchant_id}/balance")
async def get_merchant_balance(
    merchant_id: int,
    db: Session = Depends(get_db)
):
    """
    API для получения баланса продавца в реальном времени
    Используется для обновления интерфейса банка-получателя
    """
    
    from app.models.merchant import Merchant, MerchantPayment
    
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Получаем последние платежи
    recent_payments = db.query(PaymentRequest).filter(
        PaymentRequest.merchant_id == merchant_id,
        PaymentRequest.status == TransactionStatus.COMPLETED
    ).order_by(PaymentRequest.created_at.desc()).limit(5).all()
    
    # Базовый баланс 10500 KGS
    total_balance = 10500.0
    
    return {
        "merchant_id": merchant_id,
        "merchant_name": merchant.name,
        "balance": total_balance,
        "currency": "KGS",
        "recent_payments": [
            {
                "amount": payment.amount,
                "transaction_id": payment.transaction_id,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "payer_phone": payment.payer_phone
            }
            for payment in recent_payments
        ],
        "last_updated": datetime.now().isoformat()
    }

# === УТИЛИТАРНЫЕ ЭНДПОИНТЫ ===

from pydantic import BaseModel

class PaymentCompletionRequest(BaseModel):
    merchant_id: int
    amount: float
    currency: str = "KGS"
    sender_bank_code: Optional[str] = "DEMO"
    sender_account: Optional[str] = "1234567890123456"

# Глобальное хранилище для отслеживания активных транзакций
active_transactions = set()

@router.post("/api/simulate-two-phase-payment")
async def simulate_two_phase_payment(
    request: PaymentCompletionRequest,
    db: Session = Depends(get_db)
):
    """
    Специальный эндпоинт для симулятора - запускает двухфазную транзакцию
    """
    # Создаем уникальный ключ для транзакции
    transaction_key = f"{request.merchant_id}_{request.amount}_{int(datetime.now().timestamp())}"
    
    # Проверяем, не выполняется ли уже такая транзакция
    if transaction_key in active_transactions:
        logger.warning(f"🔄 Дублирующий запрос на двухфазную транзакцию: {transaction_key}")
        return {
            "success": False,
            "error": "Транзакция уже выполняется",
            "message": "Пожалуйста, подождите завершения текущей транзакции"
        }
    
    # Добавляем транзакцию в активные
    active_transactions.add(transaction_key)
    
    logger.info(f"🔄 Симуляция двухфазной транзакции: продавец {request.merchant_id}, сумма {request.amount}")
    
    try:
        # Получаем информацию о продавце для определения банка-получателя
        from app.models.merchant import Merchant
        merchant = db.query(Merchant).filter(Merchant.id == request.merchant_id).first()
        
        # Определяем банк-получатель из профиля продавца
        receiver_bank_code = "DEMO"  # По умолчанию
        receiver_account = "1234567890123456"  # По умолчанию
        receiver_name = "Демо Получатель"  # По умолчанию
        
        if merchant and merchant.bank_name:
            # Ищем банк по названию
            receiver_bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
            if receiver_bank:
                receiver_bank_code = receiver_bank.code
                receiver_account = merchant.bank_account or "1234567890123456"
                receiver_name = merchant.name or "Демо Получатель"
        
        # Создаем PaymentRequest для симуляции
        payment_request = PaymentRequest(
            token=f"SIM_{secrets.token_hex(8)}",
            receiver_account=receiver_account,
            receiver_bank_code=receiver_bank_code,
            receiver_name=receiver_name,
            description=f"Симуляция платежа на {request.amount} KGS",
            amount=request.amount,
            currency="KGS",
            payment_reference=f"SIM_{secrets.token_hex(4)}",
            expires_at=datetime.now() + timedelta(hours=24),
            merchant_id=request.merchant_id,
            status=TransactionStatus.PENDING,
            sender_bank_code=request.sender_bank_code,
            payer_bank_code=request.sender_bank_code,  # Банк плательщика = банк отправителя
            sender_account=request.sender_account  # Счет плательщика из запроса
        )
        
        db.add(payment_request)
        db.commit()
        db.refresh(payment_request)
        
        # Создаем запись MerchantPayment в статусе "pending"
        from app.models.merchant import MerchantPayment
        merchant_payment = MerchantPayment(
            merchant_id=request.merchant_id,
            qr_code_id=None,  # Будет заполнено позже, если найден QR-код
            amount=request.amount,
            currency=request.currency,
            status="pending",  # Начинаем с pending
            payer_phone="+996700123456",
            payer_bank_code=request.sender_bank_code,
            sender_account=request.sender_account,
            transaction_id=f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
            created_at=datetime.now()
        )
        
        db.add(merchant_payment)
        db.commit()
        db.refresh(merchant_payment)
        
        # Логируем создание платежного запроса
        TimelineService.record_event(
            db=db,
            payment_token=payment_request.token,
            transaction_id=f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
            event_type="payment_request_created",
            title="Создание платежного запроса",
            description=f"Создан платеж на сумму {payment_request.amount} {payment_request.currency}",
            actor="system",
            source="simulation",
            status="success"
        )
        
        # Логируем событие инициации двухфазной транзакции
        TimelineService.record_event(
            db=db,
            payment_token=payment_request.token,
            transaction_id=f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
            event_type="two_phase_initiated",
            title="Двухфазная транзакция инициирована",
            description=f"Инициирована двухфазная транзакция на сумму {payment_request.amount} {payment_request.currency}",
            actor="system",
            source="simulation",
            status="success"
        )
        
        # Запускаем двухфазную транзакцию
        result = await two_phase_commit_service.execute_transaction(
            db=db,
            payment_request=payment_request,
            sender_bank_code=request.sender_bank_code,
            payer_phone="+996700123456",
            sender_account=request.sender_account
        )
        
        logger.info(f"✅ Двухфазная транзакция завершена: {result}")
        
        # НЕ обновляем запись MerchantPayment здесь - оставляем статус "pending"
        # Обновление произойдет в finalize-payment
        if result.get("success"):
            logger.info(f"✅ Двухфазная транзакция выполнена успешно, запись остается в статусе 'pending'")
        else:
            logger.error(f"❌ Двухфазная транзакция не выполнена")
        
        # Удаляем транзакцию из активных
        active_transactions.discard(transaction_key)
        
        return {
            "success": True,
            "transaction_id": f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}",
            "amount": request.amount,
            "status": "completed",
            "message": "Транзакция успешно выполнена"
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка двухфазной транзакции: {e}")
        
        # Удаляем транзакцию из активных даже при ошибке
        active_transactions.discard(transaction_key)
        
        return {
            "success": False,
            "error": str(e),
            "message": "Ошибка выполнения транзакции"
        }

@router.post("/api/simulate-payment-completion")
async def simulate_payment_completion(
    request: PaymentCompletionRequest,
    db: Session = Depends(get_db)
):
    """
    Симуляция завершения платежа - уменьшает баланс продавца
    """
    from app.models.merchant import MerchantPayment
    
    logger.info(f"💰 Симуляция завершения платежа: продавец {request.merchant_id}, сумма {request.amount}")
    
    # Создаем запись о платеже
    payment = MerchantPayment(
        merchant_id=request.merchant_id,
        amount=request.amount,
        status="completed",
        transaction_id=f"SIM_{secrets.token_hex(8)}",
        payer_phone="+996700123456",
        created_at=datetime.now(),
        paid_at=datetime.now(),  # Заполняем время оплаты
        payer_bank_code=getattr(request, 'sender_bank_code', "DEMO"),
        sender_account=getattr(request, 'sender_account', "1234567890123456"),
        currency=getattr(request, 'currency', "KGS")
    )
    
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    # Логируем событие завершения платежа
    TimelineService.record_event(
        db=db,
        transaction_id=payment.transaction_id,
        event_type="payment_completed",
        title="Платеж завершен",
        description=f"Платеж на сумму {payment.amount} {payment.currency} успешно завершен",
        actor="system",
        source="simulation",
        status="success"
    )
    
    logger.info(f"✅ Платеж записан: {payment.transaction_id}")
    
    return {
        "success": True,
        "transaction_id": payment.transaction_id,
        "amount": request.amount,
        "status": "completed"
    }

@router.post("/api/finalize-payment")
async def finalize_payment(
    request: PaymentCompletionRequest,
    db: Session = Depends(get_db)
):
    """
    Финальное завершение платежа - списывает баланс только при подтверждении пользователем
    """
    from app.models.merchant import MerchantPayment
    
    logger.info(f"💰 Финальное завершение платежа: продавец {request.merchant_id}, сумма {request.amount}")
    
    try:
        # Находим QR-код и торговую точку для получения дополнительной информации
        qr_code = None
        trading_point = None
        
        try:
            # Ищем QR-код по merchant_id и сумме
            qr_code = db.query(QRCode).filter(
                QRCode.merchant_id == request.merchant_id,
                QRCode.amount == request.amount
            ).first()
            
            # Если не найден по сумме, ищем любой QR-код продавца
            if not qr_code:
                qr_code = db.query(QRCode).filter(
                    QRCode.merchant_id == request.merchant_id
                ).first()
            
            # Ищем торговую точку продавца
            if qr_code:
                trading_point = db.query(TradingPoint).filter(
                    TradingPoint.merchant_id == request.merchant_id
                ).first()
        except Exception as e:
            logger.warning(f"Не удалось найти QR-код или торговую точку: {e}")
        
        # Находим существующий PaymentRequest для обновления
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.merchant_id == request.merchant_id,
            PaymentRequest.amount == request.amount,
            PaymentRequest.status == TransactionStatus.PENDING
        ).order_by(PaymentRequest.created_at.desc()).first()
        
        if payment_request:
            # Обновляем существующий PaymentRequest
            payment_request.status = TransactionStatus.COMPLETED
            payment_request.paid_at = datetime.now()
            payment_request.payer_phone = "+996700123456"
            payment_request.payer_bank_code = request.sender_bank_code
            payment_request.qr_code_id = qr_code.id if qr_code else None
            payment_request.outlet_id = trading_point.id if trading_point else None
            
            db.commit()
            db.refresh(payment_request)
            
            transaction_id = f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}"
            
            # Ищем существующую запись MerchantPayment для обновления
            # Сначала ищем по transaction_id, который должен совпадать с PaymentRequest
            existing_merchant_payment = db.query(MerchantPayment).filter(
                MerchantPayment.transaction_id == transaction_id,
                MerchantPayment.merchant_id == request.merchant_id
            ).first()
            
            # Если не найдено по transaction_id, ищем по merchant_id и amount
            if not existing_merchant_payment:
                existing_merchant_payment = db.query(MerchantPayment).filter(
                    MerchantPayment.merchant_id == request.merchant_id,
                    MerchantPayment.amount == request.amount,
                    MerchantPayment.status.in_(["pending", "completed"])
                ).order_by(MerchantPayment.created_at.desc()).first()
            
            logger.info(f"🔍 Поиск существующей записи: merchant_id={request.merchant_id}, amount={request.amount}, transaction_id={transaction_id}")
            logger.info(f"🔍 Найдено записей: {existing_merchant_payment is not None}")
            if existing_merchant_payment:
                logger.info(f"🔍 Найдена запись: ID={existing_merchant_payment.id}, статус={existing_merchant_payment.status}, transaction_id={existing_merchant_payment.transaction_id}")
            
            if existing_merchant_payment:
                # Обновляем существующую запись
                existing_merchant_payment.status = "completed"
                existing_merchant_payment.paid_at = datetime.now()
                existing_merchant_payment.payer_bank_code = request.sender_bank_code
                existing_merchant_payment.sender_account = getattr(request, 'sender_account', "1234567890123456")
                existing_merchant_payment.qr_code_id = qr_code.id if qr_code else existing_merchant_payment.qr_code_id
                existing_merchant_payment.outlet_id = trading_point.id if trading_point else existing_merchant_payment.outlet_id
                db.commit()
                
                merchant_payment = existing_merchant_payment
                logger.info(f"✅ Обновлена существующая запись MerchantPayment: {merchant_payment.id}")
            else:
                # Создаем новую запись только если не найдена существующая
                merchant_payment = MerchantPayment(
                    merchant_id=request.merchant_id,
                    amount=request.amount,
                    status="completed",
                    transaction_id=f"FINAL_{secrets.token_hex(8)}",
                    payer_phone="+996700123456",
                    created_at=datetime.now(),
                    paid_at=datetime.now(),
                    qr_code_id=qr_code.id if qr_code else None,
                    outlet_id=trading_point.id if trading_point else None,
                    payer_bank_code=request.sender_bank_code,
                    sender_account=getattr(request, 'sender_account', "1234567890123456"),
                    currency="KGS"
                )
                
                db.add(merchant_payment)
                db.commit()
                db.refresh(merchant_payment)
                
                logger.info(f"✅ Создана новая запись в MerchantPayment: ID={merchant_payment.id}")
        else:
            # Если PaymentRequest не найден, создаем новый MerchantPayment
            payment = MerchantPayment(
                merchant_id=request.merchant_id,
                amount=request.amount,
                status="completed",
                transaction_id=f"FINAL_{secrets.token_hex(8)}",
                payer_phone="+996700123456",
                created_at=datetime.now(),
                paid_at=datetime.now(),
                qr_code_id=qr_code.id if qr_code else None,
                outlet_id=trading_point.id if trading_point else None,
                payer_bank_code=request.sender_bank_code,
                sender_account=getattr(request, 'sender_account', "1234567890123456"),
                currency="KGS"
            )
            
            db.add(payment)
            db.commit()
            db.refresh(payment)
            
            transaction_id = payment.transaction_id
        
        # Находим соответствующий PaymentRequest для правильного transaction_id
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.merchant_id == request.merchant_id,
            PaymentRequest.amount == request.amount
        ).order_by(PaymentRequest.created_at.desc()).first()
        
        # Логируем событие завершения платежа
        if payment_request:
            # Если обновляли PaymentRequest
            TimelineService.record_event(
                db=db,
                transaction_id=transaction_id,
                event_type="payment_completed",
                title="Платеж завершен",
                description=f"Платеж на сумму {request.amount} KGS успешно завершен",
                actor="system",
                source="simulation",
                status="success"
            )
            logger.info(f"✅ Платеж записан в БД: {transaction_id}")
        else:
            # Если создавали MerchantPayment
            TimelineService.record_event(
                db=db,
                transaction_id=transaction_id,
                event_type="payment_completed",
                title="Платеж завершен",
                description=f"Платеж на сумму {request.amount} KGS успешно завершен",
                actor="system",
                source="simulation",
                status="success"
            )
            logger.info(f"✅ Платеж записан в БД: {transaction_id}")
        
        # Помечаем QR-код как использованный
        try:
            # Находим QR-код по merchant_id и сумме
            qr_code = db.query(QRCode).filter(
                QRCode.merchant_id == request.merchant_id,
                QRCode.amount == request.amount
            ).first()
            
            if qr_code:
                qr_code.current_uses += 1
                db.commit()
                logger.info(f"✅ QR-код использован: {qr_code.name} (использований: {qr_code.current_uses})")
        except Exception as e:
            logger.warning(f"Не удалось обновить счетчик использования QR-кода: {e}")
        
        return {
            "success": True,
            "message": f"Баланс списан: {request.amount} KGS",
            "amount": request.amount,
            "status": "finalized",
            "transaction_id": transaction_id
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи платежа: {e}")
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": "Ошибка записи платежа"
        }

@router.post("/api/configure-mock-banks")
async def configure_mock_banks(
    db: Session = Depends(get_db),
    enable_simulation: bool = Query(True, description="Enable simulation mode")
):
    """
    Настройка банков для использования mock API симулятора
    Изменяет webhook_url банков на эндпоинты симулятора
    """
    
    if not enable_simulation:
        logger.info("🔄 Отключение режима симуляции банков")
        # Возвращаем оригинальные URL
        banks = db.query(Bank).all()
        for bank in banks:
            if bank.webhook_url and "simulation" in bank.webhook_url:
                # Возвращаем к стандартному формату
                bank.webhook_url = f"https://api.{bank.code.lower()}.bank"
        db.commit()
        return {"message": "Simulation mode disabled", "affected_banks": len(banks)}
    
    logger.info("🔄 Настройка банков для режима симуляции")
    
    # Получаем базовый URL приложения
    base_url = get_simulation_url()
    
    banks = db.query(Bank).all()
    for bank in banks:
        # Устанавливаем URL на наш mock API
        bank.webhook_url = f"{base_url}/bank-api"
        logger.info(f"🏦 Банк {bank.code} настроен на mock API: {bank.webhook_url}")
    
    db.commit()
    
    return {
        "message": "Banks configured for simulation mode",
        "affected_banks": len(banks),
        "mock_api_base": base_url
    }

# Подключаем банковский API
router.include_router(bank_api_router)
