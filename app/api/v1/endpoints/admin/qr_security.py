# QR security endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.enums import TransactionStatus
from app.models.settings import SystemSetting
from app.services.qr_security_service import QRSecurityService
from app.services.reference_service import PaymentReferenceService
from app.core.config import settings
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

# === УПРАВЛЕНИЕ PAYMENT REFERENCE ===

@router.get("/references/stats")
async def get_reference_statistics(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Статистика по payment_reference
    """
    return PaymentReferenceService.get_reference_statistics(db, days)

@router.get("/references/duplicates")
async def find_duplicate_references(db: Session = Depends(get_db)):
    """
    Поиск дублированных payment_reference
    """
    duplicates = PaymentReferenceService.find_duplicate_references(db)
    
    return {
        "total_duplicates": len(duplicates),
        "duplicates": duplicates
    }






# === QR БЕЗОПАСНОСТЬ ===



@router.post("/qr/create-secure")
async def create_secure_qr(
    receiver_name: str,
    receiver_account: str,
    receiver_bank_code: str,
    description: str,
    amount: Optional[float] = None,
    currency: str = "KGS",
    enhanced_security: bool = True,
    db: Session = Depends(get_db)
):
    """
    Создание QR-кода с максимальной защитой
    """
    from app.services.qr_service import QRService
    
    try:
        # Подготавливаем данные для создания платежа
        payment_data = {
            "receiver_name": receiver_name,
            "receiver_account": receiver_account,
            "receiver_bank_code": receiver_bank_code,
            "description": description,
            "amount": amount,
            "currency": currency
        }
        
        # Создаем платежный запрос через unified-схему
        from app.schemas.unified import UnifiedPaymentCreate
        payment_request = UnifiedPaymentCreate(
            amount=amount or 0,
            currency=currency,
            description=description,
            receiver_name=receiver_name,
            receiver_account=receiver_account,
            receiver_bank_code=receiver_bank_code
        )
        
        # Создаем QR с защитой через двухфазный коммит
        from app.services.two_phase_commit_service import two_phase_commit_service
        
        # Создаем базовый платежный запрос
        payment_request_obj = PaymentRequest(
            amount=payment_request.amount,
            currency=payment_request.currency,
            description=payment_request.description,
            receiver_name=payment_request.receiver_name,
            receiver_account=payment_request.receiver_account,
            receiver_bank_code=payment_request.receiver_bank_code,
            status=TransactionStatus.PENDING
        )
        
        db.add(payment_request_obj)
        db.commit()
        db.refresh(payment_request_obj)
        
        # Инициируем двухфазную транзакцию
        qr_response = await two_phase_commit_service.execute_transaction(
            db=db,
            payment_request=payment_request_obj,
            receiver_bank_code=payment_request.receiver_bank_code
        )
        
        # Генерируем отчет о безопасности
        security_report = QRSecurityService.generate_qr_security_report(qr_response.qr_url)
        
        return {
            "qr_data": {
                "qr_url": qr_response.qr_url,
                "token": qr_response.token,
                "expires_in": qr_response.expires_in
            },
            "security_report": security_report,
            "created_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Secure QR creation error: {str(e)}"
        )

@router.get("/qr/security-settings")
async def get_qr_security_settings():
    """
    Получение текущих настроек безопасности QR
    """
    return {
        "security_settings": {
            "max_qr_lifetime_minutes": QRSecurityService.MAX_QR_LIFETIME,
            "min_qr_lifetime_minutes": QRSecurityService.MIN_QR_LIFETIME,
            "allowed_domains": QRSecurityService.ALLOWED_DOMAINS,
            "default_expires_minutes": settings.QR_TOKEN_EXPIRE_MINUTES
        },
        "security_features": {
            "url_signing": "enabled",
            "token_validation": "enabled",
            "domain_validation": "enabled",
            "timestamp_validation": "enabled",
            "suspicious_pattern_detection": "enabled",
            "checksum_validation": "enabled"
        },
        "recommendations": [
            "Используйте HTTPS для всех QR-кодов",
            "Устанавливайте короткое время жизни для QR-кодов",
            "Включайте дополнительные параметры безопасности",
            "Регулярно проверяйте логи на подозрительную активность",
            "Обучайте пользователей проверять подлинность QR-кодов"
        ]
    }

@router.put("/qr/security-settings")
async def update_qr_security_settings(
    max_qr_lifetime_minutes: int,
    min_qr_lifetime_minutes: int,
    allowed_domains: Optional[List[str]] = None,
    default_expires_minutes: int = 10,
    payload: Optional[Dict[str, Any]] = Body(None),
    db: Session = Depends(get_db)
):
    """
    Обновление настроек безопасности QR и применение в рантайме
    """
    if min_qr_lifetime_minutes < 1:
        raise HTTPException(status_code=400, detail="min_qr_lifetime_minutes must be >= 1")
    if max_qr_lifetime_minutes < min_qr_lifetime_minutes:
        raise HTTPException(status_code=400, detail="max must be >= min")
    # Поддержка как query-передачи, так и JSON body: {"allowed_domains": [...]}
    if (allowed_domains is None) and payload and isinstance(payload, dict):
        body_domains = payload.get("allowed_domains")
        if isinstance(body_domains, list):
            allowed_domains = [str(d) for d in body_domains if isinstance(d, str) and d.strip()]
    # Нормализуем список доменов; допускаем пустой список как "без ограничений"
    if allowed_domains is None:
        allowed_domains = []
    else:
        allowed_domains = [str(d).strip() for d in allowed_domains if isinstance(d, str)]
    if default_expires_minutes < min_qr_lifetime_minutes or default_expires_minutes > max_qr_lifetime_minutes:
        raise HTTPException(status_code=400, detail="default_expires_minutes must be within [min, max]")

    payload = {
        "max_qr_lifetime_minutes": int(max_qr_lifetime_minutes),
        "min_qr_lifetime_minutes": int(min_qr_lifetime_minutes),
        "allowed_domains": list(allowed_domains),
        "default_expires_minutes": int(default_expires_minutes)
    }

    # Сохраняем в БД (upsert)
    import json as _json
    setting = db.query(SystemSetting).filter(SystemSetting.key == "qr_security").first()
    if setting:
        setting.value_json = _json.dumps(payload, ensure_ascii=False)
    else:
        setting = SystemSetting(key="qr_security", value_json=_json.dumps(payload, ensure_ascii=False))
        db.add(setting)
    db.commit()

    # Применяем в рантайме
    from app.services.qr_security_service import QRSecurityService as QSS
    QSS.MAX_QR_LIFETIME = payload["max_qr_lifetime_minutes"]
    QSS.MIN_QR_LIFETIME = payload["min_qr_lifetime_minutes"]
    QSS.ALLOWED_DOMAINS = payload["allowed_domains"]
    settings.QR_TOKEN_EXPIRE_MINUTES = payload["default_expires_minutes"]

    return {"message": "QR security settings updated", "applied": payload}

@router.post("/qr/validate")
async def validate_qr_security(
    qr_url: str,
    strict_mode: bool = False
):
    """
    Валидация безопасности QR-кода
    """
    try:
        validation_result = QRSecurityService.validate_qr_url(qr_url, strict_mode)
        
        return {
            "qr_url": qr_url,
            "validation_result": validation_result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"QR validation error: {str(e)}"
        )
