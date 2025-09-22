# Dashboard and statistics endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.merchant import MerchantPayment
from app.models.payment import Bank, PaymentRequest
from sqlalchemy import func, and_, desc
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

@router.get("/stats/summary")
async def get_admin_stats_summary(db: Session = Depends(get_db)):
    """Сводная статистика для мониторинга"""
    
    # Считаем общие метрики
    total_transactions = db.query(MerchantPayment).count()
    successful_transactions = db.query(MerchantPayment).filter(
        MerchantPayment.status == 'completed'
    ).count()
    
    success_rate = round((successful_transactions / total_transactions * 100), 1) if total_transactions > 0 else 0
    
    # Средняя сумма успешных платежей
    avg_amount_result = db.query(func.avg(MerchantPayment.amount)).filter(
        MerchantPayment.status == 'completed'
    ).scalar()
    avg_amount = float(avg_amount_result) if avg_amount_result else 0
    
    return {
        "total_transactions": total_transactions,
        "successful_transactions": successful_transactions,
        "success_rate": success_rate,
        "avg_amount": avg_amount
    }

@router.get("/system/stats")
async def get_system_stats(db: Session = Depends(get_db)):
    """
    Общая статистика системы для дашборда
    """
    from app.models.payment import Bank, TransactionRecord
    from app.models.merchant import Merchant
    from app.models.admin import Admin
    
    # Подсчитываем основные метрики
    total_banks = db.query(Bank).count()
    active_banks = db.query(Bank).filter(Bank.is_active == True).count()
    total_payments = db.query(PaymentRequest).count()
    total_merchants = db.query(Merchant).count()
    total_admins = db.query(Admin).count()
    total_transactions = db.query(TransactionRecord).count()
    
    # Статистика за сегодня
    from datetime import datetime, timedelta
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    today_payments = db.query(PaymentRequest)\
        .filter(PaymentRequest.created_at >= today_start)\
        .count()
    today_transactions = db.query(TransactionRecord)\
        .filter(TransactionRecord.processed_at >= today_start)\
        .count()
    
    return {
        "total_banks": total_banks,
        "active_banks": active_banks,
        "total_payments": total_payments,
        "today_payments": today_payments,
        "total_merchants": total_merchants,
        "total_admins": total_admins,
        "total_transactions": total_transactions,
        "today_transactions": today_transactions,
        "system_status": "healthy"
    }

