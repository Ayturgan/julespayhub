from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc
from app.core.dependencies import get_db
from app.services.realtime_monitoring_service import realtime_monitoring_service, MonitoringEvent, MonitoringEventType
from app.models.payment import Bank
from app.models.payment import TransactionRecord, BillingRecord
from app.services.hybrid_logging_service import hybrid_logging_service
from app.models.payment import PaymentRequest
from app.models.merchant import Merchant, MerchantPayment
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.services.bank_adapter_service import bank_adapter_service
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

router = APIRouter()

# === REAL-TIME MONITORING ===

@router.get("/current-metrics")
async def get_current_monitoring_metrics():
    """
    Получение текущих метрик мониторинга
    """
    try:
        metrics = realtime_monitoring_service.get_current_metrics()
        return {
            "status": "success",
            "data": metrics,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get monitoring metrics: {str(e)}"
        )

@router.get("/recent-events")
async def get_recent_monitoring_events(limit: int = 100):
    """
    Получение недавних событий мониторинга
    """
    try:
        events = realtime_monitoring_service.get_recent_events(limit)
        return {
            "status": "success",
            "data": events,
            "total_events": len(events),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get monitoring events: {str(e)}"
        )



@router.get("/bank-status/{bank_code}")
async def get_bank_monitoring_status(
    bank_code: str,
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Получение статуса мониторинга конкретного банка
    """
    try:
        # Проверяем существование банка
        bank = db.query(Bank).filter(Bank.code == bank_code).first()
        if not bank:
            raise HTTPException(status_code=404, detail=f"Bank {bank_code} not found")
        
        # Получаем текущие метрики
        current_metrics = realtime_monitoring_service.get_current_metrics()
        bank_metrics = current_metrics.get("bank_metrics", {}).get(bank_code)
        
        # Получаем историю статуса
        status_history = realtime_monitoring_service.get_bank_status_history(bank_code, hours)
        
        return {
            "status": "success",
            "data": {
                "bank_code": bank_code,
                "bank_name": bank.name,
                "current_metrics": bank_metrics,
                "status_history": status_history,
                "is_active": bank.is_active,
                "last_used": bank.last_used_at.isoformat() if bank.last_used_at else None
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get bank monitoring status: {str(e)}"
        )

@router.get("/system-health")
async def get_system_health_monitoring():
    """
    Получение общего состояния системы
    """
    try:
        metrics = realtime_monitoring_service.get_current_metrics()
        system_metrics = metrics.get("system_metrics")
        
        if not system_metrics:
            return {
                "status": "warning",
                "message": "System metrics not available yet",
                "data": None,
                "timestamp": datetime.now().isoformat()
            }
        
        # Определяем рекомендации на основе метрик
        recommendations = []
        
        if system_metrics["error_rate_1h"] > 10:
            recommendations.append({
                "severity": "high",
                "message": "High error rate detected",
                "action": "Check error logs and bank integrations"
            })
        
        if system_metrics["avg_response_time_ms"] > 5000:
            recommendations.append({
                "severity": "medium",
                "message": "Slow response times detected",
                "action": "Check system performance and database queries"
            })
        
        if system_metrics["active_banks"] < system_metrics["total_banks"] * 0.8:
            recommendations.append({
                "severity": "medium",
                "message": "Many banks are inactive",
                "action": "Check bank configurations and connectivity"
            })
        
        return {
            "status": "success",
            "data": {
                "system_metrics": system_metrics,
                "health_score": _calculate_health_score(system_metrics),
                "recommendations": recommendations,
                "uptime_status": "operational"  # Можно расширить
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get system health: {str(e)}"
        )

@router.get("/performance-trends")
async def get_performance_trends(
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Получение трендов производительности
    """
    try:
        since = datetime.now() - timedelta(hours=hours)
        
        # Получаем агрегированные данные по часам
        hourly_stats = db.execute("""
            SELECT 
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                COUNT(*) as total_requests,
                SUM(CASE WHEN error_message IS NULL THEN 1 ELSE 0 END) as successful_requests,
                SUM(CASE WHEN error_message IS NOT NULL THEN 1 ELSE 0 END) as failed_requests,
                AVG(CASE WHEN request_duration_ms IS NOT NULL THEN request_duration_ms ELSE 0 END) as avg_response_time,
                COUNT(DISTINCT bank_code) as active_banks
            FROM payment_logs 
            WHERE timestamp >= ?
            GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp)
            ORDER BY hour
        """, (since,)).fetchall()
        
        trends = []
        for stat in hourly_stats:
            hour, total, successful, failed, avg_time, active_banks = stat
            error_rate = (failed / total * 100) if total > 0 else 0
            
            trends.append({
                "timestamp": hour,
                "total_requests": total,
                "successful_requests": successful,
                "failed_requests": failed,
                "error_rate": round(error_rate, 2),
                "avg_response_time_ms": round(avg_time, 2),
                "active_banks": active_banks
            })
        
        # Вычисляем тренды
        trend_analysis = _analyze_trends(trends)
        
        return {
            "status": "success",
            "data": {
                "period_hours": hours,
                "hourly_trends": trends,
                "trend_analysis": trend_analysis
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get performance trends: {str(e)}"
        )



@router.get("/dashboard-data")
async def get_monitoring_dashboard_data():
    """
    Получение всех данных для дашборда мониторинга
    """
    try:
        # Собираем все необходимые данные
        current_metrics = realtime_monitoring_service.get_current_metrics()
        recent_events = realtime_monitoring_service.get_recent_events(20)
        recent_alerts = realtime_monitoring_service.get_recent_alerts(10)
        
        # Группируем события по типам
        event_types = {}
        for event in recent_events:
            event_type = event.get("event_type", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        # Считаем критические алерты
        critical_alerts = len([a for a in recent_alerts if a.get("severity") == "critical"])
        unacknowledged_alerts = len([a for a in recent_alerts if not a.get("acknowledged", False)])
        
        return {
            "status": "success",
            "data": {
                "current_metrics": current_metrics,
                "recent_events": recent_events,
                "recent_alerts": recent_alerts,
                "summary": {
                    "total_events": len(recent_events),
                    "event_types": event_types,
                    "critical_alerts": critical_alerts,
                    "unacknowledged_alerts": unacknowledged_alerts,
                    "monitoring_active": True
                }
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get dashboard data: {str(e)}"
        )

@router.get("/thresholds")
async def get_monitoring_thresholds():
    """
    Получение текущих пороговых значений мониторинга
    """
    try:
        thresholds = realtime_monitoring_service.ALERT_THRESHOLDS
        return {
            "status": "success",
            "data": {
                "thresholds": thresholds,
                "descriptions": {
                    "error_rate_warning": "Процент ошибок за час для предупреждения",
                    "error_rate_critical": "Процент ошибок за час для критического алерта",
                    "response_time_warning": "Время ответа в мс для предупреждения",
                    "response_time_critical": "Время ответа в мс для критического алерта",
                    "webhook_failure_warning": "Количество неудачных webhook за час для предупреждения",
                    "webhook_failure_critical": "Количество неудачных webhook за час для критического алерта",
                    "rate_limit_warning": "Количество блокировок rate limit за час для предупреждения",
                    "rate_limit_critical": "Количество блокировок rate limit за час для критического алерта"
                }
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get monitoring thresholds: {str(e)}"
        )

@router.put("/thresholds")
async def update_monitoring_thresholds(thresholds: Dict[str, float]):
    """
    Обновление пороговых значений мониторинга
    """
    try:
        # Валидируем входные данные
        valid_keys = set(realtime_monitoring_service.ALERT_THRESHOLDS.keys())
        invalid_keys = set(thresholds.keys()) - valid_keys
        
        if invalid_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid threshold keys: {list(invalid_keys)}"
            )
        
        # Обновляем пороговые значения
        for key, value in thresholds.items():
            if value < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Threshold {key} cannot be negative: {value}"
                )
            realtime_monitoring_service.ALERT_THRESHOLDS[key] = value
        
        return {
            "status": "success",
            "message": f"Updated {len(thresholds)} thresholds",
            "updated_thresholds": thresholds,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update monitoring thresholds: {str(e)}"
        )

def _calculate_health_score(system_metrics: Dict[str, Any]) -> int:
    """Вычисление общего балла здоровья системы (0-100)"""
    
    score = 100
    
    # Штрафы за ошибки
    error_rate = system_metrics.get("error_rate_1h", 0)
    if error_rate > 20:
        score -= 50
    elif error_rate > 10:
        score -= 30
    elif error_rate > 5:
        score -= 15
    elif error_rate > 1:
        score -= 5
    
    # Штрафы за медленные ответы
    avg_response_time = system_metrics.get("avg_response_time_ms", 0)
    if avg_response_time > 10000:
        score -= 30
    elif avg_response_time > 5000:
        score -= 20
    elif avg_response_time > 2000:
        score -= 10
    elif avg_response_time > 1000:
        score -= 5
    
    # Штрафы за неактивные банки
    total_banks = system_metrics.get("total_banks", 1)
    active_banks = system_metrics.get("active_banks", 0)
    if total_banks > 0:
        activity_ratio = active_banks / total_banks
        if activity_ratio < 0.5:
            score -= 20
        elif activity_ratio < 0.7:
            score -= 10
        elif activity_ratio < 0.9:
            score -= 5
    
    # Штрафы за банки с ошибками
    error_banks = system_metrics.get("error_banks", 0)
    if error_banks > total_banks * 0.5:
        score -= 15
    elif error_banks > total_banks * 0.3:
        score -= 10
    elif error_banks > 0:
        score -= 5
    
    return max(0, min(100, score))

def _analyze_trends(trends: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Анализ трендов производительности"""
    
    if len(trends) < 2:
        return {"status": "insufficient_data"}
    
    # Берем последние и предыдущие значения для сравнения
    recent = trends[-3:] if len(trends) >= 3 else trends
    previous = trends[:-3] if len(trends) >= 6 else []
    
    if not previous:
        return {"status": "insufficient_history"}
    
    # Средние значения
    recent_avg_error_rate = sum(t["error_rate"] for t in recent) / len(recent)
    previous_avg_error_rate = sum(t["error_rate"] for t in previous) / len(previous)
    
    recent_avg_response_time = sum(t["avg_response_time_ms"] for t in recent) / len(recent)
    previous_avg_response_time = sum(t["avg_response_time_ms"] for t in previous) / len(previous)
    
    recent_avg_requests = sum(t["total_requests"] for t in recent) / len(recent)
    previous_avg_requests = sum(t["total_requests"] for t in previous) / len(previous)
    
    # Определяем тренды
    error_rate_trend = "stable"
    if recent_avg_error_rate > previous_avg_error_rate * 1.2:
        error_rate_trend = "increasing"
    elif recent_avg_error_rate < previous_avg_error_rate * 0.8:
        error_rate_trend = "decreasing"
    
    response_time_trend = "stable"
    if recent_avg_response_time > previous_avg_response_time * 1.2:
        response_time_trend = "increasing"
    elif recent_avg_response_time < previous_avg_response_time * 0.8:
        response_time_trend = "decreasing"
    
    traffic_trend = "stable"
    if recent_avg_requests > previous_avg_requests * 1.2:
        traffic_trend = "increasing"
    elif recent_avg_requests < previous_avg_requests * 0.8:
        traffic_trend = "decreasing"
    
    return {
        "status": "analyzed",
        "error_rate_trend": error_rate_trend,
        "response_time_trend": response_time_trend,
        "traffic_trend": traffic_trend,
        "recent_avg_error_rate": round(recent_avg_error_rate, 2),
        "previous_avg_error_rate": round(previous_avg_error_rate, 2),
        "recent_avg_response_time": round(recent_avg_response_time, 2),
        "previous_avg_response_time": round(previous_avg_response_time, 2),
        "recent_avg_requests": round(recent_avg_requests, 2),
        "previous_avg_requests": round(previous_avg_requests, 2)
    }

# === Live Bank Healthcheck Endpoints ===

def _ping_healthcheck_url(url: str, headers: Optional[Dict[str, str]] = None, timeout_seconds: int = 5, bank_code: Optional[str] = None) -> Dict[str, Any]:
    """Синхронный пинг healthcheck URL. Возвращает словарь с результатом."""
    start = time.perf_counter()
    status_code: Optional[int] = None
    body_preview: Optional[str] = None
    error_message: Optional[str] = None
    try:
        req = Request(url, headers={(headers or {}) | {"User-Agent": "QRPayHub-HealthCheck"}})
        with urlopen(req, timeout=timeout_seconds) as resp:
            status_code = resp.getcode()
            # читаем небольшой фрагмент для отладки
            try:
                body_preview = resp.read(256).decode("utf-8", errors="ignore")
            except Exception:
                body_preview = None
    except HTTPError as e:
        status_code = e.code
        try:
            body_preview = e.read(256).decode("utf-8", errors="ignore")
        except Exception:
            body_preview = None
        error_message = f"HTTPError: {e.reason}"
        # Записываем событие 5xx
        try:
            realtime_monitoring_service.record_event(
                MonitoringEvent(
                    event_type=MonitoringEventType.API_5XX,
                    timestamp=datetime.now(),
                    bank_code=None,
                    endpoint=url,
                    success=False,
                    error_message=error_message,
                )
            )
        except Exception:
            pass
    except URLError as e:
        error_message = f"URLError: {getattr(e, 'reason', str(e))}"
        # Записываем событие таймаута/сети
        try:
            realtime_monitoring_service.record_event(
                MonitoringEvent(
                    event_type=MonitoringEventType.API_TIMEOUT,
                    timestamp=datetime.now(),
                    bank_code=None,
                    endpoint=url,
                    success=False,
                    error_message=error_message,
                )
            )
        except Exception:
            pass
    except Exception as e:
        error_message = f"Error: {str(e)}"
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)

    healthy = status_code is not None and 200 <= status_code < 400 and error_message is None
    # Записываем событие успеха
    try:
        realtime_monitoring_service.record_event(
            MonitoringEvent(
                event_type=MonitoringEventType.API_OK if healthy else (MonitoringEventType.API_5XX if status_code and status_code >= 500 else MonitoringEventType.API_TIMEOUT),
                timestamp=datetime.now(),
                bank_code=bank_code,
                endpoint=url,
                success=healthy,
                error_message=error_message,
            )
        )
    except Exception:
        pass
    return {
        "healthy": healthy,
        "http_status": status_code,
        "response_time_ms": elapsed_ms,
        "body_preview": body_preview,
        "error": error_message,
    }


@router.get("/bank-health/{bank_code}")
async def get_bank_live_health(
    bank_code: str,
    timeout: int = 5,
    db: Session = Depends(get_db)
):
    """
    Живая проверка доступности банковского сервиса для конкретного банка.
    Использует health_check_url из конфигурации адаптера банка.
    """
    # Проверяем банк в БД (для валидации существования и статусов)
    bank = db.query(Bank).filter(Bank.code == bank_code).first()
    if not bank:
        raise HTTPException(status_code=404, detail=f"Bank {bank_code} not found")

    # Достаем конфигурацию адаптера
    config = bank_adapter_service.get_configuration(bank_code)
    if not config:
        raise HTTPException(status_code=404, detail=f"Bank {bank_code} has no adapter configuration")

    if not config.health_check_url:
        return {
            "status": "unknown",
            "message": "health_check_url is not configured for this bank",
            "data": {
                "bank_code": bank_code,
                "is_active": getattr(bank, "is_active", None),
                "checked_at": datetime.now().isoformat()
            }
        }

    result = _ping_healthcheck_url(
        url=config.health_check_url,
        headers=config.custom_headers,
        timeout_seconds=max(1, min(timeout, 60)),
        bank_code=bank_code
    )

    return {
        "status": "success" if result["healthy"] else "error",
        "data": {
            "bank_code": bank_code,
            "bank_name": getattr(config, "name", bank.name if hasattr(bank, "name") else bank_code),
            "is_active": getattr(bank, "is_active", None),
            "health_check_url": config.health_check_url,
            "healthy": result["healthy"],
            "http_status": result["http_status"],
            "response_time_ms": result["response_time_ms"],
            "error": result["error"],
        },
        "timestamp": datetime.now().isoformat()
    }


@router.get("/banks-health")
async def get_all_banks_live_health(
    timeout: int = 5,
    db: Session = Depends(get_db)
):
    """
    Живая проверка доступности для всех активных банков (агрегированно).
    Последовательно пингует health_check_url каждого активного банка, у кого он задан.
    """
    banks: List[Bank] = db.query(Bank).filter(getattr(Bank, "is_active", True) == True).all()  # noqa: E712
    results: List[Dict[str, Any]] = []
    for bank in banks:
        bank_code = getattr(bank, "code", None) or getattr(bank, "bank_code", None)
        if not bank_code:
            continue
        config = bank_adapter_service.get_configuration(bank_code)
        if not config or not config.health_check_url:
            results.append({
                "bank_code": bank_code,
                "bank_name": getattr(config, "name", getattr(bank, "name", bank_code) if config else getattr(bank, "name", bank_code)),
                "is_active": getattr(bank, "is_active", None),
                "health_check_url": config.health_check_url if config else None,
                "healthy": None,
                "http_status": None,
                "response_time_ms": None,
                "error": "health_check_url not configured" if not (config and config.health_check_url) else None,
            })
            continue

        result = _ping_healthcheck_url(
            url=config.health_check_url,
            headers=config.custom_headers,
            timeout_seconds=max(1, min(timeout, 60)),
            bank_code=bank_code
        )
        results.append({
            "bank_code": bank_code,
            "bank_name": getattr(config, "name", getattr(bank, "name", bank_code)),
            "is_active": getattr(bank, "is_active", None),
            "health_check_url": config.health_check_url,
            "healthy": result["healthy"],
            "http_status": result["http_status"],
            "response_time_ms": result["response_time_ms"],
            "error": result["error"],
        })

    summary = {
        "total": len(results),
        "configured": len([r for r in results if r["health_check_url"]]),
        "healthy": len([r for r in results if r["healthy"] is True]),
        "unhealthy": len([r for r in results if r["healthy"] is False]),
        "not_configured": len([r for r in results if r["health_check_url"] is None]),
    }

    return {
        "status": "success",
        "data": {
            "summary": summary,
            "results": results,
        },
        "timestamp": datetime.now().isoformat()
    }

# === New consolidated monitoring endpoints ===

@router.get("/summary")
async def get_monitoring_summary(period_hours: int = 1, db: Session = Depends(get_db)):
    """
    Краткое резюме за указанный период: TPM, QPS, avg response, error rate.
    """
    try:
        since_time = datetime.now() - timedelta(hours=period_hours)

        # Получаем статистику из realtime monitoring service
        metrics = realtime_monitoring_service.get_current_metrics()
        
        # Используем данные из realtime monitoring для API статистики
        total_requests = metrics.get("total_requests", 0)
        error_requests = metrics.get("error_requests", 0)
        avg_response_ms = metrics.get("avg_response_ms", 0)

        # Successful payments in period (TPM = transactions per minute)
        tpm = db.query(func.count(TransactionRecord.id)).filter(and_(
            TransactionRecord.processed_at >= since_time, 
            TransactionRecord.status == "success"
        )).scalar() or 0

        # Convert to per-minute rates
        period_minutes = period_hours * 60
        qps = total_requests / period_minutes if period_minutes > 0 else 0
        tpm_rate = tpm / period_minutes if period_minutes > 0 else 0
        error_rate = (error_requests / total_requests * 100.0) if total_requests > 0 else 0.0

        return {
            "status": "success",
            "data": {
                "tpm": round(tpm_rate, 2),  # transactions per minute
                "api_qps": round(qps, 2),
                "avg_response_ms": avg_response_ms,
                "error_rate": round(error_rate, 2),
                "period_hours": period_hours,
                "total_requests": total_requests,
                "total_transactions": tpm
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get monitoring summary: {str(e)}")

@router.get("/bank-stats")
async def get_banks_stats(hours: int = 24, db: Session = Depends(get_db)):
    """
    Агрегированные метрики по банкам: статус, среднее время ответа, ошибки, успешные платежи.
    """
    try:
        since = datetime.now() - timedelta(hours=hours)

        # Получаем статистику из realtime monitoring service
        metrics = realtime_monitoring_service.get_current_metrics()
        bank_metrics = metrics.get("bank_metrics", {})
        
        # Используем данные из realtime monitoring для статистики по банкам
        avg_map = {}
        err_map = {}
        for bank_code, bank_data in bank_metrics.items():
            avg_map[bank_code] = bank_data.get("avg_response_ms", 0)
            err_map[bank_code] = bank_data.get("error_count", 0)

        # Successful payments per bank
        succ_rows = db.query(TransactionRecord.bank_code, func.count(TransactionRecord.id)).filter(and_(TransactionRecord.processed_at >= since, TransactionRecord.status == "success")).group_by(TransactionRecord.bank_code).all()
        succ_map = {row[0]: row[1] for row in succ_rows}

        # Current status from realtime monitoring
        metrics = realtime_monitoring_service.get_current_metrics()
        bank_metrics = metrics.get("bank_metrics", {})

        # Compose list for all known banks (from DB)
        banks: List[Bank] = db.query(Bank).all()
        results: List[Dict[str, Any]] = []
        for bank in banks:
            code = bank.code
            bm = bank_metrics.get(code)
            status = bm.get("status") if bm else "unknown"
            # Normalize status icon
            if status in ("healthy",):
                status_label = "OK"
            elif status in ("warning", "error"):
                status_label = "DEGRADED"
            elif status in ("critical",):
                status_label = "UNAVAILABLE"
            else:
                status_label = "UNKNOWN"
            results.append({
                "bank_code": code,
                "bank_name": bank.name,
                "status": status_label,
                "avg_response_ms": avg_map.get(code),
                "errors": err_map.get(code, 0),
                "successful_payments": succ_map.get(code, 0)
            })

        return {
            "status": "success",
            "data": results,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bank stats: {str(e)}")

@router.get("/business-funnel")
async def get_business_funnel(hours: int = 24, db: Session = Depends(get_db)):
    """
    Воронка: сгенерировано QR, сканировано (payment-info), оплачено (success)
    """
    try:
        since = datetime.now() - timedelta(hours=hours)
        # Надежнее считать по PaymentRequest, а не по логам
        qr_generated = db.query(func.count(PaymentRequest.id)).filter(PaymentRequest.created_at >= since).scalar() or 0
        
        # Сканирования = используем данные из realtime monitoring
        # TODO: Добавить метод в realtime_monitoring_service для получения количества сканирований
        scanned = 0  # Временно устанавливаем 0, нужно будет добавить метод в realtime monitoring
        
        paid = db.query(func.count(TransactionRecord.id)).filter(and_(TransactionRecord.processed_at >= since, TransactionRecord.status == "success")).scalar() or 0

        return {
            "status": "success",
            "data": {"qr_generated": qr_generated, "scanned": scanned, "paid": paid, "period_hours": hours},
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get business funnel: {str(e)}")

@router.get("/top-merchants")
async def get_top_merchants(limit: int = 10, days: int = 7, db: Session = Depends(get_db)):
    """
    Топ продавцов по количеству успешных платежей за период.
    """
    try:
        since = datetime.now() - timedelta(days=days)
        rows = db.query(MerchantPayment.merchant_id, func.count(MerchantPayment.id).label("cnt")).filter(and_(MerchantPayment.paid_at.isnot(None), MerchantPayment.paid_at >= since)).group_by(MerchantPayment.merchant_id).order_by(desc("cnt")).limit(limit).all()

        merchant_ids = [r[0] for r in rows if r[0] is not None]
        names = {m.id: m.name for m in db.query(Merchant).filter(Merchant.id.in_(merchant_ids)).all()} if merchant_ids else {}
        data = [{"merchant_id": mid, "merchant_name": names.get(mid, str(mid)), "count": cnt} for mid, cnt in rows]

        return {"status": "success", "data": data, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get top merchants: {str(e)}")
