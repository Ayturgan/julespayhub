# Billing and financial reporting endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.billing_service import BillingService
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

# === БИЛЛИНГОВАЯ СИСТЕМА ===

@router.get("/billing/summary")
async def get_billing_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    bank_code: Optional[str] = None,
    currency: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Сводка по биллингу и финансовой отчетности
    """
    # Парсим даты
    start_dt = None
    end_dt = None
    
    if start_date:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    if end_date:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    
    return BillingService.get_billing_summary(
        db=db,
        start_date=start_dt,
        end_date=end_dt,
        bank_code=bank_code,
        currency=currency
    )

@router.get("/billing/daily-stats")
async def get_daily_billing_stats(
    days: int = 30,
    bank_code: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Ежедневная статистика по платежам
    """
    return BillingService.get_daily_stats(
        db=db,
        days=days,
        bank_code=bank_code
    )

@router.get("/billing/top-receivers")
async def get_top_receivers(
    days: int = 30,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Топ получателей платежей
    """
    return BillingService.get_top_receivers(
        db=db,
        days=days,
        limit=limit
    )

@router.get("/billing/export")
async def export_billing_data(
    start_date: str,
    end_date: str,
    format_type: str = "json",
    db: Session = Depends(get_db)
):
    """
    Экспорт биллинговых данных
    """
    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    
    data = BillingService.export_billing_data(
        db=db,
        start_date=start_dt,
        end_date=end_dt,
        format_type=format_type
    )
    
    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date
        },
        "format": format_type,
        "total_records": len(data),
        "data": data
    }

@router.put("/billing/{transaction_id}/status")
async def update_billing_status(
    transaction_id: str,
    new_status: str,
    reason: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Обновление статуса биллинговой записи
    """
    record = BillingService.update_billing_status(
        db=db,
        transaction_id=transaction_id,
        new_status=new_status,
        reason=reason
    )
    
    if not record:
        raise HTTPException(status_code=404, detail="Billing record not found")
    
    return {
        "message": f"Billing status updated to {new_status}",
        "transaction_id": transaction_id,
        "new_status": new_status,
        "updated_at": record.updated_at.isoformat()
    }
