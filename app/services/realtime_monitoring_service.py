import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, deque
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import logging
import threading

from app.models.payment import PaymentRequest, PaymentLog, Bank, TransactionRecord, RateLimitRecord
from app.core.config import settings
from app.services.error_handling_service import ErrorCode, ErrorSeverity

logger = logging.getLogger(__name__)

class MonitoringEventType(str, Enum):
    """Типы событий мониторинга"""
    PAYMENT_REQUEST = "payment_request"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    WEBHOOK_RECEIVED = "webhook_received"
    WEBHOOK_FAILED = "webhook_failed"
    RATE_LIMIT_HIT = "rate_limit_hit"
    AUTHENTICATION_FAILED = "auth_failed"
    VALIDATION_ERROR = "validation_error"
    BANK_ERROR = "bank_error"
    SYSTEM_ERROR = "system_error"
    API_TIMEOUT = "api_timeout"
    API_5XX = "api_5xx"
    API_OK = "api_ok"
    # События возвратов
    REFUND_REQUEST = "refund_request"
    REFUND_SUCCESS = "refund_success"
    REFUND_FAILED = "refund_failed"
    REFUND_EXECUTION = "refund_execution"
    REFUND_CANCELLATION = "refund_cancellation"
    ADMIN_REFUND_EXECUTION = "admin_refund_execution"
    ADMIN_REFUND_CANCELLATION = "admin_refund_cancellation"

