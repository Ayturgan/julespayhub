# QR codes endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.admin import Admin
from app.models.admin import AdminQRCode
from app.models.payment import PaymentRequest, TransactionStatus
from app.schemas.payment import PaymentRequestCreate
from app.services.hybrid_logging_service import hybrid_logging_service
from app.services.two_phase_commit_service import two_phase_commit_service
from app.core.dependencies import get_current_admin_user
from app.core.config import settings
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class AdminQRCodeCreate(BaseModel):
    name: str
    amount: float
    currency: str = "KGS"
    description: Optional[str] = None

class QRResponse(BaseModel):
    id: int
    token: str
    amount: float
    currency: str
    description: str
    expires_at: Optional[str]
    payment_url: str

@router.post("/", response_model=QRResponse)
async def create_admin_qr_code(
    qr_data: AdminQRCodeCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Создание QR-кода от имени администратора
    Требует заполненного профиля с банковскими реквизитами
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Проверяем, заполнен ли профиль
    if not admin.has_complete_profile():
        raise HTTPException(
            status_code=400, 
            detail="Для создания QR-кодов необходимо заполнить профиль с банковскими реквизитами"
        )
    
    try:
        # Генерируем защищенный QR токен
        from app.services.token_service import SecureTokenService
        from app.services.reference_service import PaymentReferenceService
        
        # Создаем payment reference
        payment_reference = PaymentReferenceService.generate_payment_reference(db)
        
        # Подготавливаем данные для токена
        token_payload = {
            "admin_id": admin.id,
            "amount": qr_data.amount,
            "currency": qr_data.currency,
            "payment_reference": payment_reference,
            "receiver_account": admin.bank_account,
            "receiver_bank_code": admin.bank_code
        }
        
        # Генерируем защищенный токен
        secure_token = SecureTokenService.generate_secure_token(
            token_payload, 
            expires_in_minutes=10  # 10 минут
        )
        
        # Извлекаем UUID для хранения
        token_uuid = SecureTokenService.extract_uuid_from_token(secure_token)
        
        # Устанавливаем время жизни QR кода (10 минут)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Создаем QR-код для админа
        qr_code = AdminQRCode(
            admin_id=admin.id,
            name=qr_data.name,
            description=qr_data.description or f"Платеж для {admin.organization_name}",
            amount=qr_data.amount,
            currency=qr_data.currency,
            qr_token=token_uuid,  # Храним UUID
            qr_url=f"{settings.BASE_URL}/pay?token={secure_token}",  # Полный защищенный токен
            is_active=True,  # Явно устанавливаем активный статус
            expires_at=expires_at,
            max_uses=None
        )
        
        db.add(qr_code)
        db.commit()
        db.refresh(qr_code)
        
        # Создаем событие в таймлайне
        try:
            from app.services.timeline_service import TimelineService
            TimelineService.record_event(
                db,
                payment_token=token_uuid,
                transaction_id=str(qr_code.id),
                event_type='qr_created',
                title='QR-код создан',
                description=f"Администратор создал QR-код для платежа на сумму {qr_data.amount} {qr_data.currency}",
                actor='admin',
                source='api',
                status='success',
                metadata={
                    "qr_code_id": qr_code.id,
                    "admin_id": admin.id,
                    "amount": qr_data.amount,
                    "currency": qr_data.currency
                }
            )
        except Exception as e:
            logger.warning(f"Не удалось создать событие таймлайна: {e}")
        
        # Отладочная информация
        logger.info(f"QR код создан: ID={qr_code.id}, admin_id={qr_code.admin_id}, name={qr_code.name}")
        
        # Генерируем изображение QR-кода
        try:
            from app.services.qr_service import QRService
            qr_image_base64 = QRService.generate_qr_image(qr_code.qr_url)
            qr_code.qr_image_base64 = qr_image_base64
            db.commit()
        except Exception as e:
            logger.warning(f"Не удалось сгенерировать изображение QR-кода: {e}")
        
        # Создаем ответ
        qr_response = {
            "id": qr_code.id,
            "token": qr_code.qr_token,
            "amount": qr_code.amount,
            "currency": qr_code.currency,
            "description": qr_code.description,
            "expires_at": qr_code.expires_at.isoformat() if qr_code.expires_at else None,
            "payment_url": qr_code.qr_url
        }
        
        # Логируем создание QR-кода админом
        hybrid_logging_service.log_admin_action(
            db=db,
            action="create_qr_code",
            target=qr_data.name,
            details={
                "qr_name": qr_data.name,
                "amount": qr_data.amount,
                "currency": qr_data.currency,
                "qr_token": qr_response["token"][:20] + "..."
            },
            actor_id=admin.username,
            ip_address=request.client.host if request.client else None
        )
        
        return qr_response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating QR code: {str(e)}")

@router.get("/")
async def get_admin_qr_codes(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Получение QR-кодов созданных администратором
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Получаем QR-коды админа
    qr_codes = db.query(AdminQRCode).filter(
        AdminQRCode.admin_id == admin.id
    ).order_by(AdminQRCode.created_at.desc()).offset(skip).limit(limit).all()
    
    # Отладочная информация
    logger.info(f"Найдено QR кодов админа: {len(qr_codes)}")
    for qr in qr_codes:
        logger.info(f"QR код: ID={qr.id}, admin_id={qr.admin_id}, name={qr.name}")
    
    return [
        {
            "id": qr.id,
            "name": qr.name,
            "token": qr.qr_token,
            "qr_token": qr.qr_token,
            "amount": qr.amount,
            "currency": qr.currency,
            "description": qr.description,
            "status": "active" if qr.is_active else "inactive",
            "expires_at": qr.expires_at.isoformat() if qr.expires_at else None,
            "created_at": qr.created_at.isoformat() if qr.created_at else None,
            "is_expired": qr.expires_at and qr.expires_at < datetime.now() if qr.expires_at else False,
            "payment_url": qr.qr_url
        }
        for qr in qr_codes
    ]

@router.get("/stats")
async def get_admin_qr_codes_stats(
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Статистика QR-кодов администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Получаем все QR-коды админа
    qr_codes = db.query(AdminQRCode).filter(
        AdminQRCode.admin_id == admin.id
    ).all()
    
    # Подсчитываем статистику
    total_qr_codes = len(qr_codes)
    active_qr_codes = len([qr for qr in qr_codes if qr.is_active and (not qr.expires_at or qr.expires_at > datetime.now())])
    expired_qr_codes = len([qr for qr in qr_codes if qr.expires_at and qr.expires_at <= datetime.now()])
    
    # Подсчитываем общую сумму
    total_amount = sum([qr.amount for qr in qr_codes if qr.amount])
    
    # Подсчитываем количество использований (current_uses)
    total_payments = sum([qr.current_uses for qr in qr_codes])
    
    return {
        "total_qr_codes": total_qr_codes,
        "active_qr_codes": active_qr_codes,
        "expired_qr_codes": expired_qr_codes,
        "total_payments": total_payments,
        "total_amount": total_amount,
        "currency": "KGS"  # По умолчанию
    }

@router.get("/{qr_id}")
async def get_admin_qr_code(
    qr_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Получение деталей конкретного QR-кода администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Получаем QR-код админа
    qr_code = db.query(AdminQRCode).filter(
        AdminQRCode.id == qr_id,
        AdminQRCode.admin_id == admin.id
    ).first()
    
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    return {
        "id": qr_code.id,
        "name": qr_code.name,
        "token": qr_code.qr_token,
        "qr_token": qr_code.qr_token,
        "amount": qr_code.amount,
        "currency": qr_code.currency,
        "description": qr_code.description,
        "status": "active" if qr_code.is_active else "inactive",
        "expires_at": qr_code.expires_at.isoformat() if qr_code.expires_at else None,
        "created_at": qr_code.created_at.isoformat() if qr_code.created_at else None,
        "is_expired": qr_code.expires_at and qr_code.expires_at < datetime.now() if qr_code.expires_at else False,
        "payment_url": qr_code.qr_url
    }

@router.get("/{qr_id}/qr-image")
async def get_admin_qr_code_image(
    qr_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Получение изображения QR-кода администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Получаем QR-код админа
    qr_code = db.query(AdminQRCode).filter(
        AdminQRCode.id == qr_id,
        AdminQRCode.admin_id == admin.id
    ).first()
    
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    # Генерируем QR изображение
    from app.services.qr_service import QRService
    qr_image = QRService.generate_qr_image(qr_code.qr_url)
    
    # Возвращаем изображение как base64
    from fastapi.responses import Response
    import base64
    
    # Убираем префикс "data:image/png;base64," если он есть
    if qr_image.startswith("data:image/png;base64,"):
        qr_image = qr_image[22:]
    
    image_data = base64.b64decode(qr_image)
    return Response(content=image_data, media_type="image/png")

@router.delete("/{qr_id}")
async def delete_admin_qr_code(
    qr_id: int,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Удаление QR-кода администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Получаем QR-код админа
    qr_code = db.query(AdminQRCode).filter(
        AdminQRCode.id == qr_id,
        AdminQRCode.admin_id == admin.id
    ).first()
    
    if not qr_code:
        raise HTTPException(status_code=404, detail="QR code not found")
    
    # Проверяем, что QR-код не был использован для платежа
    if qr_code.current_uses > 0:
        raise HTTPException(status_code=400, detail="Cannot delete QR code that has been used for payment")
    
    try:
        db.delete(qr_code)
        db.commit()
        
        # Логируем удаление QR-кода
        hybrid_logging_service.log_admin_action(
            db=db,
            action="delete_qr_code",
            target=f"QR Code {qr_id}",
            details={
                "qr_id": qr_id,
                "amount": qr_code.amount,
                "currency": qr_code.currency
            },
            actor_id=admin.username
        )
        
        return {"message": "QR code deleted successfully", "qr_id": qr_id}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting QR code: {str(e)}")


