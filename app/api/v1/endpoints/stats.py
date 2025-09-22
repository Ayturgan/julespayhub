from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank, PaymentRequest
from app.models.merchant import Merchant, MerchantPayment
from app.models.admin import Admin
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

router = APIRouter()

@router.get("/dashboard-stats")
async def get_dashboard_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Получение статистики для дашборда"""
    
    # Подсчитываем активные банки
    active_banks = db.query(Bank).filter(Bank.is_active == True).count()
    
    # Подсчитываем платежи за сегодня
    today = datetime.now(timezone.utc).date()
    today_payments = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= today
    ).count()
    
    # Подсчитываем общую сумму платежей за сегодня
    today_amount = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= today,
        PaymentRequest.is_paid == True
    ).with_entities(PaymentRequest.amount).all()
    total_amount = sum(payment.amount for payment in today_amount if payment.amount) if today_amount else 0
    
    # Подсчитываем активных продавцов
    active_merchants = db.query(Merchant).filter(Merchant.is_active == True).count()
    
    # Подсчитываем успешные платежи за последние 24 часа
    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    successful_payments = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= last_24h,
        PaymentRequest.is_paid == True
    ).count()
    
    # Подсчитываем общее количество платежей за последние 24 часа
    total_payments_24h = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= last_24h
    ).count()
    
    # Вычисляем процент успешных платежей
    success_rate = (successful_payments / total_payments_24h * 100) if total_payments_24h > 0 else 0
    
    # Получаем последние платежи
    recent_payments = db.query(PaymentRequest).order_by(
        PaymentRequest.created_at.desc()
    ).limit(5).all()
    
    recent_payments_data = []
    for payment in recent_payments:
        recent_payments_data.append({
            "id": payment.id,
            "amount": payment.amount or 0,
            "currency": payment.currency,
            "status": "paid" if payment.is_paid else "pending",
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "receiver_name": payment.receiver_name
        })
    
    return {
        "active_banks": active_banks,
        "today_payments": today_payments,
        "total_amount_today": total_amount,
        "active_merchants": active_merchants,
        "success_rate_24h": round(success_rate, 1),
        "successful_payments_24h": successful_payments,
        "total_payments_24h": total_payments_24h,
        "recent_payments": recent_payments_data,
        "system_uptime": "99.9%",  # В реальной системе это будет вычисляться
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