class AlertSeverity(str, Enum):
    """Уровни критичности алертов"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class MonitoringStatus(str, Enum):
    """Статусы мониторинга"""
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

@dataclass
class MonitoringEvent:
    """Событие мониторинга"""
    event_type: MonitoringEventType
    timestamp: datetime
    bank_code: Optional[str] = None
    endpoint: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    response_time_ms: Optional[float] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    success: bool = True
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

@dataclass
class BankHealthMetrics:
    """Метрики здоровья банка"""
    bank_code: str
    status: MonitoringStatus
    last_successful_request: Optional[datetime] = None
    last_error: Optional[datetime] = None
    total_requests_1h: int = 0
    successful_requests_1h: int = 0
    failed_requests_1h: int = 0
    avg_response_time_ms: float = 0.0
    error_rate_1h: float = 0.0
    last_errors: List[str] = None
    webhook_failures_1h: int = 0
    rate_limit_hits_1h: int = 0
    
    def __post_init__(self):
        if self.last_errors is None:
            self.last_errors = []

@dataclass
class SystemHealthMetrics:
    """Общие метрики системы"""
    overall_status: MonitoringStatus
    total_banks: int
    active_banks: int
    healthy_banks: int
    warning_banks: int
    error_banks: int
    total_requests_1h: int = 0
    successful_requests_1h: int = 0
    failed_requests_1h: int = 0
    avg_response_time_ms: float = 0.0
    error_rate_1h: float = 0.0
    top_errors: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.top_errors is None:
            self.top_errors = []

class RealtimeMonitoringService:
    """Сервис мониторинга интеграций в реальном времени"""
    
    def __init__(self):
        self._events_buffer: deque = deque(maxlen=10000)  # Буфер последних событий
        self._bank_metrics: Dict[str, BankHealthMetrics] = {}
        self._system_metrics: Optional[SystemHealthMetrics] = None
        self._alerts: deque = deque(maxlen=1000)  # Буфер алертов
        self._subscribers: Set[callable] = set()  # WebSocket подписчики
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        self._lock = threading.Lock()
        self._last_alert_time: Dict[str, datetime] = {}
        self._last_alert_message: Dict[str, str] = {}
        # Отслеживание недоступности API банков
        self._api_failure_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._api_unavailable_active: Set[str] = set()
        self.API_UNAVAILABLE_WINDOW_SECONDS: int = 60
        self.API_UNAVAILABLE_THRESHOLD: int = 5
        
        # Пороговые значения для алертов
        self.ALERT_THRESHOLDS = {
            "error_rate_warning": 5.0,      # 5% ошибок за час
            "error_rate_critical": 15.0,    # 15% ошибок за час
            "response_time_warning": 5000,  # 5 секунд
            "response_time_critical": 10000, # 10 секунд
            "webhook_failure_warning": 3,   # 3 неудачи за час
            "webhook_failure_critical": 10, # 10 неудач за час
            "rate_limit_warning": 5,        # 5 блокировок за час
            "rate_limit_critical": 20       # 20 блокировок за час
        }

        # Настройки подавления/троттлинга алертов
        try:
            self.ALERT_COOLDOWN_SECONDS: int = int(getattr(settings, "MONITORING_ALERTS_COOLDOWN_SECONDS", 600))
        except Exception:
            self.ALERT_COOLDOWN_SECONDS = 600  # 10 минут по умолчанию
        try:
            self.SYSTEM_ALERTS_ENABLED: bool = bool(getattr(settings, "MONITORING_ENABLE_SYSTEM_ALERTS", True))
        except Exception:
            self.SYSTEM_ALERTS_ENABLED = True
    
    def start_monitoring(self):
        """Запуск мониторинга в фоновом режиме"""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            logger.warning("📊 Мониторинг уже запущен")
            return
        
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self._monitoring_thread.start()
        logger.warning("📊 Система мониторинга запущена")
    
    def stop_monitoring(self):
        """Остановка мониторинга"""
        self._stop_monitoring.set()
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=5)
        logger.warning("📊 Система мониторинга остановлена")
    
    def _monitoring_loop(self):
        """Основной цикл мониторинга"""
        while not self._stop_monitoring.is_set():
            try:
                # Обновляем метрики каждые 30 секунд
                self._update_metrics()
                self._check_alerts()
                
                # Уведомляем подписчиков
                self._notify_subscribers()
                
                # Ждем 30 секунд или до остановки
                self._stop_monitoring.wait(30)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                self._stop_monitoring.wait(10)  # Ждем меньше при ошибке
    
    def record_event(self, event: MonitoringEvent):
        """Запись события мониторинга"""
        with self._lock:
            self._events_buffer.append(event)
        
        # Немедленно проверяем критические события
        if not event.success or event.event_type in [
            MonitoringEventType.SYSTEM_ERROR,
            MonitoringEventType.BANK_ERROR,
            MonitoringEventType.AUTHENTICATION_FAILED
        ]:
            self._check_immediate_alert(event)
        # Обработка состояний доступности API
        if event.event_type in (MonitoringEventType.API_TIMEOUT, MonitoringEventType.API_5XX):
            self._record_api_failure(event)
        elif event.event_type == MonitoringEventType.API_OK:
            self._record_api_success(event)
    
    def record_payment_request(
        self,
        bank_code: str,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool = True,
        error_message: Optional[str] = None,
        amount: Optional[float] = None,
        currency: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """Запись события платежного запроса"""
        event = MonitoringEvent(
            event_type=MonitoringEventType.PAYMENT_REQUEST,
            timestamp=datetime.now(),
            bank_code=bank_code,
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            response_time_ms=response_time_ms,
            amount=amount,
            currency=currency,
            success=success,
            error_message=error_message
        )
        self.record_event(event)
    
    def record_webhook_event(
        self,
        bank_code: str,
        success: bool,
        error_message: Optional[str] = None,
        response_time_ms: Optional[float] = None,
        transaction_id: Optional[str] = None
    ):
        """Запись события webhook"""
        event_type = MonitoringEventType.WEBHOOK_RECEIVED if success else MonitoringEventType.WEBHOOK_FAILED
        
        event = MonitoringEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            bank_code=bank_code,
            endpoint="/payment-status",
            response_time_ms=response_time_ms,
            success=success,
            error_message=error_message,
            metadata={"transaction_id": transaction_id} if transaction_id else None
        )
        self.record_event(event)
    
    def record_rate_limit_hit(
        self,
        bank_code: str,
        ip_address: str,
        endpoint: str,
        user_agent: Optional[str] = None
    ):
        """Запись события превышения лимитов"""
        event = MonitoringEvent(
            event_type=MonitoringEventType.RATE_LIMIT_HIT,
            timestamp=datetime.now(),
            bank_code=bank_code,
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            error_message="Rate limit exceeded"
        )
        self.record_event(event)
    
    def record_authentication_failure(
        self,
        bank_code: Optional[str],
        ip_address: str,
        endpoint: str,
        error_message: str,
        user_agent: Optional[str] = None
    ):
        """Запись события неудачной аутентификации"""
        event = MonitoringEvent(
            event_type=MonitoringEventType.AUTHENTICATION_FAILED,
            timestamp=datetime.now(),
            bank_code=bank_code,
            endpoint=endpoint,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            error_message=error_message
        )
        self.record_event(event)
    
    def _update_metrics(self):
        """Обновление метрик мониторинга"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                # Обновляем метрики банков
                self._update_bank_metrics(db)
                
                # Обновляем общие метрики системы
                self._update_system_metrics(db)
                
        except Exception as e:
            logger.error(f"Failed to update monitoring metrics: {e}")
    
    def _update_bank_metrics(self, db: Session):
        """Обновление метрик банков"""
        # Получаем все банки
        banks = db.query(Bank).all()
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        for bank in banks:
            # Получаем логи за последний час
            logs = db.query(PaymentLog).filter(
                and_(
                    PaymentLog.bank_code == bank.code,
                    PaymentLog.created_at >= one_hour_ago
                )
            ).all()
            
            # Считаем метрики
            total_requests = len(logs)
            successful_requests = len([log for log in logs if not log.error_message])
            failed_requests = total_requests - successful_requests
            
            # Средний response time
            response_times = [log.request_duration_ms for log in logs if log.request_duration_ms]
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0
            
            # Error rate
            error_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0.0
            
            # Последние ошибки
            error_logs = [log for log in logs if log.error_message]
            last_errors = [log.error_message for log in error_logs[-5:]]  # Последние 5 ошибок
            
            # Webhook failures
            webhook_failures = len([log for log in logs if log.endpoint == "/payment-status" and log.error_message])
            
            # Rate limit hits
            rate_limit_hits = db.query(RateLimitRecord).filter(
                and_(
                    RateLimitRecord.bank_code == bank.code,
                    RateLimitRecord.last_request >= one_hour_ago,
                    RateLimitRecord.is_blocked == True
                )
            ).count()
            
            # Определяем статус банка
            status = self._determine_bank_status(
                error_rate, avg_response_time, webhook_failures, rate_limit_hits
            )
            
            # Создаем метрики банка
            metrics = BankHealthMetrics(
                bank_code=bank.code,
                status=status,
                last_successful_request=bank.last_used_at,
                last_error=error_logs[0].created_at if error_logs else None,
                total_requests_1h=total_requests,
                successful_requests_1h=successful_requests,
                failed_requests_1h=failed_requests,
                avg_response_time_ms=avg_response_time,
                error_rate_1h=error_rate,
                last_errors=last_errors,
                webhook_failures_1h=webhook_failures,
                rate_limit_hits_1h=rate_limit_hits
            )
            
            with self._lock:
                self._bank_metrics[bank.code] = metrics
    
    def _update_system_metrics(self, db: Session):
        """Обновление общих метрик системы"""
        # Получаем общее количество банков из БД
        total_banks_db = db.query(Bank).count()
        active_banks_db = db.query(Bank).filter(Bank.is_active == True).count()
        
        # Считаем общие метрики по всем банкам
        total_banks = len(self._bank_metrics)
        
        status_counts = defaultdict(int)
        total_requests = 0
        successful_requests = 0
        failed_requests = 0
        response_times = []
        all_errors = []
        
        for metrics in self._bank_metrics.values():
            status_counts[metrics.status] += 1
            total_requests += metrics.total_requests_1h
            successful_requests += metrics.successful_requests_1h
            failed_requests += metrics.failed_requests_1h
            
            if metrics.avg_response_time_ms > 0:
                response_times.append(metrics.avg_response_time_ms)
            
            all_errors.extend(metrics.last_errors)
        
        # Средний response time
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0
        
        # Error rate
        error_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0.0
        
        # Топ ошибок
        error_counts = defaultdict(int)
        for error in all_errors:
            if error:
                # Упрощаем ошибку для группировки
                simplified_error = error.split(':')[0] if ':' in error else error
                error_counts[simplified_error] += 1
        
        top_errors = [
            {"error": error, "count": count}
            for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        
        # Определяем общий статус системы
        overall_status = self._determine_system_status(status_counts, error_rate)
        
        # Создаем общие метрики
        with self._lock:
            self._system_metrics = SystemHealthMetrics(
                overall_status=overall_status,
                total_banks=total_banks_db,
                active_banks=active_banks_db,
                healthy_banks=status_counts[MonitoringStatus.HEALTHY],
                warning_banks=status_counts[MonitoringStatus.WARNING],
                error_banks=status_counts[MonitoringStatus.ERROR] + status_counts[MonitoringStatus.CRITICAL],
                total_requests_1h=total_requests,
                successful_requests_1h=successful_requests,
                failed_requests_1h=failed_requests,
                avg_response_time_ms=avg_response_time,
                error_rate_1h=error_rate,
                top_errors=top_errors
            )
    
    def _determine_bank_status(
        self,
        error_rate: float,
        avg_response_time: float,
        webhook_failures: int,
        rate_limit_hits: int
    ) -> MonitoringStatus:
        """Определение статуса банка"""
        
        # Критический статус
        if (error_rate >= self.ALERT_THRESHOLDS["error_rate_critical"] or
            avg_response_time >= self.ALERT_THRESHOLDS["response_time_critical"] or
            webhook_failures >= self.ALERT_THRESHOLDS["webhook_failure_critical"] or
            rate_limit_hits >= self.ALERT_THRESHOLDS["rate_limit_critical"]):
            return MonitoringStatus.CRITICAL
        
        # Ошибка
        if (error_rate >= self.ALERT_THRESHOLDS["error_rate_warning"] or
            avg_response_time >= self.ALERT_THRESHOLDS["response_time_warning"] or
            webhook_failures >= self.ALERT_THRESHOLDS["webhook_failure_warning"] or
            rate_limit_hits >= self.ALERT_THRESHOLDS["rate_limit_warning"]):
            return MonitoringStatus.ERROR
        
        # Предупреждение (более мягкие условия)
        if error_rate > 1.0 or avg_response_time > 2000 or webhook_failures > 0 or rate_limit_hits > 0:
            return MonitoringStatus.WARNING
        
        return MonitoringStatus.HEALTHY
    
    def _determine_system_status(
        self,
        status_counts: Dict[MonitoringStatus, int],
        error_rate: float
    ) -> MonitoringStatus:
        """Определение общего статуса системы"""
        
        total_banks = sum(status_counts.values())
        
        if total_banks == 0:
            return MonitoringStatus.UNKNOWN
        
        critical_banks = status_counts[MonitoringStatus.CRITICAL]
        error_banks = status_counts[MonitoringStatus.ERROR]
        
        # Если более 50% банков в критическом состоянии
        if critical_banks / total_banks > 0.5:
            return MonitoringStatus.CRITICAL
        
        # Если более 30% банков имеют ошибки
        if (critical_banks + error_banks) / total_banks > 0.3:
            return MonitoringStatus.ERROR
        
        # Если общий error rate высокий
        if error_rate >= self.ALERT_THRESHOLDS["error_rate_critical"]:
            return MonitoringStatus.CRITICAL
        elif error_rate >= self.ALERT_THRESHOLDS["error_rate_warning"]:
            return MonitoringStatus.ERROR
        
        # Если есть проблемные банки
        if critical_banks > 0 or error_banks > 0:
            return MonitoringStatus.WARNING
        
        return MonitoringStatus.HEALTHY
    
    def _check_alerts(self):
        """Проверка и генерация алертов"""
        current_time = datetime.now()
        
        # Проверяем алерты для каждого банка
        for bank_code, metrics in self._bank_metrics.items():
            self._check_bank_alerts(bank_code, metrics, current_time)
        
        # Проверяем системные алерты
        if self._system_metrics:
            self._check_system_alerts(self._system_metrics, current_time)
    
    def _check_bank_alerts(self, bank_code: str, metrics: BankHealthMetrics, current_time: datetime):
        """Проверка алертов для конкретного банка"""
        
        # Алерт по error rate
        if metrics.error_rate_1h >= self.ALERT_THRESHOLDS["error_rate_critical"]:
            self._create_alert(
                AlertSeverity.CRITICAL,
                f"Critical error rate for bank {bank_code}",
                f"Error rate: {metrics.error_rate_1h:.1f}% (threshold: {self.ALERT_THRESHOLDS['error_rate_critical']}%)",
                {"bank_code": bank_code, "error_rate": metrics.error_rate_1h},
                current_time
            )
        elif metrics.error_rate_1h >= self.ALERT_THRESHOLDS["error_rate_warning"]:
            self._create_alert(
                AlertSeverity.WARNING,
                f"High error rate for bank {bank_code}",
                f"Error rate: {metrics.error_rate_1h:.1f}% (threshold: {self.ALERT_THRESHOLDS['error_rate_warning']}%)",
                {"bank_code": bank_code, "error_rate": metrics.error_rate_1h},
                current_time
            )
        
        # Алерт по response time
        if metrics.avg_response_time_ms >= self.ALERT_THRESHOLDS["response_time_critical"]:
            self._create_alert(
                AlertSeverity.CRITICAL,
                f"Critical response time for bank {bank_code}",
                f"Avg response time: {metrics.avg_response_time_ms:.0f}ms (threshold: {self.ALERT_THRESHOLDS['response_time_critical']}ms)",
                {"bank_code": bank_code, "response_time": metrics.avg_response_time_ms},
                current_time
            )
        elif metrics.avg_response_time_ms >= self.ALERT_THRESHOLDS["response_time_warning"]:
            self._create_alert(
                AlertSeverity.WARNING,
                f"Slow response time for bank {bank_code}",
                f"Avg response time: {metrics.avg_response_time_ms:.0f}ms (threshold: {self.ALERT_THRESHOLDS['response_time_warning']}ms)",
                {"bank_code": bank_code, "response_time": metrics.avg_response_time_ms},
                current_time
            )
        
        # Алерт по webhook failures
        if metrics.webhook_failures_1h >= self.ALERT_THRESHOLDS["webhook_failure_critical"]:
            self._create_alert(
                AlertSeverity.CRITICAL,
                f"Critical webhook failures for bank {bank_code}",
                f"Webhook failures: {metrics.webhook_failures_1h} (threshold: {self.ALERT_THRESHOLDS['webhook_failure_critical']})",
                {"bank_code": bank_code, "webhook_failures": metrics.webhook_failures_1h},
                current_time
            )
        elif metrics.webhook_failures_1h >= self.ALERT_THRESHOLDS["webhook_failure_warning"]:
            self._create_alert(
                AlertSeverity.WARNING,
                f"Webhook failures for bank {bank_code}",
                f"Webhook failures: {metrics.webhook_failures_1h} (threshold: {self.ALERT_THRESHOLDS['webhook_failure_warning']})",
                {"bank_code": bank_code, "webhook_failures": metrics.webhook_failures_1h},
                current_time
            )
        
        # Алерт по rate limiting
        if metrics.rate_limit_hits_1h >= self.ALERT_THRESHOLDS["rate_limit_critical"]:
            self._create_alert(
                AlertSeverity.CRITICAL,
                f"Critical rate limiting for bank {bank_code}",
                f"Rate limit hits: {metrics.rate_limit_hits_1h} (threshold: {self.ALERT_THRESHOLDS['rate_limit_critical']})",
                {"bank_code": bank_code, "rate_limit_hits": metrics.rate_limit_hits_1h},
                current_time
            )
        elif metrics.rate_limit_hits_1h >= self.ALERT_THRESHOLDS["rate_limit_warning"]:
            self._create_alert(
                AlertSeverity.WARNING,
                f"Rate limiting for bank {bank_code}",
                f"Rate limit hits: {metrics.rate_limit_hits_1h} (threshold: {self.ALERT_THRESHOLDS['rate_limit_warning']})",
                {"bank_code": bank_code, "rate_limit_hits": metrics.rate_limit_hits_1h},
                current_time
            )
    
    def _check_system_alerts(self, metrics: SystemHealthMetrics, current_time: datetime):
        """Проверка системных алертов"""
        
        # Алерт по общему статусу системы
        if metrics.overall_status == MonitoringStatus.CRITICAL:
            self._create_alert(
                AlertSeverity.CRITICAL,
                "System in critical state",
                f"Overall error rate: {metrics.error_rate_1h:.1f}%, Critical/Error banks: {metrics.error_banks}",
                {"overall_status": metrics.overall_status.value, "error_rate": metrics.error_rate_1h},
                current_time
            )
        elif metrics.overall_status == MonitoringStatus.ERROR:
            self._create_alert(
                AlertSeverity.ERROR,
                "System has errors",
                f"Overall error rate: {metrics.error_rate_1h:.1f}%, Error banks: {metrics.error_banks}",
                {"overall_status": metrics.overall_status.value, "error_rate": metrics.error_rate_1h},
                current_time
            )
        
        # Алерт если много банков неактивны (только если есть банки в системе)
        if metrics.total_banks > 0 and metrics.active_banks / metrics.total_banks < 0.5 and metrics.total_banks > 1:
            self._create_alert(
                AlertSeverity.WARNING,
                "Many banks inactive",
                f"Only {metrics.active_banks}/{metrics.total_banks} banks are active",
                {"active_banks": metrics.active_banks, "total_banks": metrics.total_banks},
                current_time
            )
    
    def _check_immediate_alert(self, event: MonitoringEvent):
        """Проверка немедленных алертов для критических событий"""
        
        if event.event_type == MonitoringEventType.SYSTEM_ERROR:
            self._create_alert(
                AlertSeverity.CRITICAL,
                "System error occurred",
                event.error_message or "Unknown system error",
                {"event_type": event.event_type.value, "bank_code": event.bank_code},
                event.timestamp
            )
        
        elif event.event_type == MonitoringEventType.AUTHENTICATION_FAILED:
            self._create_alert(
                AlertSeverity.WARNING,
                f"Authentication failed for bank {event.bank_code}",
                event.error_message or "Authentication failure",
                {"event_type": event.event_type.value, "bank_code": event.bank_code, "ip": event.ip_address},
                event.timestamp
            )
        elif event.event_type in (MonitoringEventType.API_TIMEOUT, MonitoringEventType.API_5XX):
            # Немедленный алерт о недоступности API
            self._create_alert(
                AlertSeverity.CRITICAL,
                f"API unavailable for bank {event.bank_code}",
                event.error_message or "API timeout/5xx",
                {"event_type": event.event_type.value, "bank_code": event.bank_code, "endpoint": event.endpoint},
                event.timestamp
            )

    def _record_api_failure(self, event: MonitoringEvent) -> None:
        """Фиксация ошибки API и проверка порога для алерта API_UNAVAILABLE"""
        if not event.bank_code:
            return
        now = event.timestamp
        with self._lock:
            history = self._api_failure_history[event.bank_code]
            history.append(now)
            # Очищаем старые записи вне окна
            window_start = now - timedelta(seconds=self.API_UNAVAILABLE_WINDOW_SECONDS)
            while history and history[0] < window_start:
                history.popleft()
            # Проверяем порог
            if len(history) >= self.API_UNAVAILABLE_THRESHOLD and event.bank_code not in self._api_unavailable_active:
                self._api_unavailable_active.add(event.bank_code)
                self._create_alert(
                    AlertSeverity.CRITICAL,
                    f"API unavailable (threshold) for bank {event.bank_code}",
                    f"More than {self.API_UNAVAILABLE_THRESHOLD} failures in {self.API_UNAVAILABLE_WINDOW_SECONDS}s",
                    {"bank_code": event.bank_code, "failures": len(history), "endpoint": event.endpoint},
                    now
                )

    def _record_api_success(self, event: MonitoringEvent) -> None:
        """Сброс состояния недоступности и INFO-алерт о восстановлении"""
        if not event.bank_code:
            return
        with self._lock:
            was_unavailable = event.bank_code in self._api_unavailable_active
            if was_unavailable:
                self._api_unavailable_active.discard(event.bank_code)
                self._api_failure_history[event.bank_code].clear()
                self._create_alert(
                    AlertSeverity.INFO,
                    f"API restored for bank {event.bank_code}",
                    "API responses are healthy again",
                    {"bank_code": event.bank_code, "endpoint": event.endpoint},
                    event.timestamp
                )
    
    def _create_alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        metadata: Dict[str, Any],
        timestamp: datetime
    ):
        """Создание алерта"""
        # Подавление системных алертов при отключении
        is_system_alert = not metadata or not metadata.get("bank_code")
        if is_system_alert and not self.SYSTEM_ALERTS_ENABLED:
            return

        # Троттлинг: не создавать повторяющиеся алерты чаще, чем раз в ALERT_COOLDOWN_SECONDS,
        # если сообщение не изменилось
        alert_key = f"{severity.value}:{title}:{metadata.get('bank_code', 'system')}"
        with self._lock:
            last_time = self._last_alert_time.get(alert_key)
            last_msg = self._last_alert_message.get(alert_key)
            if last_time and (timestamp - last_time).total_seconds() < self.ALERT_COOLDOWN_SECONDS and last_msg == message:
                return

            alert = {
                "id": f"alert_{int(timestamp.timestamp())}_{hash(title) % 10000}",
                "severity": severity.value,
                "title": title,
                "message": message,
                "timestamp": timestamp.isoformat(),
                "metadata": metadata,
                "acknowledged": False
            }

            self._alerts.append(alert)
            self._last_alert_time[alert_key] = timestamp
            self._last_alert_message[alert_key] = message

        logger.warning(f"Alert created [{severity.value}]: {title} - {message}")
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Получение текущих метрик"""
        with self._lock:
            return {
                "system_metrics": asdict(self._system_metrics) if self._system_metrics else None,
                "bank_metrics": {
                    bank_code: asdict(metrics) 
                    for bank_code, metrics in self._bank_metrics.items()
                },
                "last_updated": datetime.now().isoformat()
            }
    
    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Получение недавних событий"""
        with self._lock:
            events = list(self._events_buffer)[-limit:]
        
        return [event.to_dict() for event in events]
    
    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Получение недавних алертов"""
        with self._lock:
            return list(self._alerts)[-limit:]
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Подтверждение алерта"""
        with self._lock:
            for alert in self._alerts:
                if alert["id"] == alert_id:
                    alert["acknowledged"] = True
                    alert["acknowledged_at"] = datetime.now().isoformat()
                    return True
        return False
    
    def subscribe_to_updates(self, callback: callable):
        """Подписка на обновления мониторинга"""
        self._subscribers.add(callback)
    
    def unsubscribe_from_updates(self, callback: callable):
        """Отписка от обновлений мониторинга"""
        self._subscribers.discard(callback)
    
    def _notify_subscribers(self):
        """Уведомление подписчиков об обновлениях"""
        if not self._subscribers:
            return
        
        try:
            current_metrics = self.get_current_metrics()
            recent_alerts = self.get_recent_alerts(10)
            
            update_data = {
                "type": "monitoring_update",
                "timestamp": datetime.now().isoformat(),
                "metrics": current_metrics,
                "alerts": recent_alerts
            }
            
            # Уведомляем всех подписчиков
            for callback in list(self._subscribers):
                try:
                    callback(update_data)
                except Exception as e:
                    logger.error(f"Error notifying subscriber: {e}")
                    # Удаляем неработающего подписчика
                    self._subscribers.discard(callback)
        
        except Exception as e:
            logger.error(f"Error notifying subscribers: {e}")
    
    def get_bank_status_history(self, bank_code: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Получение истории статуса банка"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                since = datetime.now() - timedelta(hours=hours)
                
                # Получаем логи банка за указанный период
                logs = db.query(PaymentLog).filter(
                    and_(
                        PaymentLog.bank_code == bank_code,
                        PaymentLog.created_at >= since
                    )
                ).order_by(PaymentLog.created_at).all()
                
                # Группируем по часам
                hourly_stats = defaultdict(lambda: {
                    "timestamp": None,
                    "total_requests": 0,
                    "successful_requests": 0,
                    "failed_requests": 0,
                    "avg_response_time": 0.0,
                    "error_rate": 0.0
                })
                
                for log in logs:
                    hour_key = log.created_at.replace(minute=0, second=0, microsecond=0)
                    stats = hourly_stats[hour_key]
                    
                    stats["timestamp"] = hour_key.isoformat()
                    stats["total_requests"] += 1
                    
                    if log.error_message:
                        stats["failed_requests"] += 1
                    else:
                        stats["successful_requests"] += 1
                    
                    if log.request_duration_ms:
                        # Пересчитываем среднее время ответа
                        current_avg = stats["avg_response_time"]
                        total = stats["total_requests"]
                        stats["avg_response_time"] = (
                            (current_avg * (total - 1) + log.request_duration_ms) / total
                        )
                
                # Вычисляем error rate
                for stats in hourly_stats.values():
                    if stats["total_requests"] > 0:
                        stats["error_rate"] = (
                            stats["failed_requests"] / stats["total_requests"] * 100
                        )
                
                return sorted(hourly_stats.values(), key=lambda x: x["timestamp"])
        
        except Exception as e:
            logger.error(f"Error getting bank status history: {e}")
            return []

    # === МЕТОДЫ ДЛЯ МОНИТОРИНГА ВОЗВРАТОВ ===
    
    def record_refund_request(
        self,
        merchant_id: int,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool,
        refund_amount: float,
        refund_type: str,
        error_message: Optional[str] = None
    ):
        """Запись события создания возврата"""
        try:
            event = MonitoringEvent(
                event_type=MonitoringEventType.REFUND_REQUEST,
                timestamp=datetime.now(),
                endpoint=endpoint,
                ip_address=ip_address,
                response_time_ms=response_time_ms,
                amount=refund_amount,
                success=success,
                error_message=error_message,
                metadata={
                    "merchant_id": merchant_id,
                    "refund_type": refund_type
                }
            )
            
            self.record_event(event)
            
            # Создаем алерт при ошибке
            if not success:
                self._create_alert(
                    AlertSeverity.ERROR,
                    f"Ошибка создания возврата: {error_message}",
                    f"Merchant {merchant_id}, Amount: {refund_amount}",
                    metadata={"merchant_id": merchant_id, "refund_amount": refund_amount},
                    timestamp=datetime.now()
                )
        
        except Exception as e:
            logger.error(f"Error recording refund request: {e}")
    
    def record_refund_execution(
        self,
        merchant_id: int,
        refund_id: int,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool,
        refund_amount: float,
        refund_status: str,
        error_message: Optional[str] = None
    ):
        """Запись события выполнения возврата"""
        try:
            event = MonitoringEvent(
                event_type=MonitoringEventType.REFUND_EXECUTION,
                timestamp=datetime.now(),
                endpoint=endpoint,
                ip_address=ip_address,
                response_time_ms=response_time_ms,
                amount=refund_amount,
                success=success,
                error_message=error_message,
                metadata={
                    "merchant_id": merchant_id,
                    "refund_id": refund_id,
                    "refund_status": refund_status
                }
            )
            
            self.record_event(event)
            
            # Создаем алерт при ошибке
            if not success:
                self._create_alert(
                    AlertSeverity.ERROR,
                    f"Ошибка выполнения возврата: {error_message}",
                    f"Refund {refund_id}, Merchant {merchant_id}, Amount: {refund_amount}",
                    metadata={"refund_id": refund_id, "merchant_id": merchant_id, "refund_amount": refund_amount},
                    timestamp=datetime.now()
                )
        
        except Exception as e:
            logger.error(f"Error recording refund execution: {e}")
    
    def record_refund_cancellation(
        self,
        merchant_id: int,
        refund_id: int,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool,
        refund_amount: float,
        error_message: Optional[str] = None
    ):
        """Запись события отмены возврата"""
        try:
            event = MonitoringEvent(
                event_type=MonitoringEventType.REFUND_CANCELLATION,
                timestamp=datetime.now(),
                endpoint=endpoint,
                ip_address=ip_address,
                response_time_ms=response_time_ms,
                amount=refund_amount,
                success=success,
                error_message=error_message,
                metadata={
                    "merchant_id": merchant_id,
                    "refund_id": refund_id
                }
            )
            
            self.record_event(event)
            
            # Создаем алерт при ошибке
            if not success:
                self._create_alert(
                    AlertSeverity.WARNING,
                    f"Ошибка отмены возврата: {error_message}",
                    f"Refund {refund_id}, Merchant {merchant_id}, Amount: {refund_amount}",
                    metadata={"refund_id": refund_id, "merchant_id": merchant_id, "refund_amount": refund_amount},
                    timestamp=datetime.now()
                )
        
        except Exception as e:
            logger.error(f"Error recording refund cancellation: {e}")
    
    def record_admin_refund_execution(
        self,
        admin_id: int,
        refund_id: int,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool,
        refund_amount: float,
        refund_status: str,
        error_message: Optional[str] = None
    ):
        """Запись события административного выполнения возврата"""
        try:
            event = MonitoringEvent(
                event_type=MonitoringEventType.ADMIN_REFUND_EXECUTION,
                timestamp=datetime.now(),
                endpoint=endpoint,
                ip_address=ip_address,
                response_time_ms=response_time_ms,
                amount=refund_amount,
                success=success,
                error_message=error_message,
                metadata={
                    "admin_id": admin_id,
                    "refund_id": refund_id,
                    "refund_status": refund_status
                }
            )
            
            self.record_event(event)
            
            # Создаем алерт при ошибке
            if not success:
                self._create_alert(
                    AlertSeverity.ERROR,
                    f"Ошибка административного выполнения возврата: {error_message}",
                    f"Admin {admin_id}, Refund {refund_id}, Amount: {refund_amount}",
                    metadata={"admin_id": admin_id, "refund_id": refund_id, "refund_amount": refund_amount},
                    timestamp=datetime.now()
                )
        
        except Exception as e:
            logger.error(f"Error recording admin refund execution: {e}")
    
    def record_admin_refund_cancellation(
        self,
        admin_id: int,
        refund_id: int,
        endpoint: str,
        ip_address: str,
        response_time_ms: float,
        success: bool,
        refund_amount: float,
        error_message: Optional[str] = None
    ):
        """Запись события административной отмены возврата"""
        try:
            event = MonitoringEvent(
                event_type=MonitoringEventType.ADMIN_REFUND_CANCELLATION,
                timestamp=datetime.now(),
                endpoint=endpoint,
                ip_address=ip_address,
                response_time_ms=response_time_ms,
                amount=refund_amount,
                success=success,
                error_message=error_message,
                metadata={
                    "admin_id": admin_id,
                    "refund_id": refund_id
                }
            )
            
            self.record_event(event)
            
            # Создаем алерт при ошибке
            if not success:
                self._create_alert(
                    AlertSeverity.WARNING,
                    f"Ошибка административной отмены возврата: {error_message}",
                    f"Admin {admin_id}, Refund {refund_id}, Amount: {refund_amount}",
                    metadata={"admin_id": admin_id, "refund_id": refund_id, "refund_amount": refund_amount},
                    timestamp=datetime.now()
                )
        
        except Exception as e:
            logger.error(f"Error recording admin refund cancellation: {e}")
    
    def get_refund_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """Получение метрик по возвратам"""
        try:
            since = datetime.now() - timedelta(hours=hours)
            
            # Фильтруем события возвратов
            refund_events = [
                event for event in self._recent_events
                if event.timestamp >= since and event.event_type in [
                    MonitoringEventType.REFUND_REQUEST,
                    MonitoringEventType.REFUND_EXECUTION,
                    MonitoringEventType.REFUND_CANCELLATION,
                    MonitoringEventType.ADMIN_REFUND_EXECUTION,
                    MonitoringEventType.ADMIN_REFUND_CANCELLATION
                ]
            ]
            
            # Статистика по типам событий
            event_counts = defaultdict(int)
            success_counts = defaultdict(int)
            total_amount = 0.0
            avg_response_time = 0.0
            
            for event in refund_events:
                event_counts[event.event_type] += 1
                if event.success:
                    success_counts[event.event_type] += 1
                
                if event.amount:
                    total_amount += event.amount
                
                if event.response_time_ms:
                    avg_response_time += event.response_time_ms
            
            # Вычисляем средние значения
            total_events = len(refund_events)
            if total_events > 0:
                avg_response_time /= total_events
            
            # Вычисляем success rate
            success_rates = {}
            for event_type, count in event_counts.items():
                success_rates[event_type] = (
                    success_counts[event_type] / count * 100 if count > 0 else 0
                )
            
            return {
                "total_refund_events": total_events,
                "event_counts": dict(event_counts),
                "success_rates": success_rates,
                "total_refund_amount": abs(total_amount),
                "avg_response_time_ms": avg_response_time,
                "period_hours": hours
            }
        
        except Exception as e:
            logger.error(f"Error getting refund metrics: {e}")
            return {}

# Глобальный экземпляр сервиса мониторинга
realtime_monitoring_service = RealtimeMonitoringService()
