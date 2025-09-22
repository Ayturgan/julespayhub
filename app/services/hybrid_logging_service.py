"""
Гибридный сервис логирования для QRPayHub

Принцип работы:
- Критичные операции -> БД (синхронно)
- Остальные операции -> Файлы (асинхронно)
- Асинхронная очередь для предотвращения блокировки
"""

import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
import threading
from queue import Queue, Empty as queue_Empty
import time

from app.models.payment import PaymentLog, BillingRecord
from app.models.audit import AuditLog
from app.models.timeline import TimelineEvent
from app.database import get_db

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Уровни логирования"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogDestination(str, Enum):
    """Назначения для логирования"""
    DATABASE = "database"      # Критичные операции в БД
    FILE = "file"             # Обычные операции в файлы
    BOTH = "both"             # И в БД, и в файлы


@dataclass
class LogEvent:
    """Структура события для логирования"""
    timestamp: datetime
    level: LogLevel
    destination: LogDestination
    event_type: str
    event_source: str
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = "success"
    details: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    
    # Специфичные поля для платежей
    payment_token: Optional[str] = None
    transaction_id: Optional[str] = None
    bank_code: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None


class HybridLoggingService:
    """
    Гибридный сервис логирования
    
    Принципы:
    1. Критичные операции -> БД (синхронно)
    2. Обычные операции -> Файлы (асинхронно)
    3. Асинхронная очередь для предотвращения блокировки
    """
    
    # Добавляем ссылки на перечисления как атрибуты класса
    LogLevel = LogLevel
    LogDestination = LogDestination
    LogEvent = LogEvent
    
    def __init__(self):
        self._queue = Queue(maxsize=1000)
        self._worker_thread = None
        self._running = False
        self._start_worker()
    
    def _start_worker(self):
        """Запуск фонового потока для обработки очереди"""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._running = True
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
            logger.info("HybridLoggingService: Worker thread started")
    
    def _stop_worker(self):
        """Остановка фонового потока"""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
            logger.info("HybridLoggingService: Worker thread stopped")
    
    def _process_queue(self):
        """Обработка очереди событий в фоновом потоке"""
        while self._running:
            try:
                # Получаем событие из очереди с таймаутом
                event = self._queue.get(timeout=1)
                self._write_to_file(event)
                self._queue.task_done()
            except queue_Empty:
                # Таймаут - это нормально, продолжаем цикл
                continue
            except Exception as e:
                if self._running:  # Игнорируем ошибки при остановке
                    logger.error(f"Error processing log event: {e}")
    
    def _write_to_file(self, event: LogEvent):
        """Запись события в файл"""
        try:
            log_data = {
                "timestamp": event.timestamp.isoformat(),
                "level": event.level.value,
                "event_type": event.event_type,
                "event_source": event.event_source,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "ip_address": event.ip_address,
                "status": event.status,
                "details": event.details,
                "error_message": event.error_message,
                "duration_ms": event.duration_ms,
                "payment_token": event.payment_token,
                "transaction_id": event.transaction_id,
                "bank_code": event.bank_code,
                "amount": event.amount,
                "currency": event.currency
            }
            
            # Выбираем подходящий логгер в зависимости от типа события
            if event.event_type in ["payment_success", "payment_failed", "webhook_received"]:
                logger_name = "payment_operations"
            elif event.event_type in ["admin_action", "security_alert"]:
                logger_name = "security"
            elif event.level in [LogLevel.ERROR, LogLevel.CRITICAL]:
                logger_name = "qrpayhub_errors"  # Используем root logger для ошибок
            elif event.event_source == "api":
                logger_name = "api_requests"
            else:
                logger_name = "qrpayhub_all"  # Используем root logger для остальных
            
            file_logger = logging.getLogger(logger_name)
            
            # Формируем сообщение
            message = f"{json.dumps(log_data, ensure_ascii=False)}"
            
            # Логируем с соответствующим уровнем
            if event.level == LogLevel.DEBUG:
                file_logger.debug(message)
            elif event.level == LogLevel.INFO:
                file_logger.info(message)
            elif event.level == LogLevel.WARNING:
                file_logger.warning(message)
            elif event.level == LogLevel.ERROR:
                file_logger.error(message)
            elif event.level == LogLevel.CRITICAL:
                file_logger.critical(message)
                
        except Exception as e:
            logger.error(f"Failed to write log event to file: {e}")
    
    def _should_log_to_db(self, event: LogEvent) -> bool:
        """
        Определяет, нужно ли логировать событие в БД
        
        В БД логируем ТОЛЬКО:
        - Успешные платежи (для отчетности)
        - Админские действия (для аудита)
        - Критические ошибки (для мониторинга)
        - Ключевые события timeline (для отслеживания)
        """
        return (
            # Успешные платежи
            (event.event_type == "payment_success" and event.status == "success") or
            # Админские действия
            (event.event_type == "admin_action") or
            # Критические ошибки
            (event.level == LogLevel.CRITICAL) or
            # Ключевые события timeline
            (event.event_type in [
                "qr_created", "payment_initiated", "webhook_success", 
                "webhook_failed", "transaction_recorded", "billing_recorded"
            ])
        )
    
    def log_event(self, event: LogEvent, db: Optional[Session] = None):
        """
        Основной метод логирования события
        
        Args:
            event: Событие для логирования
            db: Сессия БД (если нужна запись в БД)
        """
        try:
            # Определяем назначения для логирования
            destinations = []
            
            if event.destination == LogDestination.DATABASE:
                destinations.append("database")
            elif event.destination == LogDestination.FILE:
                destinations.append("file")
            elif event.destination == LogDestination.BOTH:
                destinations.append("database")
                destinations.append("file")
            else:
                # Автоматическое определение
                if self._should_log_to_db(event):
                    destinations.append("database")
                destinations.append("file")
            
            # Записываем в файлы (асинхронно)
            if "file" in destinations:
                try:
                    self._queue.put_nowait(event)
                except Exception as e:
                    logger.error(f"Failed to queue log event: {e}")
            
            # Записываем в БД (синхронно, только если нужно)
            if "database" in destinations and db:
                self._write_to_database(event, db)
                
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
    
    def _write_to_database(self, event: LogEvent, db: Session):
        """Запись события в БД"""
        try:
            if event.event_type == "payment_success":
                self._log_payment_success(event, db)
            elif event.event_type == "admin_action":
                self._log_admin_action(event, db)
            elif event.event_type in ["qr_created", "payment_initiated", "webhook_success", 
                                    "webhook_failed", "transaction_recorded", "billing_recorded"]:
                self._log_timeline_event(event, db)
            else:
                # Для остальных критичных событий используем AuditLog
                self._log_audit_event(event, db)
                
        except Exception as e:
            logger.error(f"Failed to write to database: {e}")
    
    def _log_payment_success(self, event: LogEvent, db: Session):
        """Логирование успешного платежа в BillingRecord"""
        if not event.payment_token or not event.transaction_id:
            return
            
        billing_record = BillingRecord(
            payment_token=event.payment_token,
            transaction_id=event.transaction_id,
            amount=event.amount or 0.0,
            currency=event.currency or "KGS",
            payer_phone=event.details.get("payer_phone") if event.details else None,
            payer_bank_code=event.bank_code,
            receiver_account=event.details.get("receiver_account") if event.details else "",
            receiver_bank_code=event.details.get("receiver_bank_code") if event.details else "",
            receiver_name=event.details.get("receiver_name") if event.details else "",
            payment_description=event.details.get("description") if event.details else "",
            payment_reference=event.details.get("reference") if event.details else "",
            payment_date=event.timestamp,
            ip_address=event.ip_address,
            user_agent=event.details.get("user_agent") if event.details else None
        )
        
        db.add(billing_record)
        db.commit()
        logger.info(f"Logged successful payment to BillingRecord: {event.transaction_id}")
    
    def _log_admin_action(self, event: LogEvent, db: Session):
        """Логирование админского действия в AuditLog"""
        audit_log = AuditLog(
            timestamp_utc=event.timestamp,
            event_type=event.event_type,
            event_source=event.event_source,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            status=event.status,
            ip_address=event.ip_address,
            details_json=json.dumps(event.details, ensure_ascii=False) if event.details else None
        )
        
        db.add(audit_log)
        db.commit()
        logger.info(f"Logged admin action to AuditLog: {event.event_type}")
    
    def _log_timeline_event(self, event: LogEvent, db: Session):
        """Логирование ключевого события в TimelineEvent"""
        timeline_event = TimelineEvent(
            transaction_id=event.transaction_id,
            payment_token=event.payment_token,
            event_type=event.event_type,
            title=event.details.get("title") if event.details else event.event_type,
            description=event.details.get("description") if event.details else None,
            actor=event.actor_type,
            source=event.event_source,
            status=event.status,
            metadata_json=json.dumps(event.details, ensure_ascii=False) if event.details else None,
            timestamp_utc=event.timestamp
        )
        
        db.add(timeline_event)
        db.commit()
        logger.info(f"Logged timeline event: {event.event_type}")
    
    def _log_audit_event(self, event: LogEvent, db: Session):
        """Логирование критичного события в AuditLog"""
        audit_log = AuditLog(
            timestamp_utc=event.timestamp,
            event_type=event.event_type,
            event_source=event.event_source,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            status=event.status,
            ip_address=event.ip_address,
            details_json=json.dumps(event.details, ensure_ascii=False) if event.details else None
        )
        
        db.add(audit_log)
        db.commit()
        logger.info(f"Logged audit event: {event.event_type}")
    
    def log_payment_success(
        self,
        db: Session,
        payment_token: str,
        transaction_id: str,
        amount: float,
        currency: str = "KGS",
        bank_code: str = None,
        payer_phone: str = None,
        receiver_account: str = None,
        receiver_bank_code: str = None,
        receiver_name: str = None,
        description: str = None,
        reference: str = None,
        ip_address: str = None,
        user_agent: str = None
    ):
        """Логирование успешного платежа"""
        event = LogEvent(
            timestamp=datetime.utcnow(),
            level=LogLevel.INFO,
            destination=LogDestination.BOTH,  # И в БД, и в файлы
            event_type="payment_success",
            event_source="payment_api",
            actor_type="bank",
            actor_id=bank_code,
            ip_address=ip_address,
            status="success",
            payment_token=payment_token,
            transaction_id=transaction_id,
            bank_code=bank_code,
            amount=amount,
            currency=currency,
            details={
                "payer_phone": payer_phone,
                "receiver_account": receiver_account,
                "receiver_bank_code": receiver_bank_code,
                "receiver_name": receiver_name,
                "description": description,
                "reference": reference,
                "user_agent": user_agent
            }
        )
        
        self.log_event(event, db)
    
    def log_admin_action(
        self,
        db: Session,
        action: str,
        target: str = None,
        details: Dict[str, Any] = None,
        actor_id: str = None,
        ip_address: str = None
    ):
        """Логирование админского действия"""
        event = LogEvent(
            timestamp=datetime.utcnow(),
            level=LogLevel.INFO,
            destination=LogDestination.BOTH,
            event_type="admin_action",
            event_source="admin_panel",
            actor_type="admin",
            actor_id=actor_id,
            ip_address=ip_address,
            status="success",
            details={"action": action, "target": target, **(details or {})}
        )
        
        self.log_event(event, db)
    
    def log_api_request(
        self,
        request_type: str,
        endpoint: str,
        method: str,
        status_code: int,
        duration_ms: int,
        ip_address: str = None,
        bank_code: str = None,
        payment_token: str = None,
        error_message: str = None,
        user_agent: str = None
    ):
        """Логирование API запроса (только в файлы)"""
        level = LogLevel.ERROR if status_code >= 400 else LogLevel.INFO
        
        event = LogEvent(
            timestamp=datetime.utcnow(),
            level=level,
            destination=LogDestination.FILE,  # Только в файлы
            event_type="api_request",
            event_source="api",
            actor_type="bank" if bank_code else "system",
            actor_id=bank_code,
            ip_address=ip_address,
            status="success" if status_code < 400 else "error",
            duration_ms=duration_ms,
            payment_token=payment_token,
            bank_code=bank_code,
            error_message=error_message,
            details={
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "user_agent": user_agent
            }
        )
        
        self.log_event(event)  # Без БД
    
    def log_timeline_event(
        self,
        db: Session,
        event_type: str,
        title: str,
        description: str = None,
        payment_token: str = None,
        transaction_id: str = None,
        actor: str = None,
        source: str = None,
        status: str = "info",
        details: Dict[str, Any] = None
    ):
        """Логирование ключевого события timeline"""
        event = LogEvent(
            timestamp=datetime.utcnow(),
            level=LogLevel.INFO,
            destination=LogDestination.BOTH,
            event_type=event_type,
            event_source=source or "system",
            actor_type=actor,
            status=status,
            payment_token=payment_token,
            transaction_id=transaction_id,
            details={"title": title, "description": description, **(details or {})}
        )
        
        self.log_event(event, db)
    
    def cleanup_old_records(self, db: Session, days: int = 30):
        """Очистка старых записей из БД"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Очищаем старые записи аудита (кроме админских действий)
            deleted_audit = db.query(AuditLog).filter(
                and_(
                    AuditLog.timestamp_utc < cutoff_date,
                    AuditLog.event_type != "admin_action"
                )
            ).delete()
            
            # Очищаем старые записи timeline
            deleted_timeline = db.query(TimelineEvent).filter(
                TimelineEvent.timestamp_utc < cutoff_date
            ).delete()
            
            db.commit()
            
            logger.info(f"Cleaned up {deleted_audit} audit records and {deleted_timeline} timeline records older than {days} days")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
            db.rollback()


# Глобальный экземпляр сервиса
hybrid_logging_service = HybridLoggingService()
