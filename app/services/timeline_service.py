from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
import json
import threading
import time

from app.models.timeline import TimelineEvent


class TimelineService:
    _pending_thread_started = False

    @staticmethod
    def record_event(
        db: Session,
        *,
        payment_token: Optional[str] = None,
        transaction_id: Optional[str] = None,
        refund_token: Optional[str] = None,  # Новый параметр для возвратов
        event_type: str,
        title: str,
        description: Optional[str] = None,
        actor: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> TimelineEvent:
        ts = timestamp or datetime.now(timezone.utc)
        evt = TimelineEvent(
            payment_token=payment_token,
            transaction_id=transaction_id,
            refund_token=refund_token,  # Добавляем токен возврата
            event_type=event_type,
            title=title,
            description=description,
            actor=actor,
            source=source,
            status=status,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            timestamp_utc=ts,
        )
        db.add(evt)
        db.commit()
        db.refresh(evt)
        return evt

    @staticmethod
    def start_pending_checker(db_factory, timeout_minutes: int = 15, interval_seconds: int = 60):
        if TimelineService._pending_thread_started:
            return
        TimelineService._pending_thread_started = True

        def _worker():
            while True:
                try:
                    with db_factory() as db:
                        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
                        # Ищем события info_requested без webhook_success после cutoff
                        # Селектим токены, у которых есть info_requested < cutoff и нет webhook_success
                        # Простая стратегия: получаем кандидатов по payment_token
                        from sqlalchemy import and_, not_, exists, select

                        sub_success = select(TimelineEvent.payment_token).where(
                            TimelineEvent.event_type == 'webhook_success'
                        )

                        q = db.query(TimelineEvent.payment_token).filter(
                            and_(
                                TimelineEvent.event_type == 'info_requested',
                                TimelineEvent.timestamp_utc < cutoff,
                            )
                        ).distinct()

                        tokens = [row[0] for row in q if row[0]]
                        for token in tokens:
                            has_success = db.query(TimelineEvent.id).filter(
                                TimelineEvent.payment_token == token,
                                TimelineEvent.event_type == 'webhook_success'
                            ).first()
                            has_timeout = db.query(TimelineEvent.id).filter(
                                TimelineEvent.payment_token == token,
                                TimelineEvent.event_type == 'pending_timeout'
                            ).first()
                            if (not has_success) and (not has_timeout):
                                TimelineService.record_event(
                                    db,
                                    payment_token=token,
                                    event_type='pending_timeout',
                                    title='Сканировали, но не оплатили',
                                    description=f'Нет webhook более {timeout_minutes} минут после запроса информации',
                                    actor='system',
                                    source='service',
                                    status='pending',
                                )
                except Exception:
                    pass
                time.sleep(interval_seconds)

    # === МЕТОДЫ ДЛЯ СОБЫТИЙ ВОЗВРАТОВ ===
    
    @staticmethod
    def record_refund_created(
        db: Session,
        refund_token: str,
        merchant_id: int,
        amount: float,
        currency: str,
        refund_type: str,
        reason: str,
        actor: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события создания возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_created",
            title="Возврат создан",
            description=f"Создан возврат на сумму {amount} {currency} ({refund_type})",
            actor=actor or f"merchant_{merchant_id}",
            source="merchant_api",
            status="created",
            metadata={
                "merchant_id": merchant_id,
                "amount": amount,
                "currency": currency,
                "refund_type": refund_type,
                "reason": reason
            }
        )
    
    @staticmethod
    def record_refund_execution_started(
        db: Session,
        refund_token: str,
        merchant_id: int,
        actor: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события начала выполнения возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_execution_started",
            title="Выполнение возврата начато",
            description="Запущен двухфазный протокол возврата",
            actor=actor or f"merchant_{merchant_id}",
            source="two_phase_service",
            status="executing",
            metadata={
                "merchant_id": merchant_id,
                "phase": "started"
            }
        )
    
    @staticmethod
    def record_refund_prepare_phase(
        db: Session,
        refund_token: str,
        bank_code: str,
        bank_role: str,
        success: bool,
        error_message: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события фазы подготовки возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_prepare_phase",
            title=f"Фаза подготовки возврата ({bank_role})",
            description=f"Банк {bank_code} ({bank_role}): {'успешно' if success else 'ошибка'}",
            actor=f"bank_{bank_code}",
            source="two_phase_service",
            status="success" if success else "failed",
            metadata={
                "bank_code": bank_code,
                "bank_role": bank_role,
                "phase": "prepare",
                "success": success,
                "error_message": error_message
            }
        )
    
    @staticmethod
    def record_refund_commit_phase(
        db: Session,
        refund_token: str,
        bank_code: str,
        bank_role: str,
        success: bool,
        error_message: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события фазы выполнения возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_commit_phase",
            title=f"Фаза выполнения возврата ({bank_role})",
            description=f"Банк {bank_code} ({bank_role}): {'успешно' if success else 'ошибка'}",
            actor=f"bank_{bank_code}",
            source="two_phase_service",
            status="success" if success else "failed",
            metadata={
                "bank_code": bank_code,
                "bank_role": bank_role,
                "phase": "commit",
                "success": success,
                "error_message": error_message
            }
        )
    
    @staticmethod
    def record_refund_completed(
        db: Session,
        refund_token: str,
        merchant_id: int,
        amount: float,
        currency: str,
        actor: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события завершения возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_completed",
            title="Возврат выполнен",
            description=f"Возврат на сумму {amount} {currency} успешно выполнен",
            actor=actor or f"merchant_{merchant_id}",
            source="two_phase_service",
            status="completed",
            metadata={
                "merchant_id": merchant_id,
                "amount": amount,
                "currency": currency
            }
        )
    
    @staticmethod
    def record_refund_failed(
        db: Session,
        refund_token: str,
        merchant_id: int,
        error_message: str,
        actor: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события неудачного возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_failed",
            title="Возврат не выполнен",
            description=f"Ошибка выполнения возврата: {error_message}",
            actor=actor or f"merchant_{merchant_id}",
            source="two_phase_service",
            status="failed",
            metadata={
                "merchant_id": merchant_id,
                "error_message": error_message
            }
        )
    
    @staticmethod
    def record_refund_cancelled(
        db: Session,
        refund_token: str,
        merchant_id: int,
        reason: str,
        actor: Optional[str] = None
    ) -> TimelineEvent:
        """Запись события отмены возврата"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type="refund_cancelled",
            title="Возврат отменен",
            description=f"Возврат отменен: {reason}",
            actor=actor or f"merchant_{merchant_id}",
            source="merchant_api",
            status="cancelled",
            metadata={
                "merchant_id": merchant_id,
                "reason": reason
            }
        )
    
    @staticmethod
    def record_admin_refund_action(
        db: Session,
        refund_token: str,
        admin_id: int,
        action: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TimelineEvent:
        """Запись события административного действия с возвратом"""
        return TimelineService.record_event(
            db=db,
            refund_token=refund_token,
            event_type=f"admin_refund_{action}",
            title=f"Административное действие: {action}",
            description=description,
            actor=f"admin_{admin_id}",
            source="admin_api",
            status="admin_action",
            metadata={
                "admin_id": admin_id,
                "action": action,
                **(metadata or {})
            }
        )
