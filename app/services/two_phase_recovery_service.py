"""
Сервис восстановления двухфазных транзакций (Recovery Service)
Обрабатывает зависшие транзакции и обеспечивает отказоустойчивость
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
import logging
import asyncio
import json
from contextlib import asynccontextmanager

from app.database import get_db
from app.models.unified import UnifiedPayment
from app.models.payment import TransactionStatus, TwoPhaseOperation
from app.services.two_phase_commit_service import two_phase_commit_service
from app.services.timeline_service import TimelineService

logger = logging.getLogger(__name__)

class TwoPhaseRecoveryService:
    """Сервис восстановления зависших двухфазных транзакций"""
    
    def __init__(self):
        self.running = False
        self.check_interval = 60  # Проверка каждую минуту
        self.prepare_timeout = 300  # 5 минут на подготовку
        self.commit_timeout = 180   # 3 минуты на commit
        self.abort_timeout = 120    # 2 минуты на abort
        self.max_recovery_attempts = 3
        
    async def start_background_recovery(self):
        """Запуск фонового процесса восстановления"""
        
        if self.running:
            logger.warning("🔄 Сервис восстановления уже запущен")
            return
        
        self.running = True
        logger.warning("🔄 Запуск сервиса восстановления транзакций")
        
        try:
            while self.running:
                await self._recovery_cycle()
                await asyncio.sleep(self.check_interval)
        except Exception as e:
            logger.error(f"💥 Критическая ошибка в recovery service: {e}")
        finally:
            self.running = False
            logger.warning("🔄 Сервис восстановления остановлен")
    
    def stop_background_recovery(self):
        """Остановка фонового процесса"""
        logger.warning("🛑 Остановка сервиса восстановления")
        self.running = False
    
    async def _recovery_cycle(self):
        """Один цикл проверки и восстановления"""
        
        try:
            # Используем контекстный менеджер для сессии БД
            async with self._get_db_session() as db:
                
                # 1. Обрабатываем транзакции в состоянии PREPARED (слишком долго)
                await self._handle_stale_prepared_transactions(db)
                
                # 2. Обрабатываем транзакции в состоянии COMMITTING (повторяем commit)
                await self._handle_stale_committing_transactions(db)
                
                # 3. Обрабатываем транзакции в состоянии ABORTING (повторяем abort)
                await self._handle_stale_aborting_transactions(db)
                
                # 4. Обрабатываем транзакции в состоянии PREPARING (слишком долго)
                await self._handle_stale_preparing_transactions(db)
                
                # 5. Ищем "мертвые" транзакции без обновлений
                await self._handle_dead_transactions(db)
                
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле восстановления: {e}")
    
    @asynccontextmanager
    async def _get_db_session(self):
        """Асинхронный контекстный менеджер для сессии БД"""
        db = next(get_db())
        try:
            yield db
        finally:
            db.close()
    
    async def _handle_stale_prepared_transactions(self, db: Session):
        """Обработка транзакций, слишком долго находящихся в состоянии PREPARED"""
        
        cutoff_time = datetime.now() - timedelta(seconds=self.prepare_timeout)
        
        stale_transactions = db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.status == TransactionStatus.PREPARED,
                UnifiedPayment.prepare_completed_at < cutoff_time,
                or_(
                    UnifiedPayment.commit_started_at.is_(None),
                    UnifiedPayment.commit_started_at < cutoff_time
                )
            )
        ).all()
        
        for transaction in stale_transactions:
            logger.warning(f"🚨 Найдена зависшая PREPARED транзакция: {transaction.transaction_id}")
            
            # Проверяем количество попыток восстановления
            recovery_attempts = await self._get_recovery_attempts(db, transaction.payment_reference)
            
            if recovery_attempts >= self.max_recovery_attempts:
                logger.error(f"💀 Превышено максимальное количество попыток восстановления для {transaction.transaction_id}")
                await self._mark_transaction_for_manual_intervention(db, transaction)
                continue
            
            # Пытаемся отменить транзакцию, так как commit не был начат
            logger.info(f"🚫 Отмена зависшей PREPARED транзакции: {transaction.transaction_id}")
            
            try:
                # Извлекаем результаты подготовки
                prepare_results = []
                
                if transaction.sender_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    sender_data = json.loads(transaction.sender_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.sender_bank_code,
                        bank_role=BankRole.SENDER,
                        operation="prepare",
                        success=True,
                        response_data=sender_data
                    ))
                
                if transaction.receiver_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    receiver_data = json.loads(transaction.receiver_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.receiver_bank_code,
                        bank_role=BankRole.RECEIVER,
                        operation="prepare",
                        success=True,
                        response_data=receiver_data
                    ))
                
                # Выполняем отмену
                await two_phase_commit_service._execute_abort_phase(db, transaction, prepare_results)
                
                # Записываем событие восстановления
                TimelineService.record_event(
                    db,
                    payment_token=transaction.payment_reference,
                    event_type='recovery_abort',
                    title='Автоматическая отмена зависшей транзакции',
                    description=f'PREPARED -> ABORTED после таймаута {self.prepare_timeout}с',
                    actor='recovery_service',
                    source='background_recovery',
                    status='warning'
                )
                
                await self._increment_recovery_attempts(db, transaction.token)
                
            except Exception as e:
                logger.error(f"💥 Ошибка при отмене зависшей транзакции {transaction.transaction_id}: {e}")
                await self._increment_recovery_attempts(db, transaction.token)
    
    async def _handle_stale_committing_transactions(self, db: Session):
        """Обработка транзакций, зависших в состоянии COMMITTING"""
        
        cutoff_time = datetime.now() - timedelta(seconds=self.commit_timeout)
        
        stale_transactions = db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.status == TransactionStatus.COMMITTING,
                UnifiedPayment.commit_started_at < cutoff_time,
                or_(
                    UnifiedPayment.commit_completed_at.is_(None),
                    UnifiedPayment.commit_completed_at < cutoff_time
                )
            )
        ).all()
        
        for transaction in stale_transactions:
            logger.warning(f"🚨 Найдена зависшая COMMITTING транзакция: {transaction.transaction_id}")
            
            recovery_attempts = await self._get_recovery_attempts(db, transaction.payment_reference)
            
            if recovery_attempts >= self.max_recovery_attempts:
                logger.error(f"💀 Превышено максимальное количество попыток восстановления для {transaction.transaction_id}")
                await self._mark_transaction_for_manual_intervention(db, transaction)
                continue
            
            # Повторяем commit, так как средства уже зарезервированы
            logger.info(f"🔄 Повторная попытка commit для транзакции: {transaction.transaction_id}")
            
            try:
                # Извлекаем результаты подготовки для повторного commit
                prepare_results = []
                
                if transaction.sender_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    sender_data = json.loads(transaction.sender_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.sender_bank_code,
                        bank_role=BankRole.SENDER,
                        operation="prepare",
                        success=True,
                        response_data=sender_data
                    ))
                
                if transaction.receiver_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    receiver_data = json.loads(transaction.receiver_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.receiver_bank_code,
                        bank_role=BankRole.RECEIVER,
                        operation="prepare",
                        success=True,
                        response_data=receiver_data
                    ))
                
                # Повторяем commit
                commit_result = await two_phase_commit_service._execute_commit_phase(db, transaction, prepare_results)
                
                if commit_result["success"]:
                    # Успешно завершили
                    transaction.status = TransactionStatus.COMPLETED
                    transaction.commit_completed_at = datetime.now()
                    transaction.is_paid = True
                    transaction.paid_at = datetime.now()

                    # Находим сумму из результатов
                    for result in commit_result["results"]:
                        if result.bank_role.value == "sender" and result.response_data:
                            transaction.amount = result.response_data.get("actual_amount", transaction.amount)
                            break
                    
                    db.commit()
                    
                    TimelineService.record_event(
                        db,
                        payment_token=transaction.payment_reference,
                        event_type='recovery_commit_success',
                        title='Успешное восстановление commit транзакции',
                        description=f'COMMITTING -> COMPLETED после повторной попытки',
                        actor='recovery_service',
                        source='background_recovery',
                        status='success'
                    )
                    
                    logger.info(f"✅ Успешно восстановлен commit для транзакции: {transaction.transaction_id}")
                else:
                    # Commit снова не удался - оставляем в COMMITTING для ручного вмешательства
                    await self._mark_transaction_for_manual_intervention(db, transaction)
                    
                    TimelineService.record_event(
                        db,
                        payment_token=transaction.payment_reference,
                        event_type='recovery_commit_failed',
                        title='Неудачная попытка восстановления commit',
                        description=f'Требуется ручное вмешательство: {commit_result["error"]}',
                        actor='recovery_service',
                        source='background_recovery',
                        status='error'
                    )
                
                await self._increment_recovery_attempts(db, transaction.payment_reference)
                
            except Exception as e:
                logger.error(f"💥 Ошибка при повторном commit транзакции {transaction.transaction_id}: {e}")
                await self._increment_recovery_attempts(db, transaction.payment_reference)
    
    async def _handle_stale_aborting_transactions(self, db: Session):
        """Обработка транзакций, зависших в состоянии ABORTING"""
        
        cutoff_time = datetime.now() - timedelta(seconds=self.abort_timeout)
        
        stale_transactions = db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.status == TransactionStatus.ABORTING,
                UnifiedPayment.abort_started_at < cutoff_time,
                or_(
                    UnifiedPayment.abort_completed_at.is_(None),
                    UnifiedPayment.abort_completed_at < cutoff_time
                )
            )
        ).all()
        
        for transaction in stale_transactions:
            logger.warning(f"🚨 Найдена зависшая ABORTING транзакция: {transaction.transaction_id}")
            
            recovery_attempts = await self._get_recovery_attempts(db, transaction.payment_reference)
            
            if recovery_attempts >= self.max_recovery_attempts:
                # Принудительно завершаем отмену
                transaction.status = TransactionStatus.ABORTED
                transaction.abort_completed_at = datetime.now()
                db.commit()
                
                logger.warning(f"⚠️ Принудительно завершена отмена транзакции: {transaction.transaction_id}")
                continue
            
            # Повторяем abort
            logger.info(f"🔄 Повторная попытка abort для транзакции: {transaction.transaction_id}")
            
            try:
                # Извлекаем результаты подготовки для abort
                prepare_results = []
                
                if transaction.sender_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    sender_data = json.loads(transaction.sender_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.sender_bank_code,
                        bank_role=BankRole.SENDER,
                        operation="prepare",
                        success=True,
                        response_data=sender_data
                    ))
                
                if transaction.receiver_prepare_result:
                    from app.schemas.bank import BankOperationResult, BankRole
                    receiver_data = json.loads(transaction.receiver_prepare_result)
                    prepare_results.append(BankOperationResult(
                        bank_code=transaction.receiver_bank_code,
                        bank_role=BankRole.RECEIVER,
                        operation="prepare",
                        success=True,
                        response_data=receiver_data
                    ))
                
                # Повторяем abort
                await two_phase_commit_service._execute_abort_phase(db, transaction, prepare_results)
                
                TimelineService.record_event(
                    db,
                    payment_token=transaction.payment_reference,
                    event_type='recovery_abort_completed',
                    title='Успешно завершена отмена транзакции',
                    description=f'ABORTING -> ABORTED после повторной попытки',
                    actor='recovery_service',
                    source='background_recovery',
                    status='info'
                )
                
                logger.info(f"✅ Успешно завершена отмена транзакции: {transaction.transaction_id}")
                
                await self._increment_recovery_attempts(db, transaction.payment_reference)
                
            except Exception as e:
                logger.error(f"💥 Ошибка при повторной отмене транзакции {transaction.transaction_id}: {e}")
                await self._increment_recovery_attempts(db, transaction.payment_reference)
    
    async def _handle_stale_preparing_transactions(self, db: Session):
        """Обработка транзакций, слишком долго находящихся в состоянии PREPARING"""
        
        cutoff_time = datetime.now() - timedelta(seconds=self.prepare_timeout * 2)  # Двойной таймаут для PREPARING
        
        stale_transactions = db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.status == TransactionStatus.PREPARING,
                UnifiedPayment.prepare_started_at < cutoff_time
            )
        ).all()
        
        for transaction in stale_transactions:
            logger.warning(f"🚨 Найдена зависшая PREPARING транзакция: {transaction.transaction_id}")
            
            # Принудительно отменяем такие транзакции
            transaction.status = TransactionStatus.ABORTED
            transaction.abort_started_at = datetime.now()
            transaction.abort_completed_at = datetime.now()
            db.commit()
            
            TimelineService.record_event(
                db,
                payment_token=transaction.payment_reference,
                event_type='recovery_force_abort',
                title='Принудительная отмена зависшей подготовки',
                description=f'PREPARING -> ABORTED после таймаута {self.prepare_timeout * 2}с',
                actor='recovery_service',
                source='background_recovery',
                status='warning'
            )
            
            logger.info(f"🚫 Принудительно отменена зависшая подготовка: {transaction.transaction_id}")
    
    async def _handle_dead_transactions(self, db: Session):
        """Обработка "мертвых" транзакций без активности"""
        
        cutoff_time = datetime.now() - timedelta(hours=24)  # 24 часа без изменений
        
        dead_transactions = db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.status.in_([
                    TransactionStatus.PREPARING,
                    TransactionStatus.PREPARED,
                    TransactionStatus.COMMITTING,
                    TransactionStatus.ABORTING
                ]),
                UnifiedPayment.created_at < cutoff_time
            )
        ).all()
        
        for transaction in dead_transactions:
            logger.error(f"💀 Найдена мертвая транзакция: {transaction.transaction_id} (статус: {transaction.status.value})")
            
            # Помечаем для ручного вмешательства
            await self._mark_transaction_for_manual_intervention(db, transaction)
    
    async def _get_recovery_attempts(self, db: Session, payment_token: str) -> int:
        """Получение количества попыток восстановления"""
        
        count = db.query(TwoPhaseOperation).filter(
            and_(
                TwoPhaseOperation.payment_token == payment_token,
                TwoPhaseOperation.operation_type == "recovery"
            )
        ).count()
        
        return count
    
    async def _increment_recovery_attempts(self, db: Session, payment_token: str):
        """Увеличение счетчика попыток восстановления"""
        
        recovery_log = TwoPhaseOperation(
            payment_token=payment_token,
            transaction_id="",  # Для recovery операций
            phase="recovery",
            operation_type="recovery",
            bank_code="system",
            bank_role="recovery",
            request_data=json.dumps({"recovery_attempt": True}),
            started_at=datetime.now(),
            completed_at=datetime.now(),
            response_status="attempted"
        )
        
        db.add(recovery_log)
        db.commit()
    
    async def _mark_transaction_for_manual_intervention(self, db: Session, transaction: UnifiedPayment):
        """Помечаем транзакцию для ручного вмешательства"""
        
        # Обновляем метаданные
        metadata = {}
        if transaction.two_phase_metadata:
            metadata = json.loads(transaction.two_phase_metadata)
        
        metadata.update({
            "requires_manual_intervention": True,
            "marked_at": datetime.now().isoformat(),
            "reason": "Recovery attempts exceeded or dead transaction"
        })
        
        transaction.two_phase_metadata = json.dumps(metadata)
        db.commit()
        
        TimelineService.record_event(
            db,
            payment_token=transaction.payment_reference,
            event_type='manual_intervention_required',
            title='Требуется ручное вмешательство',
            description=f'Транзакция {transaction.transaction_id} помечена для ручного разбора',
            actor='recovery_service',
            source='background_recovery',
            status='error'
        )
        
        logger.error(f"🚨 Транзакция {transaction.transaction_id} помечена для ручного вмешательства")

# Глобальный экземпляр сервиса
two_phase_recovery_service = TwoPhaseRecoveryService()
