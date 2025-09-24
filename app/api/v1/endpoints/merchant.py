"""
API эндпоинты для работы с продавцами (Merchant API)
Полностью рефакторинг с использованием аутентификации и сервисного слоя
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta, date
import logging

from app.database import get_db
from app.models.merchant import (
    Merchant, QRCode, MerchantPayment, MerchantSettings, TradingPoint
)
from app.models.payment import Bank


from app.schemas.merchant import (
    MerchantRegister, MerchantLogin, MerchantResponse, MerchantLoginResponse,
    MerchantPaymentResponse, MerchantSettingsUpdate, MerchantSettingsResponse,
    MerchantStats, PaymentSummary, MerchantProfileUpdate
)
from app.schemas.unified import UnifiedQRCodeCreate, UnifiedQRCodeRead
from app.core.merchant_dependencies import (
    get_current_merchant, get_verified_merchant,
    get_merchant_for_payments, get_merchant_for_reports, get_merchant_for_settings
)
from app.services.merchant_auth_service import MerchantAuthService
from app.services.merchant_payment_service import MerchantPaymentService
from app.services.merchant_outlet_service import MerchantOutletService
from app.services.qr_service import QRService
from app.services.error_handling_service import ErrorHandlingService, ErrorCode
from app.core.config import settings
from pydantic import BaseModel
import secrets


logger = logging.getLogger(__name__)
router = APIRouter()


# === РЕГИСТРАЦИЯ И АУТЕНТИФИКАЦИЯ ===

@router.post("/register", response_model=MerchantResponse)
async def register_merchant(
    merchant_data: MerchantRegister,
    db: Session = Depends(get_db)
):
    """Регистрация нового продавца"""
    auth_service = MerchantAuthService(db)
    merchant = auth_service.register_merchant(merchant_data)
    return merchant


@router.post("/login", response_model=MerchantLoginResponse)
async def login_merchant(
    login_data: MerchantLogin,
    db: Session = Depends(get_db)
):
    """Вход продавца"""
    auth_service = MerchantAuthService(db)
    merchant = auth_service.authenticate_merchant(login_data)
    
    if not merchant:
        error = ErrorHandlingService.create_authentication_error(
            "Invalid credentials",
            {"email": login_data.email}
        )
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )
    
    # Возвращаем API ключ как bearer-токен
    return MerchantLoginResponse(
        access_token=merchant.api_key,
        token_type="bearer",
        merchant=MerchantResponse.from_orm(merchant)
    )


@router.get("/banks")
async def get_banks_list(db: Session = Depends(get_db)):
    """Получение списка активных банков для формы регистрации"""
    try:
        banks = db.query(Bank).filter(Bank.is_active == True).all()
        return {
            "banks": [
                {
                    "id": bank.id,
                    "code": bank.code,
                    "name": bank.name,
                    "bik": bank.bik,
                    "is_active": bank.is_active
                }
                for bank in banks
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching banks: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка при получении списка банков")


# === QR-КОДЫ ===

@router.post("/qr-codes", response_model=UnifiedQRCodeRead)
async def create_qr_code(
    qr_data: UnifiedQRCodeCreate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Создание нового QR-кода"""
    # Проверяем лимиты продавца
    auth_service = MerchantAuthService(db)
    if qr_data.amount:
        limits_check = auth_service.check_merchant_limits(current_merchant, qr_data.amount)
        if not limits_check["within_limits"]:
            error = ErrorHandlingService.create_business_logic_error(
                "merchant_limits",
                f"Exceeded {limits_check['limit_type']} limit",
                ErrorCode.TRANSACTION_LIMIT_EXCEEDED,
                [f"Превышен {limits_check['limit_type']} лимит"]
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
                detail=error.to_dict()
            )
    
    # Генерируем защищенный QR токен
    from app.services.token_service import SecureTokenService
    from app.services.reference_service import PaymentReferenceService
    
    # Создаем payment reference
    payment_reference = PaymentReferenceService.generate_payment_reference(db)
    
    # Подготавливаем данные для токена
    token_payload = {
        "merchant_id": current_merchant.id,
        "amount": qr_data.amount,
        "currency": qr_data.currency,
        "payment_reference": payment_reference
    }
    
    # Устанавливаем время истечения
    now = datetime.now(timezone.utc)
    if qr_data.expires_at is not None:
        expires_at = qr_data.expires_at
    else:
        expires_at = now + timedelta(minutes=settings.QR_TOKEN_EXPIRE_MINUTES)
    
    # Генерируем защищенный токен
    # Вычисляем время истечения в минутах для токена
    if qr_data.expires_in_minutes is not None:
        token_expires_in_minutes = qr_data.expires_in_minutes
    else:
        token_expires_in_minutes = settings.QR_TOKEN_EXPIRE_MINUTES
        
    secure_token = SecureTokenService.generate_secure_token(
        token_payload, 
        expires_in_minutes=token_expires_in_minutes,
        expires_at=expires_at
    )
    
    # Извлекаем UUID для хранения
    token_uuid = SecureTokenService.extract_uuid_from_token(secure_token)
    
    # Создаем QR-код
    qr_code = QRCode(
        merchant_id=current_merchant.id,
        name=qr_data.name,
        description=qr_data.description,
        amount=qr_data.amount,
        currency=qr_data.currency,
        qr_token=token_uuid,  # Храним UUID
        qr_url=f"{settings.BASE_URL}/pay?token={secure_token}",  # Полный защищенный токен
        expires_at=expires_at,  # Устанавливаем время истечения
        max_uses=qr_data.max_uses,
        outlet_id=getattr(qr_data, 'outlet_id', None)
    )
    
    try:
        db.add(qr_code)
        db.commit()
        db.refresh(qr_code)
        
            # Генерируем изображение QR-кода
        try:
            qr_image_base64 = QRService.generate_qr_image(qr_code.qr_url)
            qr_code.qr_image_base64 = qr_image_base64
            db.commit()
        except Exception as e:
            logger.warning(f"Не удалось сгенерировать изображение QR-кода: {e}")
        
        # Записываем событие в таймлайн
        from app.services.timeline_service import TimelineService
        TimelineService.record_event(
            db,
            event_type='qr_created',
            title='QR-код создан',
            description=f"Продавец создал QR-код: {qr_data.name}",
            actor='merchant',
            source='api',
            status='info',
            metadata={
                "qr_code_id": qr_code.id,
                "amount": qr_data.amount,
                "currency": qr_data.currency
            }
        )
        
        return UnifiedQRCodeRead.from_orm(qr_code)
        
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при создании QR-кода: {e}")
        raise HTTPException(
            status_code=500,
            detail="Ошибка при создании QR-кода"
        )


