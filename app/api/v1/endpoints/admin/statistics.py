# Unified statistics endpoint for admin
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.payment import Bank, PaymentLog, TransactionRecord
from app.models.merchant import Merchant, MerchantPayment
from app.models.admin import Admin
from sqlalchemy import func, and_, desc
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from enum import Enum
from app.core.dependencies import get_current_admin_user

router = APIRouter(prefix="/statistics")

class MetricType(str, Enum):
    DASHBOARD = "dashboard"
    MERCHANT_QUICK = "merchant_quick"
    MERCHANTS_OVERVIEW = "merchants_overview"
    ADMIN_SUMMARY = "admin_summary"
    SYSTEM = "system"
    DASHBOARD_FULL = "dashboard_full"
    AUDIT_SUMMARY = "audit_summary"
    TOP_MERCHANTS = "top_merchants"
    MONITORING_SUMMARY = "monitoring_summary"
    BANK_STATS = "bank_stats"
    # Новые метрики для графиков
    TURNOVER_7DAYS = "turnover_7days"
    STATUS_DISTRIBUTION = "status_distribution"
    TRANSACTION_LIFETIME_SERIES = "transaction_lifetime_series"
    AVERAGE_CHECK = "average_check"

class PeriodType(str, Enum):
    HOUR_1 = "1h"
    HOUR_24 = "24h"
    DAY_7 = "7d"
    DAY_30 = "30d"
    MONTH = "month"
    YEAR = "year"

