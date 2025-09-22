# Error handling and monitoring endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import PaymentLog
from app.services.error_handling_service import ErrorHandlingService, StandardError, ErrorCode
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

# === ОБРАБОТКА ОШИБОК И МОНИТОРИНГ ===

@router.get("/errors/summary")
async def get_error_summary(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Сводка ошибок за указанный период
    """
    try:
        # Получаем логи с ошибками за указанный период
        from datetime import datetime, timedelta
        since = datetime.now() - timedelta(hours=hours)
        
        error_logs = db.query(PaymentLog).filter(
            PaymentLog.created_at >= since,
            PaymentLog.error_message.isnot(None)
        ).all()
        
        # Группируем ошибки
        error_summary = {}
        by_endpoint = {}
        by_bank = {}
        
        for log in error_logs:
            # По типу ошибки
            error_type = log.error_message.split(':')[0] if log.error_message else 'Unknown'
            error_summary[error_type] = error_summary.get(error_type, 0) + 1
            
            # По эндпоинту
            endpoint = log.endpoint or 'unknown'
            by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
            
            # По банку
            bank_code = log.bank_code or 'unknown'
            by_bank[bank_code] = by_bank.get(bank_code, 0) + 1
        
        return {
            "period_hours": hours,
            "total_errors": len(error_logs),
            "error_types": [
                {"type": k, "count": v} 
                for k, v in sorted(error_summary.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_endpoint": [
                {"endpoint": k, "count": v}
                for k, v in sorted(by_endpoint.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_bank": [
                {"bank_code": k, "count": v}
                for k, v in sorted(by_bank.items(), key=lambda x: x[1], reverse=True)
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error summary generation failed: {str(e)}"
        )

@router.get("/errors/summary")
async def get_error_summary(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Сводка ошибок за указанный период
    """
    try:
        # Получаем логи с ошибками за указанный период
        from datetime import datetime, timedelta
        since = datetime.now() - timedelta(hours=hours)
        
        error_logs = db.query(PaymentLog).filter(
            PaymentLog.created_at >= since,
            PaymentLog.error_message.isnot(None)
        ).all()
        
        # Группируем ошибки
        error_summary = {}
        by_endpoint = {}
        by_bank = {}
        
        for log in error_logs:
            # По типу ошибки
            error_type = log.error_message.split(':')[0] if log.error_message else 'Unknown'
            error_summary[error_type] = error_summary.get(error_type, 0) + 1
            
            # По эндпоинту
            endpoint = log.endpoint or 'unknown'
            by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
            
            # По банку
            bank_code = log.bank_code or 'unknown'
            by_bank[bank_code] = by_bank.get(bank_code, 0) + 1
        
        return {
            "period_hours": hours,
            "total_errors": len(error_logs),
            "error_types": [
                {"type": k, "count": v} 
                for k, v in sorted(error_summary.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_endpoint": [
                {"endpoint": k, "count": v}
                for k, v in sorted(by_endpoint.items(), key=lambda x: x[1], reverse=True)
            ],
            "by_bank": [
                {"bank_code": k, "count": v}
                for k, v in sorted(by_bank.items(), key=lambda x: x[1], reverse=True)
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error summary generation failed: {str(e)}"
        )

@router.get("/errors/codes")
async def get_error_codes():
    """
    Получение списка всех кодов ошибок системы
    """
    
    error_codes = []
    for code in ErrorCode:
        http_status = ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(code, 500)
        
        error_codes.append({
            "code": code.value,
            "name": code.name,
            "http_status": http_status,
            "category": _get_error_category(code)
        })
    
    # Группируем по категориям
    by_category = {}
    for error_code in error_codes:
        category = error_code["category"]
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(error_code)
    
    return {
        "total_codes": len(error_codes),
        "error_codes": error_codes,
        "by_category": by_category,
        "categories": list(by_category.keys())
    }

def _get_error_category(error_code: ErrorCode) -> str:
    """Определение категории ошибки по коду"""
    
    code_value = error_code.value
    
    if code_value.startswith("AUTH_"):
        return "Authentication & Authorization"
    elif code_value.startswith("VAL_"):
        return "Validation"
    elif code_value.startswith("BIZ_"):
        return "Business Logic"
    elif code_value.startswith("RATE_"):
        return "Rate Limiting"
    elif code_value.startswith("QR_"):
        return "QR Security"
    elif code_value.startswith("SYS_"):
        return "System Errors"
    elif code_value.startswith("WH_"):
        return "Webhook Errors"
    else:
        return "Other"