@router.get("/dashboard-summary")
async def get_dashboard_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Новый эндпоинт для админского дашборда с KPI, графиками и сводками
    """
    
    # Определяем временные границы - используем UTC, но корректно для полных суток
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)  # Следующий день 00:00
    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start  # today_start уже 00:00 текущего дня
    week_ago = today_start - timedelta(days=7)
    
    # === KPI за сегодня с динамикой ===
    
    # Оборот за сегодня (от 00:00 до 24:00 текущего дня)
    today_revenue_query = db.query(func.sum(MerchantPayment.amount)).filter(
        and_(
            MerchantPayment.created_at >= today_start,
            MerchantPayment.created_at < today_end,  # Добавляем верхнюю границу
            MerchantPayment.status == 'completed'
        )
    )
    today_revenue = float(today_revenue_query.scalar() or 0)
    
    # Оборот за вчера (полные сутки)
    yesterday_revenue_query = db.query(func.sum(MerchantPayment.amount)).filter(
        and_(
            MerchantPayment.created_at >= yesterday_start,
            MerchantPayment.created_at < yesterday_end,
            MerchantPayment.status == 'completed'
        )
    )
    yesterday_revenue = float(yesterday_revenue_query.scalar() or 0)
    
    revenue_change = 0.0
    if yesterday_revenue > 0:
        revenue_change = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100
    
    # Успешные платежи за сегодня и вчера
    today_payments_count = db.query(func.count(MerchantPayment.id)).filter(
        and_(
            MerchantPayment.created_at >= today_start,
            MerchantPayment.created_at < today_end,  # Добавляем верхнюю границу
            MerchantPayment.status == 'completed'
        )
    ).scalar() or 0
    
    yesterday_payments_count = db.query(func.count(MerchantPayment.id)).filter(
        and_(
            MerchantPayment.created_at >= yesterday_start,
            MerchantPayment.created_at < yesterday_end,
            MerchantPayment.status == 'completed'
        )
    ).scalar() or 0
    
    payments_change = 0.0
    if yesterday_payments_count > 0:
        payments_change = ((today_payments_count - yesterday_payments_count) / yesterday_payments_count) * 100
    
    # Средний чек за сегодня и вчера
    today_avg_check = today_revenue / max(today_payments_count, 1)
    yesterday_avg_check = yesterday_revenue / max(yesterday_payments_count, 1)
    
    avg_check_change = 0.0
    if yesterday_avg_check > 0:
        avg_check_change = ((today_avg_check - yesterday_avg_check) / yesterday_avg_check) * 100
    
    # Активные алерты (упрощенно - считаем failed платежи как алерты)
    active_alerts = db.query(func.count(MerchantPayment.id)).filter(
        and_(
            MerchantPayment.created_at >= today_start,
            MerchantPayment.created_at < today_end,  # Добавляем верхнюю границу
            MerchantPayment.status == 'failed'
        )
    ).scalar() or 0
    
    # Отладочная информация: проверим общее количество записей MerchantPayment
    total_merchant_payments = db.query(func.count(MerchantPayment.id)).scalar() or 0
    
    # === Данные для графиков ===
    
    # Динамика оборота за 7 дней
    revenue_series = []
    for i in range(7):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        
        day_revenue = db.query(func.sum(MerchantPayment.amount)).filter(
            and_(
                MerchantPayment.created_at >= day_start,
                MerchantPayment.created_at < day_end,
                MerchantPayment.status == 'completed'
            )
        ).scalar() or 0
        
        revenue_series.insert(0, {
            "date": day_start.strftime("%Y-%m-%d"),
            "revenue": float(day_revenue)
        })
    
    # Соотношение статусов за 24 часа (полные сутки)
    status_stats = db.query(
        MerchantPayment.status,
        func.count(MerchantPayment.id)
    ).filter(
        and_(
            MerchantPayment.created_at >= today_start,
            MerchantPayment.created_at < today_end
        )
    ).group_by(MerchantPayment.status).all()
    
    status_distribution = {}
    total_transactions = 0
    for status, count in status_stats:
        status_distribution[status] = count
        total_transactions += count
    
    # Преобразуем в проценты
    status_percentages = {}
    if total_transactions > 0:
        for status, count in status_distribution.items():
            status_percentages[status] = round((count / total_transactions) * 100, 1)
    
    # === Статусы банков ===
    banks = db.query(Bank).all()
    bank_statuses = []
    for bank in banks:
        # Упрощенная логика - считаем банк активным если is_active=True
        status = "ok" if bank.is_active else "error"
        bank_statuses.append({
            "name": bank.name,
            "code": bank.code,
            "status": status
        })
    
    # === Лента последних событий ===
    recent_events = []
    
    # Последние крупные успешные платежи (>10000)
    large_payments = db.query(MerchantPayment).filter(
        and_(
            MerchantPayment.amount >= 10000,
            MerchantPayment.status == 'completed',
            MerchantPayment.created_at >= week_ago
        )
    ).order_by(desc(MerchantPayment.created_at)).limit(3).all()
    
    for payment in large_payments:
        recent_events.append({
            "type": "success",
            "icon": "✅",
            "title": f"Крупный платеж на {payment.amount:,.0f} KGS успешно завершен",
            "description": f"Продавец ID: {payment.merchant_id}",
            "timestamp": payment.created_at.isoformat() if payment.created_at else None
        })
    
    # Последние failed платежи как критические события
    failed_payments = db.query(MerchantPayment).filter(
        and_(
            MerchantPayment.status == 'failed',
            MerchantPayment.created_at >= today_start
        )
    ).order_by(desc(MerchantPayment.created_at)).limit(2).all()
    
    for payment in failed_payments:
        recent_events.append({
            "type": "critical",
            "icon": "🔴",
            "title": "CRITICAL: Платеж завершился ошибкой",
            "description": f"Сумма: {payment.amount} KGS, Продавец ID: {payment.merchant_id}",
            "timestamp": payment.created_at.isoformat() if payment.created_at else None
        })
    
    # Сортируем события по времени (новые сначала)
    recent_events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    recent_events = recent_events[:5]  # Берем только 5 последних
    
    return {
        "kpi": {
            "revenue_today": {
                "value": today_revenue,
                "change_percent": round(revenue_change, 1),
                "trend": "up" if revenue_change > 0 else "down" if revenue_change < 0 else "neutral"
            },
            "payments_today": {
                "value": today_payments_count,
                "change_percent": round(payments_change, 1),
                "trend": "up" if payments_change > 0 else "down" if payments_change < 0 else "neutral"
            },
            "avg_check_today": {
                "value": round(today_avg_check, 0),
                "change_percent": round(avg_check_change, 1),
                "trend": "up" if avg_check_change > 0 else "down" if avg_check_change < 0 else "neutral"
            },
            "active_alerts": {
                "value": active_alerts,
                "severity": "critical" if active_alerts > 10 else "warning" if active_alerts > 5 else "normal"
            }
        },
        "charts": {
            "revenue_trend": revenue_series,
            "status_distribution": status_percentages
        },
        "summaries": {
            "bank_statuses": bank_statuses,
            "recent_events": recent_events
        },
        "debug_info": {
            "total_merchant_payments": total_merchant_payments,
            "today_start": today_start.isoformat(),
            "today_end": today_end.isoformat(),
            "yesterday_start": yesterday_start.isoformat(),
            "yesterday_end": yesterday_end.isoformat()
        },
        "timestamp": now.isoformat()
    }