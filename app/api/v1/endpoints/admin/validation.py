# API validation endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank, PaymentLog
from app.services.validation_service import APIValidationService
from app.services.enhanced_validation_service import EnhancedValidationService
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import json

router = APIRouter()

# === ВАЛИДАЦИЯ API ЗАПРОСОВ ===

@router.put("/banks/{bank_id}/validation")
async def update_bank_validation_rules(
    bank_id: int,
    allowed_user_agents: Optional[List[str]] = None,
    required_headers: Optional[List[str]] = None,
    validation_rules: Optional[dict] = None,
    db: Session = Depends(get_db)
):
    """
    Обновление правил валидации для банка
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    
    # Обновляем правила валидации
    if allowed_user_agents is not None:
        bank.allowed_user_agents = json.dumps(allowed_user_agents) if allowed_user_agents else None
    
    if required_headers is not None:
        bank.required_headers = json.dumps(required_headers) if required_headers else None
    
    if validation_rules is not None:
        bank.validation_rules = json.dumps(validation_rules) if validation_rules else None
    
    db.commit()
    db.refresh(bank)
    
    return {
        "message": f"Validation rules updated for bank {bank.name}",
        "bank_id": bank_id,
        "updated_rules": {
            "allowed_user_agents": allowed_user_agents,
            "required_headers": required_headers,
            "validation_rules": validation_rules
        }
    }

@router.get("/banks/{bank_id}/validation")
async def get_bank_validation_rules(
    bank_id: int,
    db: Session = Depends(get_db)
):
    """
    Получение правил валидации банка
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(status_code=404, detail="Bank not found")
    
    # Парсим JSON правила
    allowed_user_agents = None
    if bank.allowed_user_agents:
        try:
            allowed_user_agents = json.loads(bank.allowed_user_agents)
        except json.JSONDecodeError:
            pass
    
    required_headers = None
    if bank.required_headers:
        try:
            required_headers = json.loads(bank.required_headers)
        except json.JSONDecodeError:
            pass
    
    validation_rules = None
    if bank.validation_rules:
        try:
            validation_rules = json.loads(bank.validation_rules)
        except json.JSONDecodeError:
            pass
    
    return {
        "bank_id": bank_id,
        "bank_name": bank.name,
        "bank_code": bank.code,
        "validation_settings": {
            "allowed_user_agents": allowed_user_agents,
            "required_headers": required_headers,
            "validation_rules": validation_rules
        },
        "default_rules": APIValidationService.DEFAULT_VALIDATION_RULES
    }

@router.get("/validation/patterns")
async def get_validation_patterns():
    """
    Получение паттернов валидации системы
    """
    
    return {
        "phone_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("phone", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.PHONE_PATTERNS.items()
        },
        "account_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("account", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.ACCOUNT_PATTERNS.items()
        },
        "bank_code_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("bank_code", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.BANK_CODE_PATTERNS.items()
        },
        "security_checks": {
            "suspicious_patterns_count": len(EnhancedValidationService.SUSPICIOUS_PATTERNS),
            "sql_injection_protection": True,
            "xss_protection": True,
            "dos_protection": True
        },
        "default_limits": {
            limit_name: str(limit_value)
            for limit_name, limit_value in EnhancedValidationService.DEFAULT_LIMITS.items()
        }
    }






@router.get("/validation/patterns")
async def get_validation_patterns():
    """
    Получение паттернов валидации системы
    """
    
    return {
        "phone_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("phone", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.PHONE_PATTERNS.items()
        },
        "account_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("account", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.ACCOUNT_PATTERNS.items()
        },
        "bank_code_patterns": {
            pattern_name: {"regex": pattern, "description": _get_pattern_description("bank_code", pattern_name)}
            for pattern_name, pattern in EnhancedValidationService.BANK_CODE_PATTERNS.items()
        },
        "security_checks": {
            "suspicious_patterns_count": len(EnhancedValidationService.SUSPICIOUS_PATTERNS),
            "sql_injection_protection": True,
            "xss_protection": True,
            "dos_protection": True
        },
        "default_limits": {
            limit_name: str(limit_value)
            for limit_name, limit_value in EnhancedValidationService.DEFAULT_LIMITS.items()
        }
    }



@router.get("/validation/statistics")
async def get_validation_statistics(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Статистика валидации за указанный период
    """
    try:
        # Получаем логи с ошибками валидации за указанный период
        from datetime import datetime, timedelta
        since = datetime.now() - timedelta(hours=hours)
        
        # Ищем логи с ошибками валидации
        validation_logs = db.query(PaymentLog).filter(
            PaymentLog.created_at >= since,
            PaymentLog.error_message.like('%validation%')
        ).all()
        
        # Анализируем типы ошибок валидации
        validation_errors = {}
        by_endpoint = {}
        by_bank = {}
        
        for log in validation_logs:
            if log.error_message:
                # Извлекаем тип ошибки валидации
                if "validation" in log.error_message.lower():
                    error_type = "validation_error"
                    validation_errors[error_type] = validation_errors.get(error_type, 0) + 1
                
                # По эндпоинту
                endpoint = log.endpoint or 'unknown'
                by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
                
                # По банку
                bank_code = log.bank_code or 'unknown'
                by_bank[bank_code] = by_bank.get(bank_code, 0) + 1
        
        return {
            "period_hours": hours,
            "total_validation_issues": len(validation_logs),
            "validation_error_types": [
                {"type": k, "count": v}
                for k, v in sorted(validation_errors.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_endpoint": [
                {"endpoint": k, "count": v}
                for k, v in sorted(by_endpoint.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_bank": [
                {"bank_code": k, "count": v}
                for k, v in sorted(by_bank.items(), key=lambda x: x[1], reverse=True)
            ],
            "validation_health": {
                "error_rate": round((len(validation_logs) / max(1, hours * 60)) * 100, 2),  # Ошибок в час
                "status": "healthy" if len(validation_logs) < hours * 5 else "warning"  # < 5 ошибок в час = здорово
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get validation statistics: {str(e)}"
        )

def _get_pattern_description(pattern_type: str, pattern_name: str) -> str:
    """Получение описания паттерна валидации"""
    
    descriptions = {
        "phone": {
            "kyrgyzstan": "Номера телефонов Кыргызстана (+996, 996, 0 + 9 цифр)",
            "international": "Международный формат (+код страны + номер)",
            "any": "Любой телефонный номер (7-20 символов)"
        },
        "account": {
            "numeric": "Числовой счет (10-20 цифр)",
            "alphanumeric": "Буквенно-цифровой счет (8-25 символов)",
            "iban": "Международный номер банковского счета (IBAN)"
        },
        "bank_code": {
            "kyrgyzstan": "Код банка Кыргызстана (1-2 буквы + 3-5 цифр)",
            "swift": "SWIFT код банка (6 букв + 2 символа + опционально 3 символа)",
            "custom": "Кастомный код банка (3-10 символов)"
        }
    }
    
    return descriptions.get(pattern_type, {}).get(pattern_name, "Специализированный паттерн")