@router.get("/qr-codes", response_model=List[UnifiedQRCodeRead])
async def get_qr_codes(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    active_only: bool = Query(False, description="Только активные QR-коды")
):
    """Получение списка QR-кодов продавца"""
    query = db.query(QRCode).filter(QRCode.merchant_id == current_merchant.id)
    
    if active_only:
        # Показываем активные QR-коды, которые не истекли и не были использованы
        now = datetime.now(timezone.utc)
        query = query.filter(
            QRCode.is_active == True,
            (QRCode.expires_at.is_(None) | (QRCode.expires_at > now)),
            (QRCode.max_uses.is_(None) | (QRCode.current_uses < QRCode.max_uses))
        )
    
    qr_codes = query.order_by(QRCode.created_at.desc()).all()
    return qr_codes


@router.get("/qr-codes/{qr_code_id}", response_model=UnifiedQRCodeRead)
async def get_qr_code(
    qr_code_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Получение конкретного QR-кода"""
    qr_code = db.query(QRCode).filter(
        QRCode.id == qr_code_id,
        QRCode.merchant_id == current_merchant.id
    ).first()
    
    if not qr_code:
        error = ErrorHandlingService.create_business_logic_error(
            "qr_code_not_found",
            f"QR code with id {qr_code_id} not found",
            ErrorCode.PAYMENT_NOT_FOUND
        )
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )
    
    return UnifiedQRCodeRead.from_orm(qr_code)


@router.get("/qr-codes/{qr_code_id}/stats")
async def get_qr_code_stats(
    qr_code_id: int,
    hours: int = Query(24, description="Период в часах"),
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Статистика по конкретному QR коду"""
    from sqlalchemy import and_, func
    
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Проверяем принадлежность QR продавцу
    qr = db.query(QRCode).filter(
        QRCode.id == qr_code_id,
        QRCode.merchant_id == current_merchant.id
    ).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    count = db.query(func.count(MerchantPayment.id)).filter(
        and_(
            MerchantPayment.merchant_id == current_merchant.id,
            MerchantPayment.qr_code_id == qr_code_id,
            MerchantPayment.status == 'completed',
            MerchantPayment.created_at >= since,
        )
    ).scalar() or 0
    
    total = db.query(func.sum(MerchantPayment.amount)).filter(
        and_(
            MerchantPayment.merchant_id == current_merchant.id,
            MerchantPayment.qr_code_id == qr_code_id,
            MerchantPayment.status == 'completed',
            MerchantPayment.created_at >= since,
        )
    ).scalar() or 0
    
    return {
        "status": "success",
        "data": {
            "qr_code_id": qr_code_id,
            "name": qr.name,
            "hours": hours,
            "payments_count": int(count),
            "total_amount": float(total),
        },
        "timestamp": datetime.now().isoformat()
    }


@router.get("/qr-codes/{qr_code_id}/qr-image")
async def get_qr_code_image(
    qr_code_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    format: str = Query("png", description="png|svg")
):
    """Получение изображения QR-кода"""
    qr_code = db.query(QRCode).filter(
        QRCode.id == qr_code_id,
        QRCode.merchant_id == current_merchant.id
    ).first()
    
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    # Генерируем QR-код
    qr_image = QRService.generate_qr_image(qr_code.qr_url)
    
    content_type = "image/png" if format == "png" else "image/svg+xml"
    return Response(content=qr_image, media_type=content_type)


@router.put("/qr-codes/{qr_code_id}/toggle")
async def toggle_qr_code_status(
    qr_code_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Переключение статуса QR-кода (активен/неактивен)"""
    qr_code = db.query(QRCode).filter(
        QRCode.id == qr_code_id,
        QRCode.merchant_id == current_merchant.id
    ).first()
    
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    qr_code.is_active = not qr_code.is_active
    qr_code.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(qr_code)
    
    return {
        "success": True,
        "message": f"QR-код {'активирован' if qr_code.is_active else 'деактивирован'}",
        "is_active": qr_code.is_active
    }


# === ПЛАТЕЖИ ===

@router.get("/payments", response_model=List[MerchantPaymentResponse])
async def get_payments(
    current_merchant: Merchant = Depends(get_merchant_for_payments),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    limit: int = Query(50, description="Количество записей"),
    offset: int = Query(0, description="Смещение"),
    date_from: Optional[str] = Query(None, description="Дата от (ISO)"),
    date_to: Optional[str] = Query(None, description="Дата до (ISO)"),
    min_amount: Optional[float] = Query(None, description="Мин. сумма"),
    max_amount: Optional[float] = Query(None, description="Макс. сумма"),
    qr_code_id: Optional[int] = Query(None, description="Фильтр по QR коду"),
    outlet_id: Optional[int] = Query(None, description="Фильтр по торговой точке")
):
    """Получение списка платежей продавца"""
    payment_service = MerchantPaymentService(db)
    
    try:
        payments = payment_service.get_payments_list(
            merchant=current_merchant,
            limit=limit,
            offset=offset,
            status=status,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            qr_code_id=qr_code_id,
            outlet_id=outlet_id
        )
        return payments
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/payments/export")
async def export_payments_csv(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    qr_code_id: Optional[int] = None,
    outlet_id: Optional[int] = None,
):
    """Экспорт платежей в CSV"""
    payment_service = MerchantPaymentService(db)
    
    try:
        csv_content = payment_service.export_payments_csv(
            merchant=current_merchant,
            status=status,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            qr_code_id=qr_code_id,
            outlet_id=outlet_id
        )
        
        headers = {"Content-Disposition": "attachment; filename=payments.csv"}
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers=headers
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/payments/series")
async def get_payments_series(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db),
    days: int = Query(7, description="Количество дней для серии")
):
    """Серия данных платежей по дням для графиков"""
    payment_service = MerchantPaymentService(db)
    series = payment_service.get_payments_series(current_merchant, days)
    return series


@router.get("/payments/{payment_id}", response_model=MerchantPaymentResponse)
async def get_payment(
    payment_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Получение конкретного платежа"""
    payment = db.query(MerchantPayment).filter(
        MerchantPayment.id == payment_id,
        MerchantPayment.merchant_id == current_merchant.id
    ).first()
    
    if not payment:
        error = ErrorHandlingService.create_business_logic_error(
            "payment_not_found",
            f"Payment with id {payment_id} not found",
            ErrorCode.PAYMENT_NOT_FOUND
        )
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )
    
    return payment


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(
    payment_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Отмена платежа"""
    payment = db.query(MerchantPayment).filter(
        MerchantPayment.id == payment_id,
        MerchantPayment.merchant_id == current_merchant.id
    ).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    if payment.status != 'pending':
        raise HTTPException(status_code=400, detail="Only pending payments can be cancelled")
    
    payment.status = 'cancelled'
    payment.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(payment)
    
    return {
        "success": True,
        "message": "Payment cancelled successfully",
        "payment_id": payment_id
    }


# === ТОРГОВЫЕ ТОЧКИ ===

class OutletCreate(BaseModel):
    name: str
    address: Optional[str] = None
    description: Optional[str] = None


class OutletUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


@router.post("/outlets")
async def create_outlet(
    outlet: OutletCreate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Создание торговой точки"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.create_outlet(
        current_merchant,
        outlet.name,
        outlet.address,
        outlet.description
    )


@router.get("/outlets")
async def list_outlets(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Список торговых точек"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.list_outlets(current_merchant)


@router.put("/outlets/{outlet_id}")
async def update_outlet(
    outlet_id: int,
    payload: OutletUpdate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Обновление торговой точки"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.update_outlet(
        current_merchant,
        outlet_id,
        payload.name,
        payload.address,
        payload.description
    )


@router.post("/outlets/{outlet_id}/archive")
async def archive_outlet(
    outlet_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Архивация торговой точки"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.archive_outlet(current_merchant, outlet_id)


@router.post("/outlets/{outlet_id}/activate")
async def activate_outlet(
    outlet_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Активация торговой точки"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.activate_outlet(current_merchant, outlet_id)


@router.get("/outlets/{outlet_id}/qr")
async def get_outlet_qr(
    outlet_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    format: str = Query("png", description="png|svg"),
):
    """Генерация статического QR для торговой точки"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.generate_outlet_qr(current_merchant, outlet_id, format)


@router.get("/outlets/{outlet_id}/stats")
async def get_outlet_stats(
    outlet_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    hours: int = Query(24, description="Период в часах")
):
    """Статистика платежей по торговой точке"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.get_outlet_stats(current_merchant, outlet_id, hours)


@router.get("/outlets/distribution")
async def get_outlets_distribution(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db),
    days: int = Query(7, description="Период в днях для расчёта распределения")
) -> Dict[str, Any]:
    """Распределение оборота по торговым точкам"""
    outlet_service = MerchantOutletService(db)
    return outlet_service.get_outlets_distribution(current_merchant, days)


# === СТАТИСТИКА ===

@router.get("/statistics", response_model=MerchantStats)
async def get_merchant_statistics(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db),
    period: str = Query("month", description="Период: day, week, month"),
    start_date: Optional[date] = Query(None, description="Начальная дата для статистики (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Конечная дата для статистики (YYYY-MM-DD)")
):
    """Получение статистики продавца (алиас для /stats)"""
    payment_service = MerchantPaymentService(db)
    
    # Получаем статистику платежей
    payment_stats = payment_service.get_merchant_stats(current_merchant, period, start_date, end_date)
    
    # QR-коды
    active_qr_codes = db.query(QRCode).filter(
        QRCode.merchant_id == current_merchant.id,
        QRCode.is_active == True
    ).count()
    
    total_qr_codes = db.query(QRCode).filter(
        QRCode.merchant_id == current_merchant.id
    ).count()
    
    # Торговые точки
    from app.models.merchant import TradingPoint
    active_outlets = db.query(TradingPoint).filter(
        TradingPoint.merchant_id == current_merchant.id,
        TradingPoint.status == "ACTIVE"
    ).count()
    
    total_outlets = db.query(TradingPoint).filter(
        TradingPoint.merchant_id == current_merchant.id
    ).count()
    
    # Сегодня и вчера
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    
    today_amount_result = db.query(func.sum(MerchantPayment.amount)).filter(
        MerchantPayment.merchant_id == current_merchant.id,
        func.date(MerchantPayment.paid_at) == today,
        MerchantPayment.status == "completed"
    ).scalar()
    today_amount = float(today_amount_result) if today_amount_result else 0.0
    
    yesterday_amount_result = db.query(func.sum(MerchantPayment.amount)).filter(
        MerchantPayment.merchant_id == current_merchant.id,
        func.date(MerchantPayment.paid_at) == yesterday,
        MerchantPayment.status == "completed"
    ).scalar()
    yesterday_amount = float(yesterday_amount_result) if yesterday_amount_result else 0.0
    
    return MerchantStats(
        total_payments=payment_stats["total_payments"],
        total_amount=payment_stats["total_amount"],
        successful_payments=payment_stats["successful_payments"],
        failed_payments=payment_stats["failed_payments"],
        success_rate=payment_stats["success_rate"],
        average_payment_amount=payment_stats["average_payment_amount"],
        active_qr_codes=active_qr_codes,
        total_qr_codes=total_qr_codes,
        active_outlets=active_outlets,
        total_outlets=total_outlets,
        today_amount=today_amount,
        yesterday_amount=yesterday_amount
    )

@router.get("/stats", response_model=MerchantStats)
async def get_merchant_stats(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db),
    period: str = Query("month", description="Период: day, week, month"),
    start_date: Optional[date] = Query(None, description="Начальная дата для статистики (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="Конечная дата для статистики (YYYY-MM-DD)")
):
    """Получение статистики продавца"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Запрос статистики для продавца ID: {current_merchant.id}, Email: {current_merchant.email}")
    
    payment_service = MerchantPaymentService(db)
    
    # Получаем статистику платежей
    payment_stats = payment_service.get_merchant_stats(current_merchant, period, start_date, end_date)
    
    # QR-коды
    active_qr_codes = db.query(QRCode).filter(
        QRCode.merchant_id == current_merchant.id,
        QRCode.is_active == True
    ).count()
    
    total_qr_codes = db.query(QRCode).filter(
        QRCode.merchant_id == current_merchant.id
    ).count()
    
    # Торговые точки
    active_outlets = db.query(TradingPoint).filter(
        TradingPoint.merchant_id == current_merchant.id,
        TradingPoint.status == "ACTIVE"
    ).count()
    
    total_outlets = db.query(TradingPoint).filter(
        TradingPoint.merchant_id == current_merchant.id
    ).count()
    
    # Сегодня и вчера
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    
    today_amount_result = db.query(func.sum(MerchantPayment.amount)).filter(
        MerchantPayment.merchant_id == current_merchant.id,
        func.date(MerchantPayment.created_at) == today,
        MerchantPayment.status == "completed"
    ).scalar()
    today_amount = float(today_amount_result) if today_amount_result else 0.0
    
    yesterday_amount_result = db.query(func.sum(MerchantPayment.amount)).filter(
        MerchantPayment.merchant_id == current_merchant.id,
        func.date(MerchantPayment.created_at) == yesterday,
        MerchantPayment.status == "completed"
    ).scalar()
    yesterday_amount = float(yesterday_amount_result) if yesterday_amount_result else 0.0
    
    return MerchantStats(
        total_payments=payment_stats["total_payments"],
        total_amount=payment_stats["total_amount"],
        successful_payments=payment_stats["successful_payments"],
        failed_payments=payment_stats["failed_payments"],
        success_rate=payment_stats["success_rate"],
        average_payment_amount=payment_stats["average_payment_amount"],
        active_qr_codes=active_qr_codes,
        total_qr_codes=total_qr_codes,
        active_outlets=active_outlets,
        total_outlets=total_outlets,
        today_amount=today_amount,
        yesterday_amount=yesterday_amount,
        status_distribution=payment_stats.get("status_distribution", {})
    )


# === БЫСТРАЯ СТАТИСТИКА ДЛЯ ДАШБОРДА ===

@router.get("/stats/quick")
async def get_quick_stats(
    current_merchant: Merchant = Depends(get_merchant_for_reports),
    db: Session = Depends(get_db)
):
    """Быстрая статистика для дашборда"""
    payment_service = MerchantPaymentService(db)
    return payment_service.get_quick_stats(current_merchant)


# === НАСТРОЙКИ ===

@router.get("/settings", response_model=MerchantSettingsResponse)
async def get_merchant_settings(
    current_merchant: Merchant = Depends(get_merchant_for_settings),
    db: Session = Depends(get_db)
):
    """Получение настроек продавца"""
    settings = db.query(MerchantSettings).filter(
        MerchantSettings.merchant_id == current_merchant.id
    ).first()
    
    if not settings:
        # Создаем настройки по умолчанию
        settings = MerchantSettings(merchant_id=current_merchant.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return settings


@router.put("/settings", response_model=MerchantSettingsResponse)
async def update_merchant_settings(
    settings_data: MerchantSettingsUpdate,
    current_merchant: Merchant = Depends(get_merchant_for_settings),
    db: Session = Depends(get_db)
):
    """Обновление настроек продавца"""
    settings = db.query(MerchantSettings).filter(
        MerchantSettings.merchant_id == current_merchant.id
    ).first()
    
    if not settings:
        settings = MerchantSettings(merchant_id=current_merchant.id)
        db.add(settings)
    
    # Обновляем только переданные поля
    for field, value in settings_data.dict(exclude_unset=True).items():
        if hasattr(settings, field):
            setattr(settings, field, value)
    
    db.commit()
    db.refresh(settings)
    
    return settings


# === ПРОФИЛЬ ===

@router.get("/profile", response_model=MerchantResponse)
async def get_merchant_profile(
    current_merchant: Merchant = Depends(get_current_merchant)
):
    """Получение профиля продавца"""
    return current_merchant


@router.put("/profile", response_model=MerchantResponse)
async def update_merchant_profile(
    profile_data: MerchantProfileUpdate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Обновление профиля продавца"""
    # Проверяем уникальность email и ИНН с блокировкой записи
    from sqlalchemy import and_
    
    try:
        # Блокируем запись для обновления
        locked_merchant = db.query(Merchant).filter(
            Merchant.id == current_merchant.id
        ).with_for_update().first()
        
        if not locked_merchant:
            raise HTTPException(status_code=404, detail="Продавец не найден")
        
        # Проверяем уникальность email (если он изменяется)
        if profile_data.email and profile_data.email != locked_merchant.email:
            existing_merchant = db.query(Merchant).filter(
                and_(
                    Merchant.email == profile_data.email,
                    Merchant.id != locked_merchant.id
                )
            ).first()
            if existing_merchant:
                raise HTTPException(
                    status_code=400,
                    detail="Email уже используется другим продавцом"
                )
        
        # Проверяем уникальность ИНН (если он изменяется)
        if profile_data.inn and profile_data.inn != locked_merchant.inn:
            existing_merchant = db.query(Merchant).filter(
                and_(
                    Merchant.inn == profile_data.inn,
                    Merchant.id != locked_merchant.id
                )
            ).first()
            if existing_merchant:
                raise HTTPException(
                    status_code=400,
                    detail="ИНН уже используется другим продавцом"
                )
        
        # Обновляем только переданные поля
        for field, value in profile_data.dict(exclude_unset=True).items():
            if hasattr(locked_merchant, field) and value is not None:
                setattr(locked_merchant, field, value)
        
        # Обновляем время последнего изменения
        locked_merchant.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(locked_merchant)
        
        return locked_merchant
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении профиля: {e}")
        raise HTTPException(
            status_code=500,
            detail="Ошибка при обновлении профиля"
        )
    



# === СМЕНА ПАРОЛЯ ===

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Смена пароля продавца"""
    from app.services.merchant_auth_service import MerchantAuthService
    
    auth_service = MerchantAuthService(db)
    
    # Проверяем текущий пароль
    if not auth_service.verify_password(password_data.current_password, current_merchant.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    
    # Хешируем новый пароль
    new_password_hash = auth_service.hash_password(password_data.new_password)
    
    # Обновляем пароль
    current_merchant.hashed_password = new_password_hash
    current_merchant.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(current_merchant)
    
    return {"success": True, "message": "Пароль успешно изменен"}

# === ПЕРЕГЕНЕРАЦИЯ API КЛЮЧА ===

@router.post("/regenerate-api-key")
async def regenerate_api_key(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Перегенерация API ключа продавца"""
    import secrets
    
    # Генерируем новый API ключ
    new_api_key = f"merchant_{secrets.token_urlsafe(32)}"
    
    # Обновляем API ключ
    current_merchant.api_key = new_api_key
    current_merchant.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(current_merchant)
    
    return {"success": True, "api_key": new_api_key, "message": "API ключ успешно перегенерирован"}

# === ТЕСТ АУТЕНТИФИКАЦИИ ===

@router.get("/test-auth")
async def test_auth(
    current_merchant: Merchant = Depends(get_current_merchant)
):
    """Тестовый эндпоинт для проверки аутентификации"""
    return {
        "success": True,
        "merchant_id": current_merchant.id,
        "merchant_name": current_merchant.name,
        "merchant_email": current_merchant.email,
        "is_verified": current_merchant.is_verified,
        "is_active": current_merchant.is_active,
        "api_key_prefix": current_merchant.api_key[:20] if current_merchant.api_key else None,
        "message": "Аутентификация работает"
    }

# === БАНКИ ===

@router.get("/banks")
async def get_banks_list(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """Получение списка доступных банков для выбора"""
    from app.models.payment import Bank
    
    banks = db.query(Bank).filter(Bank.is_active == True).all()
    return [
        {
            "code": bank.code,
            "name": bank.name,
            "bik": bank.bik or f"{bank.code}00000"[:9]
        }
        for bank in banks
    ]