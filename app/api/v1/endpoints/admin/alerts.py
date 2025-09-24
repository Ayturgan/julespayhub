# Alerts and notifications endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin import AdminFullResponse, AdminProfileUpdate, AdminQRCodeCreate
# from app.services.logging_service import AuditLoggingService  # Больше не используется
from app.services.two_phase_commit_service import two_phase_commit_service
from app.models.payment import PaymentRequest, TransactionStatus    
from app.core.dependencies import get_current_admin_user

from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
import secrets
from typing import Optional

router = APIRouter(prefix="/alerts")

# Алерты - действия
@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """Принятие алерта"""
    from sqlalchemy import text
    db.execute(text("UPDATE bank_alerts SET acknowledged_at = :now WHERE id = :alert_id"), {
        "now": datetime.now(timezone.utc),
        "alert_id": alert_id
    })
    db.commit()
    return {"message": "Алерт принят"}

@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    """Закрытие алерта"""
    from sqlalchemy import text
    db.execute(text("UPDATE bank_alerts SET resolved_at = :now WHERE id = :alert_id"), {
        "now": datetime.now(timezone.utc),
        "alert_id": alert_id
    })
    db.commit()
    return {"message": "Алерт закрыт"}

@router.get("/summary") 
async def get_alerts_summary(db: Session = Depends(get_db)):
    """Сводка по алертам"""
    
    from sqlalchemy import text
    
    # Используем SQL напрямую для работы с таблицей bank_alerts
    total_result = db.execute(text("SELECT COUNT(*) FROM bank_alerts")).scalar()
    total_alerts = total_result or 0
    
    active_result = db.execute(text("SELECT COUNT(*) FROM bank_alerts WHERE resolved_at IS NULL")).scalar()
    active_alerts = active_result or 0
    
    critical_result = db.execute(text("SELECT COUNT(*) FROM bank_alerts WHERE severity = 'critical' AND resolved_at IS NULL")).scalar()
    critical_alerts = critical_result or 0
    
    return {
        "total_alerts": total_alerts,
        "active_alerts": active_alerts,
        "critical_alerts": critical_alerts,
        "resolved_alerts": total_alerts - active_alerts
    }

@router.get("/")
async def get_alerts_list(
    skip: int = 0,
    limit: int = 50,
    severity: Optional[str] = None,
    is_resolved: Optional[bool] = None,
    # current_admin: dict = Depends(get_current_admin_user),  # Временно отключено для демо
    db: Session = Depends(get_db)
):
    """Список алертов с фильтрацией"""
    
    from sqlalchemy import text
    
    # Формируем SQL запрос с фильтрами
    sql = "SELECT id, alert_id, title, message, severity, alert_type, bank_code, created_at, resolved_at FROM bank_alerts WHERE 1=1"
    params = {}
    
    if severity:
        sql += " AND severity = :severity"
        params["severity"] = severity
    
    if is_resolved is not None:
        if is_resolved:
            sql += " AND resolved_at IS NOT NULL"
        else:
            sql += " AND resolved_at IS NULL"
    
    sql += " ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
    params.update({"limit": limit, "skip": skip})
    
    results = db.execute(text(sql), params).fetchall()
    
    return {
        "alerts": [
            {
                "id": row[0],
                "alert_id": row[1],
                "title": row[2],
                "description": row[3],
                "severity": row[4],
                "alert_type": row[5],
                "bank_code": row[6],
                "is_resolved": row[8] is not None,
                "created_at": row[7],
                "resolved_at": row[8]
            }
            for row in results
        ],
        "total": len(results)
    }

@router.post("/create")
async def create_alert(
    message: str,
    severity: str = "info",
    alert_type: str = "system",
    bank_code: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Создание нового алерта"""
    from sqlalchemy import text
    alert_id = f"alert_{int(datetime.now().timestamp())}"
    db.execute(text("""
        INSERT INTO bank_alerts (alert_id, title, message, severity, alert_type, bank_code, created_at) 
        VALUES (:alert_id, :title, :message, :severity, :alert_type, :bank_code, :created_at)
    """), {
        "alert_id": alert_id,
        "title": f"Alert: {message[:50]}...",
        "message": message,
        "severity": severity,
        "alert_type": alert_type,
        "bank_code": bank_code,
        "created_at": datetime.now(timezone.utc)
    })
    db.commit()
    return {"message": "Алерт создан", "alert_id": alert_id}