@router.get("/")
async def get_unified_statistics(
    metric: MetricType = Query(..., description="Тип метрики"),
    period: PeriodType = Query(PeriodType.DAY_7, description="Период"),
    merchant_id: Optional[int] = Query(None, description="ID продавца для merchant_quick"),
    bank_code: Optional[str] = Query(None, description="Код банка для bank_stats"),
    limit: int = Query(10, description="Лимит для top_merchants"),
    # current_admin: dict = Depends(get_current_admin_user),  # Временно отключено для демо
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Единый эндпоинт для получения всех типов статистики
    """
    try:
        # Определяем период
        now = datetime.now(timezone.utc)
        if period == PeriodType.HOUR_1:
            since = now - timedelta(hours=1)
        elif period == PeriodType.HOUR_24:
            since = now - timedelta(hours=24)
        elif period == PeriodType.DAY_7:
            since = now - timedelta(days=7)
        elif period == PeriodType.DAY_30:
            since = now - timedelta(days=30)
        elif period == PeriodType.MONTH:
            since = now - timedelta(days=30)
        elif period == PeriodType.YEAR:
            since = now - timedelta(days=365)
        else:
            since = now - timedelta(days=7)

        # Выбираем соответствующую функцию
        if metric == MetricType.DASHBOARD:
            return await _get_dashboard_stats(db, since)
        elif metric == MetricType.MERCHANT_QUICK:
            if not merchant_id:
                raise HTTPException(status_code=400, detail="merchant_id required for merchant_quick")
            return await _get_merchant_quick_stats(db, merchant_id, since)
        elif metric == MetricType.MERCHANTS_OVERVIEW:
            return await _get_merchants_overview(db, since)
        elif metric == MetricType.ADMIN_SUMMARY:
            return await _get_admin_summary(db, since)
        elif metric == MetricType.SYSTEM:
            return await _get_system_stats(db, since)
        elif metric == MetricType.DASHBOARD_FULL:
            return await _get_dashboard_full(db, since)
        elif metric == MetricType.AUDIT_SUMMARY:
            return await _get_audit_summary(db, since)
        elif metric == MetricType.TOP_MERCHANTS:
            return await _get_top_merchants(db, since, limit)
        elif metric == MetricType.MONITORING_SUMMARY:
            return await _get_monitoring_summary(db, since)
        elif metric == MetricType.BANK_STATS:
            return await _get_bank_stats(db, since, bank_code)
        elif metric == MetricType.TURNOVER_7DAYS:
            return await _get_turnover_7days(db, since)
        elif metric == MetricType.STATUS_DISTRIBUTION:
            return await _get_status_distribution(db, since)
        elif metric == MetricType.TRANSACTION_LIFETIME_SERIES:
            return await _get_transaction_lifetime_series(db, since)
        elif metric == MetricType.AVERAGE_CHECK:
            return await _get_average_check(db, since)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")

async def _get_dashboard_stats(db: Session, since: datetime) -> Dict[str, Any]:
    """Статистика для дашборда"""
    # Подсчитываем общее количество платежей (за все время)
    total_payments = db.query(PaymentRequest).count()
    
    # Подсчитываем общее количество банков
    total_banks = db.query(Bank).count()
    active_banks = db.query(Bank).filter(Bank.is_active == True).count()
    
    # Подсчитываем общее количество продавцов
    total_merchants = db.query(Merchant).count()
    
    # Подсчитываем объем за последние 24 часа
    today_start = datetime.now(timezone.utc) - timedelta(hours=24)
    today_payments = db.query(PaymentRequest).filter(
        and_(
            PaymentRequest.created_at >= today_start,
            PaymentRequest.is_paid == True
        )
    ).all()
    
    today_total_amount = sum(p.amount for p in today_payments if p.amount)
    
    return {
        "total_payments": total_payments,
        "total_banks": total_banks,
        "active_banks": active_banks,
        "total_merchants": total_merchants,
        "today_total_amount": today_total_amount,
        "period": since.isoformat()
    }

async def _get_merchant_quick_stats(db: Session, merchant_id: int, since: datetime) -> Dict[str, Any]:
    """Быстрая статистика продавца"""
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    
    # Платежи продавца за период
    payments = db.query(PaymentRequest).filter(
        and_(
            PaymentRequest.merchant_id == merchant_id,
            PaymentRequest.created_at >= since
        )
    ).all()
    
    total_payments = len(payments)
    successful_payments = len([p for p in payments if p.is_paid])
    total_amount = sum(p.amount for p in payments if p.is_paid and p.amount)
    
    return {
        "merchant_id": merchant_id,
        "merchant_name": merchant.name,
        "total_payments": total_payments,
        "successful_payments": successful_payments,
        "success_rate": round((successful_payments / total_payments * 100), 2) if total_payments > 0 else 0,
        "total_amount": total_amount,
        "period": since.isoformat()
    }

async def _get_merchants_overview(db: Session, since: datetime) -> Dict[str, Any]:
    """Обзор статистики всех продавцов"""
    # Общая статистика по продавцам
    total_merchants = db.query(Merchant).count()
    active_merchants = db.query(Merchant).filter(Merchant.is_active == True).count()
    
    # Топ продавцов по обороту
    top_merchants = db.query(
        Merchant.id,
        Merchant.name,
        func.count(PaymentRequest.id).label('total_payments'),
        func.sum(PaymentRequest.amount).label('total_amount')
    ).join(PaymentRequest).filter(
        PaymentRequest.created_at >= since
    ).group_by(Merchant.id, Merchant.name).order_by(
        desc(func.sum(PaymentRequest.amount))
    ).limit(10).all()
    
    return {
        "total_merchants": total_merchants,
        "active_merchants": active_merchants,
        "top_merchants": [
            {
                "id": m.id,
                "name": m.name,
                "total_payments": m.total_payments,
                "total_amount": float(m.total_amount or 0)
            }
            for m in top_merchants
        ],
        "period": since.isoformat()
    }

async def _get_admin_summary(db: Session, since: datetime) -> Dict[str, Any]:
    """Сводная статистика для админа"""
    # Основные метрики
    total_banks = db.query(Bank).count()
    active_banks = db.query(Bank).filter(Bank.is_active == True).count()
    total_payments = db.query(PaymentRequest).count()
    total_merchants = db.query(Merchant).count()
    total_admins = db.query(Admin).count()
    
    # Статистика за период
    period_payments = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= since
    ).count()
    
    period_transactions = db.query(TransactionRecord).filter(
        TransactionRecord.processed_at >= since
    ).count()
    
    return {
        "total_banks": total_banks,
        "active_banks": active_banks,
        "total_payments": total_payments,
        "period_payments": period_payments,
        "total_merchants": total_merchants,
        "total_admins": total_admins,
        "period_transactions": period_transactions,
        "system_status": "healthy",
        "period": since.isoformat()
    }

async def _get_system_stats(db: Session, since: datetime) -> Dict[str, Any]:
    """Системная статистика"""
    # Общая статистика системы
    total_banks = db.query(Bank).count()
    active_banks = db.query(Bank).filter(Bank.is_active == True).count()
    total_payments = db.query(PaymentRequest).count()
    total_merchants = db.query(Merchant).count()
    total_admins = db.query(Admin).count()
    total_transactions = db.query(TransactionRecord).count()
    
    # Статистика за сегодня
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    
    today_payments = db.query(PaymentRequest).filter(
        PaymentRequest.created_at >= today_start
    ).count()
    
    today_transactions = db.query(TransactionRecord).filter(
        TransactionRecord.processed_at >= today_start
    ).count()
    
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

async def _get_dashboard_full(db: Session, since: datetime) -> Dict[str, Any]:
    """Полная сводка дашборда"""
    # Объединяем данные из разных источников
    dashboard_stats = await _get_dashboard_stats(db, since)
    admin_summary = await _get_admin_summary(db, since)
    
    # Дополнительные метрики
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
        **dashboard_stats,
        **admin_summary,
        "total_transactions": total_transactions,
        "successful_transactions": successful_transactions,
        "success_rate": success_rate,
        "avg_amount": avg_amount
    }

async def _get_audit_summary(db: Session, since: datetime) -> Dict[str, Any]:
    """Сводка аудита"""
    # Подсчитываем логи за период
    total_logs = db.query(PaymentLog).filter(PaymentLog.created_at >= since).count()
    error_logs = db.query(PaymentLog).filter(
        and_(PaymentLog.created_at >= since, PaymentLog.error_message.isnot(None))
    ).count()
    
    error_rate = (error_logs / total_logs * 100) if total_logs > 0 else 0
    
    return {
        "total_logs": total_logs,
        "error_logs": error_logs,
        "error_rate": round(error_rate, 2),
        "live_metrics": {
            "active_sessions": 25,  # Заглушка
            "requests_per_second": 12.5,  # Заглушка
            "error_rate": round(error_rate, 2),
            "avg_response_time": 120  # Заглушка
        },
        "period": since.isoformat()
    }

async def _get_top_merchants(db: Session, since: datetime, limit: int) -> Dict[str, Any]:
    """Топ продавцов по обороту"""
    top_merchants = db.query(
        Merchant.id,
        Merchant.name,
        func.count(PaymentRequest.id).label('total_payments'),
        func.sum(PaymentRequest.amount).label('total_amount')
    ).join(PaymentRequest).filter(
        PaymentRequest.created_at >= since
    ).group_by(Merchant.id, Merchant.name).order_by(
        desc(func.sum(PaymentRequest.amount))
    ).limit(limit).all()
    
    return {
        "top_merchants": [
            {
                "id": m.id,
                "name": m.name,
                "total_payments": m.total_payments,
                "total_amount": float(m.total_amount or 0)
            }
            for m in top_merchants
        ],
        "limit": limit,
        "period": since.isoformat()
    }

async def _get_monitoring_summary(db: Session, since: datetime) -> Dict[str, Any]:
    """Сводка мониторинга"""
    # Requests in specified period - используем PaymentRequest вместо PaymentLog
    total_requests = db.query(func.count(PaymentRequest.id)).filter(
        PaymentRequest.created_at >= since
    ).scalar() or 0
    
    # Успешные платежи
    successful_requests = db.query(func.count(PaymentRequest.id)).filter(and_(
        PaymentRequest.created_at >= since,
        PaymentRequest.status == "COMPLETED"
    )).scalar() or 0
    
    # Ошибки (платежи со статусом не COMPLETED)
    error_requests = total_requests - successful_requests
    
    # Среднее время ответа (заглушка)
    avg_response_ms = 150  # 150ms среднее время
    
    # Successful payments in period (TPM = transactions per minute)
    tpm = successful_requests

    # Convert to per-minute rates
    period_minutes = (datetime.now(timezone.utc) - since).total_seconds() / 60
    qps = total_requests / period_minutes if period_minutes > 0 else 0
    tpm_rate = tpm / period_minutes if period_minutes > 0 else 0
    error_rate = (error_requests / total_requests * 100.0) if total_requests > 0 else 0.0

    # Получаем количество активных банков и мерчантов
    active_banks = db.query(func.count(Bank.id)).filter(Bank.is_active == True).scalar() or 0
    active_merchants = db.query(func.count(Merchant.id)).filter(Merchant.is_active == True).scalar() or 0
    
    return {
        "summary": {
            "total_requests": total_requests,
            "error_requests": error_requests,
            "successful_requests": total_requests - error_requests,
            "error_rate": round(error_rate, 2),
            "avg_response_time_ms": avg_response_ms,
            "qps": round(qps, 2),
            "tpm": round(tpm_rate, 2)
        },
        "active_banks": active_banks,
        "active_merchants": active_merchants,
        "period": since.isoformat()
    }

async def _get_bank_stats(db: Session, since: datetime, bank_code: Optional[str] = None) -> Dict[str, Any]:
    """Статистика по банкам"""
    # Avg response per bank
    avg_resp_query = db.query(PaymentLog.bank_code, func.avg(PaymentLog.request_duration_ms)).filter(and_(
        PaymentLog.created_at >= since, 
        PaymentLog.bank_code.isnot(None), 
        PaymentLog.request_duration_ms.isnot(None)
    ))
    
    if bank_code:
        avg_resp_query = avg_resp_query.filter(PaymentLog.bank_code == bank_code)
    
    avg_resp_rows = avg_resp_query.group_by(PaymentLog.bank_code).all()
    avg_map = {row[0]: int(row[1] or 0) for row in avg_resp_rows}

    # Error counts per bank
    err_query = db.query(PaymentLog.bank_code, func.count(PaymentLog.id)).filter(and_(
        PaymentLog.created_at >= since, 
        PaymentLog.bank_code.isnot(None), 
        PaymentLog.error_message.isnot(None)
    ))
    
    if bank_code:
        err_query = err_query.filter(PaymentLog.bank_code == bank_code)
    
    err_rows = err_query.group_by(PaymentLog.bank_code).all()
    err_map = {row[0]: row[1] for row in err_rows}

    # Successful payments per bank
    succ_query = db.query(TransactionRecord.bank_code, func.count(TransactionRecord.id)).filter(and_(
        TransactionRecord.processed_at >= since, 
        TransactionRecord.status == "success"
    ))
    
    if bank_code:
        succ_query = succ_query.filter(TransactionRecord.bank_code == bank_code)
    
    succ_rows = succ_query.group_by(TransactionRecord.bank_code).all()
    succ_map = {row[0]: row[1] for row in succ_rows}

    # Compose list for banks
    banks_query = db.query(Bank)
    if bank_code:
        banks_query = banks_query.filter(Bank.code == bank_code)
    
    banks = banks_query.all()
    results = []
    
    for bank in banks:
        code = bank.code
        results.append({
            "bank_code": code,
            "bank_name": bank.name,
            "status": "OK" if bank.is_active else "INACTIVE",
            "avg_response_ms": avg_map.get(code, 0),
            "errors": err_map.get(code, 0),
            "successful_payments": succ_map.get(code, 0)
        })

    # Подсчитываем общую статистику
    total_banks = len(banks)
    active_banks = len([b for b in banks if b.is_active])
    
    # Подсчитываем общую статистику по всем банкам
    total_avg_response = sum(avg_map.values()) / len(avg_map) if avg_map else 0
    total_errors = sum(err_map.values())
    total_successful = sum(succ_map.values())
    
    # Подсчитываем успешность
    total_transactions = total_errors + total_successful
    success_rate = (total_successful / total_transactions * 100) if total_transactions > 0 else 0
    
    # Подсчитываем uptime (упрощенно - процент активных банков)
    uptime = (active_banks / total_banks * 100) if total_banks > 0 else 0
    
    # Статистика за сегодня
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_successful = db.query(TransactionRecord).filter(
        and_(
            TransactionRecord.processed_at >= today_start,
            TransactionRecord.status == "success"
        )
    ).count()
    
    today_errors = db.query(PaymentLog).filter(
        and_(
            PaymentLog.created_at >= today_start,
            PaymentLog.error_message.isnot(None)
        )
    ).count()
    
    today_volume = db.query(func.sum(PaymentRequest.amount)).filter(
        and_(
            PaymentRequest.created_at >= today_start,
            PaymentRequest.is_paid == True
        )
    ).scalar() or 0

    return {
        "total_banks": total_banks,
        "active_banks": active_banks,
        "avg_response_time": int(total_avg_response),
        "success_rate": round(success_rate, 1),
        "uptime": round(uptime, 1),
        "today_successful": today_successful,
        "today_errors": today_errors,
        "today_volume": float(today_volume),
        "bank_stats": results,
        "period": since.isoformat()
    }

async def _get_turnover_7days(db: Session, since: datetime) -> Dict[str, Any]:
    """Динамика оборота за 7 дней"""
    # Генерируем данные за последние 7 дней
    turnover_data = []
    for i in range(7):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Сумма успешных платежей за день
        daily_amount = db.query(func.sum(PaymentRequest.amount)).filter(
            and_(
                PaymentRequest.created_at >= date_start,
                PaymentRequest.created_at <= date_end,
                PaymentRequest.is_paid == True
            )
        ).scalar() or 0
        
        turnover_data.append({
            "date": date.strftime("%d.%m"),
            "amount": float(daily_amount)
        })
    
    # Разворачиваем в правильном порядке (от старых к новым)
    turnover_data.reverse()
    
    return {
        "turnover": turnover_data,
        "period": since.isoformat()
    }

async def _get_status_distribution(db: Session, since: datetime) -> Dict[str, Any]:
    """Соотношение статусов транзакций за 24 часа"""
    # Статусы транзакций за последние 24 часа
    status_counts = db.query(
        PaymentRequest.status,
        func.count(PaymentRequest.id)
    ).filter(
        PaymentRequest.created_at >= since
    ).group_by(PaymentRequest.status).all()
    
    # Преобразуем в нужный формат
    status_data = []
    status_names = {
        "pending": "Ожидание",
        "preparing": "Подготовка", 
        "prepared": "Подготовлен",
        "committing": "Выполнение",
        "completed": "Завершен",
        "aborting": "Отмена",
        "aborted": "Отменен"
    }
    
    for status, count in status_counts:
        status_data.append({
            "status": status_names.get(status, status),
            "count": count
        })
    
    return {
        "status_distribution": status_data,
        "period": since.isoformat()
    }

async def _get_transaction_lifetime_series(db: Session, since: datetime) -> Dict[str, Any]:
    """Время жизни транзакции (от создания до завершения) - серия за 24 часа"""
    # Генерируем данные по часам за последние 24 часа
    lifetime_data = []
    
    for i in range(24):
        # Начало часа (в UTC)
        hour_start = datetime.now(timezone.utc) - timedelta(hours=23-i)
        hour_end = hour_start + timedelta(hours=1)
        
        # Выбираем транзакции, завершенные в этом часе
        transactions = db.query(
            PaymentRequest.created_at,
            PaymentRequest.paid_at
        ).filter(
            and_(
                PaymentRequest.paid_at >= hour_start,
                PaymentRequest.paid_at < hour_end,
                PaymentRequest.is_paid == True,
                PaymentRequest.paid_at.isnot(None),
                PaymentRequest.created_at.isnot(None)
            )
        ).all()
        
        # Рассчитываем время жизни для каждой транзакции
        lifetimes = []
        for transaction in transactions:
            if transaction.created_at and transaction.paid_at:
                lifetime_seconds = (transaction.paid_at - transaction.created_at).total_seconds()
                if lifetime_seconds >= 0:  # Исключаем отрицательные значения
                    lifetimes.append(lifetime_seconds)
        
        # Рассчитываем среднее время жизни
        avg_lifetime_seconds = 0.0
        transaction_count = len(lifetimes)
        
        if transaction_count > 0:
            avg_lifetime_seconds = sum(lifetimes) / transaction_count
        
        lifetime_data.append({
            "timestamp": hour_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "avg_lifetime_seconds": round(avg_lifetime_seconds, 2),
            "transaction_count": transaction_count
        })
    
    return {
        "transaction_lifetime_series": lifetime_data,
        "period": since.isoformat()
    }

async def _get_average_check(db: Session, since: datetime) -> Dict[str, Any]:
    """Динамика среднего чека за 30 дней"""
    # Генерируем данные за последние 30 дней
    check_data = []
    for i in range(30):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Средний чек за день
        avg_amount = db.query(func.avg(PaymentRequest.amount)).filter(
            and_(
                PaymentRequest.created_at >= date_start,
                PaymentRequest.created_at <= date_end,
                PaymentRequest.is_paid == True
            )
        ).scalar() or 0
        
        check_data.append({
            "date": date.strftime("%d.%m"),
            "avg_amount": round(float(avg_amount), 2)
        })
    
    # Разворачиваем в правильном порядке
    check_data.reverse()
    
    return {
        "average_check": check_data,
        "period": since.isoformat()
    }


