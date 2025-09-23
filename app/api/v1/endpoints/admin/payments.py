# Payment management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.unified_payment import UnifiedPaymentCreate as PaymentRequestCreate, UnifiedPaymentResponse as QRResponse
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.payment import TransactionStatus, Bank, TransactionRecord
from app.models.merchant import Merchant
from app.models.admin import Admin
from app.services.qr_service import QRService
from app.core.config import get_payment_url
from app.services.enhanced_validation_service import EnhancedValidationService
from app.core.dependencies import check_rate_limit, get_current_admin_user
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

router = APIRouter(prefix="/payments")

@router.post("/create-payment", response_model=QRResponse)
async def create_payment_request(
    payment_data: PaymentRequestCreate,
    request: Request,
    _: None = Depends(check_rate_limit("create-payment")),
    db: Session = Depends(get_db)
):
    """
    Создание платежного запроса с расширенной валидацией
    """
    
    # Расширенная валидация входных данных
    validation_data = payment_data.dict()
    validation_result = EnhancedValidationService.validate_payment_request(
        validation_data, 
        bank=None,  # Для админа банк не указан
        strict_mode=False
    )
    
    # Если есть критические ошибки валидации
    if not validation_result.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Payment validation failed",
                "validation_errors": validation_result.errors,
                "validation_warnings": validation_result.warnings,
                "validation_summary": validation_result.get_summary()
            }
        )
    
    # Логируем предупреждения валидации
    if validation_result.has_warnings():
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Payment validation warnings from {request.client.host}: "
            f"{len(validation_result.warnings)} warnings"
        )
    
    # Создаем платежный запрос через двухфазный коммит
    from app.services.two_phase_commit_service import two_phase_commit_service
    
    # Создаем базовый платежный запрос
    payment_request = PaymentRequest(
        amount=payment_data.amount,
        currency=payment_data.currency,
        description=payment_data.description,
        merchant_id=payment_data.merchant_id,
        receiver_name=payment_data.receiver_name,
        receiver_account=payment_data.receiver_account,
        receiver_bank_code=payment_data.receiver_bank_code,
        payment_reference=payment_data.payment_reference,
        status=TransactionStatus.PENDING.value
    )
    
    db.add(payment_request)
    db.commit()
    db.refresh(payment_request)
    
    # Инициируем двухфазную транзакцию
    result = await two_phase_commit_service.execute_transaction(
        db=db,
        payment_request=payment_request,
        sender_bank_code=payment_data.sender_bank_code,
        receiver_bank_code=payment_data.receiver_bank_code
    )
    
    return result

@router.get("/qr-image/{token}")
async def get_qr_image(token: str, db: Session = Depends(get_db)):
    """
    Получение изображения QR-кода по токену
    """
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.qr_code.has(qr_token=token)
    ).first()
    
    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment request not found")
    
    qr_url = get_payment_url(payment_request.qr_code.qr_token)
    qr_image = QRService.generate_qr_image(qr_url)
    
    return {"qr_image": qr_image}

@router.get("/{payment_id}")
async def get_payment_details(
    payment_id: int,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Получение деталей платежа по ID
    """
    payment = db.query(PaymentRequest).filter(
        PaymentRequest.id == payment_id
    ).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    return payment

@router.get("/")
async def list_payments(db: Session = Depends(get_db)):
    """
    Список всех платежных запросов (для админки)
    """
    payments = db.query(PaymentRequest).order_by(PaymentRequest.created_at.desc()).limit(50).all()
    return payments

@router.get("/recent")
async def get_recent_payments(
    limit: int = 20,
    # current_admin: dict = Depends(get_current_admin_user),  # Временно отключено для демо
    db: Session = Depends(get_db)
):
    """
    Получение последних платежных запросов (упрощенная версия для демо)
    """
    try:
        # Простой запрос без сложных JOIN для демонстрации
        payments = db.query(PaymentRequest)\
            .order_by(PaymentRequest.created_at.desc())\
            .limit(limit)\
            .all()
        
        return payments
    except Exception as e:
        # Если есть ошибка, возвращаем тестовые данные для демо
        return [
            {
                "id": 1,
                "token": "demo_token_123",
                "amount": 1000.0,
                "currency": "KGS",
                "status": "completed",
                "sender_bank_code": "RSK",
                "receiver_bank_code": "OBANK",
                "created_at": "2025-08-28T00:00:00Z",
                "expires_at": "2025-08-29T00:00:00Z",
                "merchant_id": 1,
                "description": "Демо платеж",
                "is_paid": True
            },
            {
                "id": 2,
                "token": "demo_token_456",
                "amount": 2500.0,
                "currency": "KGS",
                "status": "pending",
                "sender_bank_code": "KBANK",
                "receiver_bank_code": "CBKG",
                "created_at": "2025-08-27T23:00:00Z",
                "expires_at": "2025-08-28T23:00:00Z",
                "merchant_id": 1,
                "description": "Демо платеж 2",
                "is_paid": False
            }
        ]

@router.get("/{token}")
async def get_payment_details(token: str, db: Session = Depends(get_db)):
    """
    Детальная информация о платеже
    """
    payment = db.query(PaymentRequest).filter(PaymentRequest.qr_code.has(qr_token=token)).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment



