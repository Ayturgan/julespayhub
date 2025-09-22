# Audit and logging endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body, Request    
from sqlalchemy.orm import Session
from app.database import get_db
# PaymentLog больше не используется для API логирования
from app.services.hybrid_logging_service import hybrid_logging_service

from app.models.merchant import Merchant, MerchantPayment
from app.models.admin import Admin
from sqlalchemy import func, and_, desc
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
import secrets
from typing import Optional, Dict, Any

router = APIRouter()




@router.post("/audit-log/admin-action")
async def audit_admin_action(
    action: str,
    target: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Запись админского действия в аудит"""
    try:
        actor = getattr(request.state, 'current_admin', None)
        actor_id = actor.get('username') if isinstance(actor, dict) else None
        hybrid_logging_service.log_admin_action(
            db=db,
            action=action,
            target=target,
            details=details,
            actor_id=actor_id,
            ip_address=request.client.host if request.client else None
        )
        return {"message": "Recorded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/audit-log")
async def get_audit_log(
    page: int = 1,
    page_size: int = 50,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_type: Optional[str] = None,
    ip_address: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from app.models.audit import AuditLog
    from datetime import datetime
    import json as _json

    q = db.query(AuditLog)

    if date_from:
        q = q.filter(AuditLog.timestamp_utc >= datetime.fromisoformat(date_from.replace('Z','+00:00')))
    if date_to:
        q = q.filter(AuditLog.timestamp_utc <= datetime.fromisoformat(date_to.replace('Z','+00:00')))
    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if status:
        q = q.filter(AuditLog.status == status)
    if actor_id:
        q = q.filter(AuditLog.actor_id == str(actor_id))
    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)
    if ip_address:
        q = q.filter(AuditLog.ip_address == ip_address)
    if search:
        # Простое LIKE по JSON-строке деталей
        q = q.filter(AuditLog.details_json.ilike(f"%{search}%"))

    total = q.count()
    q = q.order_by(AuditLog.timestamp_utc.desc(), AuditLog.id.desc())
    items = q.offset((page-1)*page_size).limit(page_size).all()

    def _parse_details(s):
        if not s:
            return None
        try:
            return _json.loads(s)
        except Exception:
            return s

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [
            {
                "id": i.id,
                "timestamp_utc": i.timestamp_utc,
                "event_type": i.event_type,
                "event_source": i.event_source,
                "actor_type": i.actor_type,
                "actor_id": i.actor_id,
                "status": i.status,
                "ip_address": i.ip_address,
                "details": _parse_details(i.details_json)
            } for i in items
        ]
    }



# === РАСШИРЕННОЕ ЛОГИРОВАНИЕ ===

@router.get("/logs")
async def get_enhanced_logs(
    ip_address: Optional[str] = None,
    bank_code: Optional[str] = None,
    request_type: Optional[str] = None,
    status_code: Optional[int] = None,
    has_error: Optional[bool] = None,
    rate_limited: Optional[bool] = None,
    hours: int = 24,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Получение расширенных логов API (из файлов)
    """
    # В новой системе API логи хранятся в файлах, а не в БД
    # Возвращаем информацию о том, что логи доступны в файлах
    return {
        "message": "API logs are now stored in files, not database",
        "log_files": [
            "logs/qrpayhub_all.jsonl",
            "logs/qrpayhub_api.jsonl",
            "logs/qrpayhub_errors.jsonl"
        ],
        "note": "Use file-based log analysis tools to query these logs",
        "sample_query": "grep 'api_request' logs/qrpayhub_all.jsonl | jq"
    }

@router.get("/logs/errors")
async def get_error_summary(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Сводка по ошибкам API (из файлов)
    """
    # В новой системе ошибки логируются в файлы
    return {
        "message": "Error logs are now stored in files",
        "error_log_file": "logs/qrpayhub_errors.jsonl",
        "note": "Use file-based analysis to get error statistics",
        "sample_query": "grep 'error' logs/qrpayhub_errors.jsonl | jq '.timestamp' | wc -l"
    }

@router.get("/logs/{log_id}")
async def get_log_details(
    log_id: int,
    db: Session = Depends(get_db)
):
    """
    Детальная информация о конкретном логе (недоступно для API логов)
    """
    # API логи теперь хранятся в файлах, а не в БД
    raise HTTPException(
        status_code=404, 
        detail="API log details are not available via API. Logs are stored in files."
    )

@router.post("/logs/cleanup")
async def cleanup_old_logs(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Очистка старых логов (файловые логи очищаются автоматически)
    """
    # Файловые логи очищаются автоматически системой ротации
    return {
        "message": "File-based logs are cleaned up automatically by log rotation",
        "note": "Log files are rotated daily and compressed after 7 days",
        "log_rotation": "Automatic"
    }



# Журнал аудита
@router.get("/audit")
async def get_audit_log(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    action_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получение журнала аудита"""
    try:
        from app.models.audit import AuditLog
        
        query = db.query(AuditLog)
        
        if date_from:
            query = query.filter(AuditLog.timestamp_utc >= datetime.fromisoformat(date_from.replace('Z','+00:00')))
        if date_to:
            query = query.filter(AuditLog.timestamp_utc <= datetime.fromisoformat(date_to.replace('Z','+00:00')))
        if action_type:
            query = query.filter(AuditLog.event_type == action_type)
        
        logs = query.order_by(AuditLog.timestamp_utc.desc()).limit(50).all()
        
        return [
            {
                "id": log.id,
                "timestamp": log.timestamp_utc.isoformat(),
                "user": log.actor_id,
                "action": log.event_type,
                "resource": log.event_source,
                "details": log.details_json
            }
            for log in logs
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get audit log: {str(e)}")

# Мониторинг
@router.get("/monitoring/summary")
async def get_monitoring_summary(
    period: str = "24h",
    bank: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Сводка мониторинга"""
    try:
        # Получаем реальные метрики из логов
        from datetime import datetime, timedelta
        
        if period == "24h":
            since = datetime.now() - timedelta(hours=24)
        elif period == "7d":
            since = datetime.now() - timedelta(days=7)
        else:
            since = datetime.now() - timedelta(hours=1)
        
        # Подсчитываем логи за период
        total_logs = db.query(PaymentLog).filter(PaymentLog.created_at >= since).count()
        error_logs = db.query(PaymentLog).filter(
            and_(PaymentLog.created_at >= since, PaymentLog.error_message.isnot(None))
        ).count()
        
        error_rate = (error_logs / total_logs * 100) if total_logs > 0 else 0
        
        return {
            "live_metrics": {
                "active_sessions": 25,  # Заглушка
                "requests_per_second": 12.5,  # Заглушка
                "error_rate": round(error_rate, 2),
                "avg_response_time": 120  # Заглушка
            },
            "period_stats": {
                "total_requests": total_logs,
                "successful_requests": total_logs - error_logs,
                "failed_requests": error_logs,
                "avg_response_time": 125  # Заглушка
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get monitoring summary: {str(e)}")

# ТОП продавцов
@router.get("/merchants/top")
async def get_top_merchants(
    period: str = "month",
    db: Session = Depends(get_db)
):
    """ТОП продавцов по обороту"""
    # Рассчитываем период
    now = datetime.now(timezone.utc)
    if period == "day":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now - timedelta(days=7)
    else:  # month
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Получаем топ продавцов
    top_merchants = db.query(
        Merchant.id,
        Merchant.name,
        func.sum(MerchantPayment.amount).label('total_revenue'),
        func.count(MerchantPayment.id).label('payments_count')
    ).join(
        MerchantPayment, MerchantPayment.merchant_id == Merchant.id
    ).filter(
        and_(
            MerchantPayment.status == 'completed',
            MerchantPayment.created_at >= start_date
        )
    ).group_by(
        Merchant.id, Merchant.name
    ).order_by(
        func.sum(MerchantPayment.amount).desc()
    ).limit(10).all()
    
    return [
        {
            "merchant_id": row.id,
            "name": row.name,
            "revenue": float(row.total_revenue or 0),
            "payments_count": row.payments_count
        }
        for row in top_merchants
    ]
