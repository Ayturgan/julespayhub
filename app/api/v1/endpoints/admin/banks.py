# Bank management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank
from app.services.auth_service import BankAuthService
from app.core.dependencies import check_rate_limit, get_current_admin_user
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import secrets
import json

router = APIRouter(prefix="/banks")

# === УПРАВЛЕНИЕ БАНКАМИ ===

@router.post("/")
async def create_bank(bank_data: dict, db: Session = Depends(get_db)):
    """
    Создание нового банка-партнера
    Для MVP - без аутентификации админа
    """
    try:
        # Генерируем случайные токены
        access_token = f"bank_{secrets.token_urlsafe(32)}"
        hmac_secret = secrets.token_urlsafe(64)
        
        bank = BankAuthService.create_bank(
            db=db,
            code=bank_data["code"],
            name=bank_data["name"],
            access_token=access_token,
            hmac_secret=hmac_secret,
            allowed_ips=bank_data.get("allowed_ips"),
            webhook_url=bank_data.get("webhook_url")
        )
        
        return {
            "id": bank.id,
            "code": bank.code,
            "name": bank.name,
            "access_token": access_token,
            "hmac_secret": hmac_secret,
            "message": "Банк успешно создан. Сохраните access_token и hmac_secret!"
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/")
async def list_banks(
    # current_admin: dict = Depends(get_current_admin_user),  # Временно отключено для демо
    db: Session = Depends(get_db)
):
    """
    Список всех банков (без секретов)
    """
    try:
        banks = db.query(Bank).all()
        return {
            "banks": [
                {
                    "id": bank.id,
                    "code": bank.code,
                    "name": bank.name,
                    "is_active": bank.is_active,
                    "created_at": bank.created_at,
                    "last_used_at": bank.last_used_at,
                    "webhook_url": bank.webhook_url
                }
                for bank in banks
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/dropdown")
async def get_banks_for_dropdown(
    db: Session = Depends(get_db)
):
    """
    Список банков для выпадающего списка с полными данными
    """
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
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/{bank_id}")
async def get_bank_details(
    bank_id: int,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Получение деталей банка по ID
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    
    return {
        "id": bank.id,
        "name": bank.name,
        "code": bank.code,
        "bik": bank.bik,
        "is_active": bank.is_active,
        "webhook_url": bank.webhook_url,
        "allowed_ips": bank.allowed_ips,
        "created_at": bank.created_at.isoformat() if bank.created_at else None,
        "last_used_at": bank.last_used_at.isoformat() if bank.last_used_at else None
    }

@router.put("/{bank_id}")
async def update_bank(
    bank_id: int,
    bank_data: dict,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Обновление данных банка
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    
    # Обновляем поля
    if "name" in bank_data:
        bank.name = bank_data["name"]
    if "code" in bank_data:
        bank.code = bank_data["code"]
    if "bik" in bank_data:
        bank.bik = bank_data["bik"]
    if "webhook_url" in bank_data:
        bank.webhook_url = bank_data["webhook_url"]
    if "allowed_ips" in bank_data:
        bank.allowed_ips = bank_data["allowed_ips"]
    
    db.commit()
    db.refresh(bank)
    
    return {
        "id": bank.id,
        "name": bank.name,
        "code": bank.code,
        "bik": bank.bik,
        "is_active": bank.is_active,
        "webhook_url": bank.webhook_url,
        "allowed_ips": bank.allowed_ips,
        "message": "Банк успешно обновлен"
    }

@router.get("/performance")
async def get_banks_performance(
    # current_admin: dict = Depends(get_current_admin_user),  # Временно отключено для демо
    db: Session = Depends(get_db)
):
    """
    Производительность банков для дашборда
    """
    try:
        banks = db.query(Bank).all()
        return {
            "banks": [
                {
                    "id": bank.id,
                    "code": bank.code,
                    "name": bank.name,
                    "is_active": bank.is_active,
                    "created_at": bank.created_at,
                    "last_used_at": bank.last_used_at
                }
                for bank in banks
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")



@router.post("/{bank_id}/regenerate-keys")
async def regenerate_bank_keys(bank_id: int, db: Session = Depends(get_db)):
    """
    Перевыпуск access_token и hmac_secret для банка. Возвращает новые ключи ОДИН раз.
    Клиент обязан сохранить их — повторно показать нельзя (МVP: не храним историю версий ключей).
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")

    new_access_token = f"bank_{secrets.token_urlsafe(32)}"
    new_hmac_secret = secrets.token_urlsafe(64)

    bank.access_token = new_access_token
    bank.hmac_secret = new_hmac_secret
    db.commit()
    db.refresh(bank)

    return {
        "message": "Новые ключи сгенерированы. Сохраните их — повторно показать нельзя.",
        "bank_id": bank.id,
        "code": bank.code,
        "name": bank.name,
        "access_token": new_access_token,
        "hmac_secret": new_hmac_secret
    }

@router.put("/{bank_id}/toggle-active")
async def toggle_bank_active(bank_id: int, db: Session = Depends(get_db)):
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    bank.is_active = not bank.is_active
    db.commit()
    db.refresh(bank)
    return {"bank_id": bank.id, "is_active": bank.is_active}

@router.put("/{bank_id}/settings")
async def update_bank_settings(
    bank_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    Обновление настроек банка (без секретов): webhook_url, allowed_ips, allowed_user_agents,
    required_headers, validation_rules.
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")

    import json as _json

    if "webhook_url" in payload:
        bank.webhook_url = payload.get("webhook_url") or None

    if "allowed_ips" in payload:
        ips = payload.get("allowed_ips")
        if ips is not None and not isinstance(ips, list):
            raise HTTPException(status_code=400, detail="allowed_ips must be a list or null")
        bank.allowed_ips = _json.dumps(ips) if ips is not None else None

    if "allowed_user_agents" in payload:
        uas = payload.get("allowed_user_agents")
        if uas is not None and not isinstance(uas, list):
            raise HTTPException(status_code=400, detail="allowed_user_agents must be a list or null")
        bank.allowed_user_agents = _json.dumps(uas) if uas is not None else None

    if "required_headers" in payload:
        rh = payload.get("required_headers")
        if rh is not None and not isinstance(rh, list):
            raise HTTPException(status_code=400, detail="required_headers must be a list or null")
        bank.required_headers = _json.dumps(rh) if rh is not None else None

    if "validation_rules" in payload:
        vr = payload.get("validation_rules")
        if vr is not None and not isinstance(vr, dict):
            raise HTTPException(status_code=400, detail="validation_rules must be an object or null")
        bank.validation_rules = _json.dumps(vr, ensure_ascii=False) if vr is not None else None

    db.commit()
    db.refresh(bank)

    return {"message": "Bank settings updated"}

@router.put("/{bank_id}/toggle")
async def toggle_bank_status(bank_id: int, db: Session = Depends(get_db)):
    """
    Включить/отключить банк
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    
    bank.is_active = not bank.is_active
    db.commit()
    
    return {
        "message": f"Банк {bank.name} {'активирован' if bank.is_active else 'деактивирован'}",
        "is_active": bank.is_active
    }