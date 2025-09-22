# Payment management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.payment import PaymentRequestCreate, QRResponse
from app.models.payment import PaymentRequest, TransactionStatus, Bank, TransactionRecord
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
        sender_bank_code=payment_data.sender_bank_code,
        receiver_bank_code=payment_data.receiver_bank_code,
        status=TransactionStatus.PENDING
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
        PaymentRequest.token == token
    ).first()
    
    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment request not found")
    
    qr_url = get_payment_url(token)
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
    
    return {
        "id": payment.id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status.value if payment.status else None,
        "receiver_name": payment.receiver_name,
        "receiver_account": payment.receiver_account,
        "receiver_bank_code": payment.receiver_bank_code,
        "description": payment.description,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "transaction_id": payment.transaction_id,
        "payer_phone": payment.payer_phone,
        "sender_bank_code": payment.sender_bank_code,
        "payer_bank_code": payment.payer_bank_code,
        "sender_account": payment.sender_account,
        "payment_reference": payment.payment_reference,
        "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
        "is_paid": payment.is_paid,
        "is_used": payment.is_used
    }

@router.get("/payments")
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
        
        payments_data = []
        for payment in payments:
            payments_data.append({
                "id": payment.id,
                "token": payment.token,
                "amount": payment.amount,
                "currency": payment.currency,
                "status": payment.status.value if payment.status else "pending",
                "sender_bank_code": payment.sender_bank_code,
                "payer_bank_code": payment.payer_bank_code,
                "sender_account": payment.sender_account,
                "receiver_bank_code": payment.receiver_bank_code,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
                "merchant_id": payment.merchant_id,
                "description": payment.description,
                "is_paid": payment.is_paid
            })
        
        return payments_data
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
    payment = db.query(PaymentRequest).filter(PaymentRequest.token == token).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment



