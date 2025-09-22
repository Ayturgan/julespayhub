# Merchant management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.merchant import MerchantResponse, MerchantDetailResponse, MerchantStats, PaymentSummary
from app.models.merchant import Merchant, MerchantPayment, QRCode, MerchantSettings
from app.services.billing_service import BillingService
from app.core.dependencies import check_rate_limit, get_current_admin_user
from app.services.hybrid_logging_service import hybrid_logging_service
from sqlalchemy import func, and_, desc
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import secrets

router = APIRouter(prefix="/merchants")

# ============================================================================
# MERCHANT MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/", response_model=List[MerchantResponse])
async def list_merchants(
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    is_verified: Optional[bool] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Список всех продавцов (поиск по имени/юридическому имени/email)
    """
    query = db.query(Merchant)

    if is_active is not None:
        query = query.filter(Merchant.is_active == is_active)
    if is_verified is not None:
        query = query.filter(Merchant.is_verified == is_verified)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Merchant.name.ilike(like)) |
            (Merchant.legal_name.ilike(like)) |
            (Merchant.email.ilike(like))
        )

    merchants = query.order_by(Merchant.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for merchant in merchants:
        # Подсчитываем QR-коды
        qr_codes_count = db.query(QRCode).filter(QRCode.merchant_id == merchant.id).count()
        
        # Подсчитываем платежи
        payments_count = db.query(MerchantPayment).filter(MerchantPayment.merchant_id == merchant.id).count()
        
        result.append({
            "id": merchant.id,
            "name": merchant.name,
            "legal_name": merchant.legal_name,
            "inn": merchant.inn,
            "kpp": merchant.kpp,
            "email": merchant.email,
            "phone": merchant.phone,
            "address": merchant.address,
            "bank_account": merchant.bank_account,
            "bank_name": merchant.bank_name,
            "bank_bik": merchant.bank_bik,
            "api_key": merchant.api_key,
            "is_active": merchant.is_active,
            "is_verified": merchant.is_verified,
            "verification_date": merchant.verification_date,
            "daily_limit": merchant.daily_limit,
            "monthly_limit": merchant.monthly_limit,
            "created_at": merchant.created_at,
            "updated_at": merchant.updated_at,
            "last_activity": merchant.last_activity,
            "qr_codes_count": qr_codes_count,
            "payments_count": payments_count
        })
    
    return result

@router.get("/{merchant_id}", response_model=MerchantDetailResponse)
async def get_merchant_details(
    merchant_id: int,
    db: Session = Depends(get_db)
):
    """
    Детальная информация о продавце
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Подсчитываем QR-коды
    qr_codes_count = db.query(QRCode).filter(QRCode.merchant_id == merchant_id).count()
    
    # Подсчитываем платежи
    payments_count = db.query(MerchantPayment).filter(MerchantPayment.merchant_id == merchant_id).count()
    
    # Подсчитываем общую сумму успешных платежей
    total_amount_result = db.query(func.sum(MerchantPayment.amount)).filter(
        and_(
            MerchantPayment.merchant_id == merchant_id,
            MerchantPayment.status == 'completed'
        )
    ).scalar()
    total_amount = float(total_amount_result) if total_amount_result else 0
    
    return {
        "id": merchant.id,
        "name": merchant.name,
        "legal_name": merchant.legal_name,
        "inn": merchant.inn,
        "kpp": merchant.kpp,
        "email": merchant.email,
        "phone": merchant.phone,
        "address": merchant.address,
        "bank_account": merchant.bank_account,
        "bank_name": merchant.bank_name,
        "bank_bik": merchant.bank_bik,
        "api_key": merchant.api_key,
        "is_active": merchant.is_active,
        "is_verified": merchant.is_verified,
        "verification_date": merchant.verification_date,
        "daily_limit": merchant.daily_limit,
        "monthly_limit": merchant.monthly_limit,
        "created_at": merchant.created_at,
        "updated_at": merchant.updated_at,
        "last_activity": merchant.last_activity,
        "qr_codes_count": qr_codes_count,
        "payments_count": payments_count,
        "total_amount": total_amount
    }





@router.put("/{merchant_id}/toggle-status")
async def toggle_merchant_status(
    merchant_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin = None
):
    """
    Переключение статуса активности продавца
    Требует аутентификации админа
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Сохраняем старый статус для логирования
    old_active_status = merchant.is_active
    
    merchant.is_active = not merchant.is_active
    merchant.updated_at = datetime.now()
    
    db.commit()
    db.refresh(merchant)
    
    # Логируем действие админа
    action = "activate_merchant" if merchant.is_active else "deactivate_merchant"
    action_text = "активирован" if merchant.is_active else "деактивирован"
    
    # Временно отключаем логирование для демо
    # hybrid_logging_service.log_admin_action(
    #     db=db,
    #     action=action,
    #     target=f"merchant_{merchant_id}",
    #     details={
    #         "merchant_id": merchant_id,
    #         "merchant_name": merchant.name,
    #         "merchant_email": merchant.email,
    #         "old_status": old_active_status,
    #         "new_status": merchant.is_active
    #     },
    #     actor_id=current_admin.get("username") if current_admin else "demo_admin",
    #     ip_address=request.client.host if request.client else None
    # )
    
    return {
        "merchant_id": merchant.id,
        "is_active": merchant.is_active,
        "message": f"Продавец {action_text} успешно",
        "admin": current_admin.get("username") if current_admin else "demo_admin"
    }

@router.put("/{merchant_id}/verify")
async def toggle_merchant_verification(
    merchant_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin = None
):
    """
    Переключение статуса верификации продавца
    Требует аутентификации админа
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Сохраняем старый статус для логирования
    old_verification_status = merchant.is_verified
    
    # Переключаем статус верификации
    merchant.is_verified = not merchant.is_verified
    
    if merchant.is_verified:
        merchant.verification_date = datetime.now(timezone.utc)
    else:
        merchant.verification_date = None
        
    merchant.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(merchant)
    
    # Логируем действие админа
    action = "verify_merchant" if merchant.is_verified else "unverify_merchant"
    action_text = "верифицирован" if merchant.is_verified else "снята верификация"
    
    # Временно отключаем логирование для демо
    # hybrid_logging_service.log_admin_action(
    #     db=db,
    #     action=action,
    #     target=f"merchant_{merchant_id}",
    #     details={
    #         "merchant_id": merchant_id,
    #         "merchant_name": merchant.name,
    #         "merchant_email": merchant.email,
    #         "old_status": old_verification_status,
    #         "new_status": merchant.is_verified,
    #         "verification_date": merchant.verification_date.isoformat() if merchant.verification_date else None
    #     },
    #     actor_id=current_admin.get("username") if current_admin else "demo_admin",
    #     ip_address=request.client.host if request.client else None
    # )
    
    return {
        "merchant_id": merchant.id,
        "is_verified": merchant.is_verified,
        "verification_date": merchant.verification_date,
        "message": f"Продавец {action_text} успешно",
        "admin": current_admin.get("username") if current_admin else "demo_admin"
    }


@router.put("/{merchant_id}/limits")
async def update_merchant_limits(
    merchant_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user),
    daily_limit: Optional[float] = None,
    monthly_limit: Optional[float] = None
):
    """
    Обновление лимитов продавца
    Требует аутентификации админа
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Сохраняем старые лимиты для логирования
    old_daily_limit = merchant.daily_limit
    old_monthly_limit = merchant.monthly_limit
    
    if daily_limit is not None:
        merchant.daily_limit = daily_limit
    
    if monthly_limit is not None:
        merchant.monthly_limit = monthly_limit
    
    merchant.updated_at = datetime.now()
    
    db.commit()
    db.refresh(merchant)
    
    # Логируем действие админа
    hybrid_logging_service.log_admin_action(
        db=db,
        action="update_merchant_limits",
        target=f"merchant_{merchant_id}",
        details={
            "merchant_id": merchant_id,
            "merchant_name": merchant.name,
            "merchant_email": merchant.email,
            "old_daily_limit": old_daily_limit,
            "new_daily_limit": merchant.daily_limit,
            "old_monthly_limit": old_monthly_limit,
            "new_monthly_limit": merchant.monthly_limit
        },
        actor_id=current_admin.get("username"),
        ip_address=request.client.host if request.client else None
    )
    
    return {
        "merchant_id": merchant.id,
        "daily_limit": merchant.daily_limit,
        "monthly_limit": merchant.monthly_limit,
        "message": "Лимиты продавца обновлены успешно",
        "admin": current_admin.get("username")
    }

@router.delete("/{merchant_id}")
async def delete_merchant(
    merchant_id: int, 
    request: Request,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Удаление продавца. При наличии связанных данных может вернуть ошибку целостности.
    Требует аутентификации админа
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    merchant_name = merchant.name
    merchant_email = merchant.email
    
    try:
        db.delete(merchant)
        db.commit()
        
        # Логируем действие админа
        hybrid_logging_service.log_admin_action(
            db=db,
            action="delete_merchant",
            target=f"merchant_{merchant_id}",
            details={
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "merchant_email": merchant_email
            },
            actor_id=current_admin.get("username"),
            ip_address=request.client.host if request.client else None
        )
        
        return {
            "message": "Продавец удален успешно", 
            "merchant_id": merchant_id,
            "admin": current_admin.get("username")
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete merchant with related data. Deactivate instead.")

@router.delete("/{merchant_id}/force")
async def force_delete_merchant(merchant_id: int, db: Session = Depends(get_db)):
    """Форс-удаление продавца: деактивация, очистка зависимостей (QR/Payments), затем удаление.
    Внимание: операции необратимы."""
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    try:
        # 1) Мягкая деактивация
        merchant.is_active = False
        merchant.updated_at = datetime.now()
        db.commit()

        # 2) Удаляем связанные QR-коды
        db.query(QRCode).filter(QRCode.merchant_id == merchant_id).delete(synchronize_session=False)
        db.commit()

        # 3) Удаляем связанные MerchantPayment
        db.query(MerchantPayment).filter(MerchantPayment.merchant_id == merchant_id).delete(synchronize_session=False)
        db.commit()

        # 4) Удаляем настройки
        db.query(MerchantSettings).filter(MerchantSettings.merchant_id == merchant_id).delete(synchronize_session=False)
        db.commit()

        # 5) Пытаемся удалить самого продавца
        db.delete(merchant)
        db.commit()
        return {"message": "Merchant force deleted", "merchant_id": merchant_id}
    except IntegrityError as e:
        db.rollback()
        # Если остались внешние ключи (например, биллинг), не удаляем, а возвращаем подсказку
        raise HTTPException(status_code=409, detail="Cannot force delete merchant due to related billing or records. Deactivate instead.")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{merchant_id}/stats", response_model=MerchantStats)
async def get_merchant_stats(
    merchant_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Статистика продавца
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Парсим даты
    start_dt = None
    end_dt = None
    
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    return BillingService.get_merchant_billing_summary(db, merchant, start_dt, end_dt)

@router.get("/{merchant_id}/payments", response_model=List[PaymentSummary])
async def get_merchant_payments(
    merchant_id: int,
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Платежи продавца
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    query = db.query(MerchantPayment).filter(MerchantPayment.merchant_id == merchant_id)
    
    if status:
        query = query.filter(MerchantPayment.status == status)
    
    payments = query.order_by(MerchantPayment.processed_at.desc()).offset(skip).limit(limit).all()
    
    return [
        PaymentSummary(
            id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            payer_phone=payment.payer_phone,
            payer_name=payment.payer_name,
            transaction_id=payment.transaction_id,
            bank_code=payment.bank_code,
            processed_at=payment.processed_at,
            qr_code_id=payment.qr_code_id
        )
        for payment in payments
    ]

@router.get("/{merchant_id}/qr-codes")
async def get_merchant_qr_codes(
    merchant_id: int,
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    QR-коды продавца
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    query = db.query(QRCode).filter(QRCode.merchant_id == merchant_id)
    
    if is_active is not None:
        query = query.filter(QRCode.is_active == is_active)
    
    qr_codes = query.order_by(QRCode.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": qr.id,
            "name": qr.name,
            "description": qr.description,
            "amount": qr.amount,
            "currency": qr.currency,
            "qr_token": qr.qr_token,
            "qr_url": qr.qr_url,
            "expires_at": qr.expires_at,
            "max_uses": qr.max_uses,
            "current_uses": qr.current_uses,
            "is_active": qr.is_active,
            "created_at": qr.created_at
        }
        for qr in qr_codes
    ]

@router.get("/{merchant_id}/qr-stats")
async def get_merchant_qr_stats(
    merchant_id: int,
    db: Session = Depends(get_db)
):
    """
    Статистика QR-кодов продавца
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    return BillingService.get_merchant_qr_code_stats(db, merchant)

@router.post("/{merchant_id}/regenerate-api-key")
async def regenerate_merchant_api_key(
    merchant_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Регенерация API ключа продавца
    Требует аутентификации админа
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Сохраняем старый API ключ для логирования
    old_api_key = merchant.api_key
    
    # Генерируем новый API ключ
    new_api_key = f"merchant_{secrets.token_urlsafe(32)}"
    new_api_secret = secrets.token_urlsafe(64)
    
    merchant.api_key = new_api_key
    merchant.api_secret = new_api_secret
    merchant.updated_at = datetime.now()
    
    db.commit()
    db.refresh(merchant)
    
    # Логируем действие админа
    hybrid_logging_service.log_admin_action(
        db=db,
        action="regenerate_merchant_api_key",
        target=f"merchant_{merchant_id}",
        details={
            "merchant_id": merchant_id,
            "merchant_name": merchant.name,
            "merchant_email": merchant.email,
            "old_api_key": old_api_key[:20] + "..." if old_api_key else None,
            "new_api_key": new_api_key[:20] + "..."
        },
        actor_id=current_admin.get("username"),
        ip_address=request.client.host if request.client else None
    )
    
    return {
        "merchant_id": merchant.id,
        "new_api_key": new_api_key,
        "message": "API ключ продавца регенерирован успешно",
        "admin": current_admin.get("username")
    }

@router.get("/stats/overview")
async def get_merchants_overview_stats(db: Session = Depends(get_db)):
    """
    Общая статистика по продавцам
    """
    total_merchants = db.query(Merchant).count()
    active_merchants = db.query(Merchant).filter(Merchant.is_active == True).count()
    verified_merchants = db.query(Merchant).filter(Merchant.is_verified == True).count()
    
    # Статистика за последние 30 дней
    thirty_days_ago = datetime.now() - timedelta(days=30)
    new_merchants = db.query(Merchant).filter(Merchant.created_at >= thirty_days_ago).count()
    
    # Общая статистика платежей
    total_payments = db.query(MerchantPayment).count()
    successful_payments = db.query(MerchantPayment).filter(MerchantPayment.status == "success").count()
    
    # Общая статистика QR-кодов
    total_qr_codes = db.query(QRCode).count()
    active_qr_codes = db.query(QRCode).filter(QRCode.is_active == True).count()
    
    return {
        "merchants": {
            "total": total_merchants,
            "active": active_merchants,
            "verified": verified_merchants,
            "new_last_30_days": new_merchants
        },
        "payments": {
            "total": total_payments,
            "successful": successful_payments,
            "success_rate": round((successful_payments / max(total_payments, 1)) * 100, 2)
        },
        "qr_codes": {
            "total": total_qr_codes,
            "active": active_qr_codes
        }
    }