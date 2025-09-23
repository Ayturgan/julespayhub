"""
Сервис для управления двухфазными возвратами (Two-Phase Refund Protocol)
Основан на TwoPhaseCommitService, но адаптирован для обратных транзакций
"""

from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
import logging
import json
import asyncio
import aiohttp
from contextlib import asynccontextmanager

from app.models.unified import UnifiedPayment
from app.models.payment import TransactionStatus, TwoPhaseOperation, Bank
from app.models.refund import RefundRequest, RefundOperation, RefundStatus, RefundType
from app.models.merchant import Merchant
from app.schemas.bank import (
    TransactionPrepareRequest, TransactionPrepareResponse,
    TransactionCommitRequest, TransactionCommitResponse,
    TransactionAbortRequest, TransactionAbortResponse,
    BankRole, TwoPhaseOperationStatus, BankOperationResult
)
from app.schemas.refund import (
    RefundPrepareRequest, RefundPrepareResponse,
    RefundCommitRequest, RefundCommitResponse,
    RefundAbortRequest, RefundAbortResponse,
    RefundOperationResult, RefundValidationResult
)
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity
from app.services.timeline_service import TimelineService
from app.services.bank_adapter_service import bank_adapter_service
from app.services.token_service import SecureTokenService

logger = logging.getLogger(__name__)

class TwoPhaseRefundService:
    """Оркестратор двухфазных возвратов"""
    
    def __init__(self):
        self.default_timeout = 300  # 5 минут по умолчанию
        self.max_retries = 3
        self.retry_delay = 5  # секунд
        
    async def start_refund_process(self, db: Session, refund_id: int) -> Dict[str, Any]:
        """
        Запускает автоматический двухфазный процесс возврата
        
        Args:
            db: Сессия базы данных
            refund_id: ID запроса на возврат
            
        Returns:
            Результат запуска процесса
        """
        try:
            # Получаем запрос на возврат
            refund_request = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
            if not refund_request:
                return {
                    "success": False,
                    "error": f"Запрос на возврат {refund_id} не найден"
                }
            
            # Получаем оригинальный платеж
            original_payment = db.query(UnifiedPayment).filter(
                UnifiedPayment.id == refund_request.original_payment_id
            ).first()
            if not original_payment:
                return {
                    "success": False,
                    "error": f"Оригинальный платеж {refund_request.original_payment_id} не найден"
                }
            
            # Проверяем, что возврат еще не выполняется
            if refund_request.status not in [RefundStatus.PENDING]:
                return {
                    "success": False,
                    "error": f"Возврат {refund_id} уже в процессе выполнения (статус: {refund_request.status.value})"
                }
            
            logger.info(f"🚀 Запуск автоматического двухфазного процесса возврата {refund_id}")
            
            # Запускаем двухфазный процесс в фоновом режиме
            asyncio.create_task(self._execute_refund_background(refund_request.id, original_payment.id))
            
            return {
                "success": True,
                "message": f"Двухфазный процесс возврата {refund_id} запущен",
                "refund_id": refund_id,
                "status": "started"
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка запуска двухфазного процесса возврата {refund_id}: {e}")
            return {
                "success": False,
                "error": f"Ошибка запуска процесса: {str(e)}"
            }
    
    async def _execute_refund_background(self, refund_id: int, original_payment_id: int):
        """
        Выполняет двухфазный процесс возврата в фоновом режиме
        """
        from app.database import get_db
        
        try:
            # Создаем новую сессию для фонового процесса
            new_db = next(get_db())
            try:
                # Получаем свежие объекты из новой сессии
                fresh_refund_request = new_db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
                fresh_original_payment = new_db.query(UnifiedPayment).filter(UnifiedPayment.id == original_payment_id).first()
                
                if not fresh_refund_request or not fresh_original_payment:
                    logger.error(f"❌ Не удалось найти объекты в новой сессии для возврата {refund_id}")
                    return
                
                result = await self.execute_refund(new_db, fresh_refund_request, fresh_original_payment)
                logger.info(f"✅ Двухфазный процесс возврата {refund_id} завершен: {result}")
            finally:
                new_db.close()
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения двухфазного процесса возврата {refund_id}: {e}")
            # Обновляем статус на FAILED в новой сессии
            try:
                new_db = next(get_db())
                try:
                    failed_refund = new_db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
                    if failed_refund:
                        failed_refund.status = RefundStatus.FAILED
                        new_db.commit()
                        logger.info(f"✅ Статус возврата {refund_id} обновлен на FAILED")
                finally:
                    new_db.close()
            except Exception as commit_error:
                logger.error(f"❌ Не удалось обновить статус возврата {refund_id}: {commit_error}")
        
    async def execute_refund(
        self, 
        db: Session, 
        refund_request: RefundRequest,
        original_payment: UnifiedPayment
    ) -> Dict[str, Any]:
        """
        Основной метод выполнения двухфазного возврата
        
        Args:
            db: Сессия базы данных
            refund_request: Запрос на возврат
            original_payment: Оригинальный платеж
            
        Returns:
            Результат выполнения возврата
        """
        
        # Генерируем уникальный ID транзакции возврата
        transaction_id = f"REFUND_{refund_request.refund_token}_{int(datetime.now().timestamp())}"
        
        logger.info(f"🔄 Начало двухфазного возврата {transaction_id}")
        
        try:
            # Валидируем возможность возврата
            validation_result = self._validate_refund_request(db, refund_request, original_payment)
            if not validation_result.valid:
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "validation_failed",
                    "error": "Ошибка валидации возврата",
                    "validation_errors": [err.dict() for err in validation_result.errors]
                }
            
            # Обновляем статус и сохраняем данные
            refund_request.status = RefundStatus.PREPARING
            refund_request.transaction_id = transaction_id
            
            # Определяем банки для возврата (обратные роли)
            # Получаем банковскую информацию продавца
            merchant = db.query(Merchant).filter(Merchant.id == original_payment.merchant_id).first()
            if not merchant:
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "validation_failed",
                    "error": "Продавец не найден"
                }
            
            # Определяем банки для возврата (обратные роли)
            # Банк отправителя = банк продавца (который возвращает средства)
            # Банк получателя = банк покупателя (который получает средства обратно)
            
            # Получаем банк продавца из профиля
            sender_bank_code = "DEMO"  # По умолчанию
            if merchant and merchant.bank_name:
                # Ищем банк по названию из профиля продавца
                seller_bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
                if seller_bank:
                    sender_bank_code = seller_bank.code
            
            # Банк получателя = банк покупателя из оригинального платежа
            receiver_bank_code = original_payment.payer_bank_code if original_payment.payer_bank_code else "DEMO"
            
            # Устанавливаем банковские коды
            refund_request.sender_bank_code = sender_bank_code
            refund_request.receiver_bank_code = receiver_bank_code
            refund_request.prepare_started_at = datetime.now()
            
            # Сохраняем изменения в базе данных
            db.commit()
            
            # Сохраняем метаданные
            metadata = {
                "original_payment_id": original_payment.id,
                "original_amount": original_payment.amount,
                "refund_amount": refund_request.amount,
                "refund_type": refund_request.refund_type.value,
                "reason": refund_request.reason,
                "sender_bank_code": sender_bank_code,
                "receiver_bank_code": receiver_bank_code,
                "started_at": datetime.now().isoformat(),
                "timeout_seconds": self.default_timeout
            }
            refund_request.two_phase_metadata = json.dumps(metadata, default=str)
            
            db.commit()
            
            # Запись в таймлайн
            TimelineService.record_event(
                db,
                payment_token=refund_request.refund_token,
                event_type='refund_two_phase_started',
                title='Начата двухфазная транзакция возврата',
                description=f'ID: {transaction_id}, сумма: {refund_request.amount} {refund_request.currency}',
                actor='system',
                source='two_phase_refund',
                status='info'
            )
            
            # Фаза 1: Подготовка возврата (Prepare)
            prepare_result = await self._execute_refund_prepare_phase(
                db, refund_request, original_payment
            )
            
            if not prepare_result["success"]:
                # Подготовка не удалась - переходим к отмене
                logger.warning(f"❌ Подготовка возврата {transaction_id} не удалась: {prepare_result['error']}")
                
                abort_result = await self._execute_refund_abort_phase(
                    db, refund_request, prepare_result.get("partial_results", [])
                )
                
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "aborted",
                    "error": prepare_result["error"],
                    "prepare_results": prepare_result.get("results", []),
                    "abort_results": abort_result.get("results", [])
                }
            
            # Обновляем статус на PREPARED
            refund_request.status = RefundStatus.PREPARED
            refund_request.prepare_completed_at = datetime.now()
            
            # Запись в таймлайн о завершении подготовки
            TimelineService.record_event(
                db,
                payment_token=refund_request.refund_token,
                event_type='refund_two_phase_prepared',
                title='Подготовка возврата завершена',
                description=f'Банки готовы к выполнению возврата {transaction_id}',
                actor='system',
                source='two_phase_refund',
                status='success'
            )
            
            # Сохраняем результаты подготовки
            sender_result = next((r for r in prepare_result["results"] if r.bank_role == BankRole.SENDER), None)
            receiver_result = next((r for r in prepare_result["results"] if r.bank_role == BankRole.RECEIVER), None)
            
            if sender_result and sender_result.response_data:
                refund_request.sender_prepare_result = json.dumps(sender_result.response_data, default=str)
            if receiver_result and receiver_result.response_data:
                refund_request.receiver_prepare_result = json.dumps(receiver_result.response_data, default=str)
            
            db.commit()
            
            logger.info(f"✅ Подготовка возврата {transaction_id} завершена успешно")
            
            # Фаза 2: Выполнение возврата (Commit)
            commit_result = await self._execute_refund_commit_phase(
                db, refund_request, prepare_result["results"]
            )
            
            if commit_result["success"]:
                # Возврат завершен успешно
                refund_request.status = RefundStatus.COMPLETED
                refund_request.commit_completed_at = datetime.now()
                refund_request.completed_at = datetime.now()
                
                # Обновляем оригинальный платеж
                self._update_original_payment_refund_status(db, original_payment, refund_request)
                
                # Запись в таймлайн о завершении возврата
                TimelineService.record_event(
                    db,
                    payment_token=refund_request.refund_token,
                    event_type='refund_two_phase_completed',
                    title='Возврат завершен успешно',
                    description=f'Возврат {refund_request.amount} {refund_request.currency} успешно обработан',
                    actor='system',
                    source='two_phase_refund',
                    status='success'
                )
                
                db.commit()
                
                logger.info(f"🎉 Возврат {transaction_id} завершен успешно")
                
                return {
                    "success": True,
                    "transaction_id": transaction_id,
                    "status": "completed",
                    "amount": refund_request.amount,
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result["results"]
                }
            else:
                # Commit не удался - это критическая ситуация
                # Средства зарезервированы, но возврат не выполнен
                logger.error(f"💥 Критическая ошибка: Commit возврата {transaction_id} не удался")
                
                refund_request.status = RefundStatus.FAILED
                refund_request.commit_completed_at = datetime.now()
                
                # Запись в таймлайн о критической ошибке
                TimelineService.record_event(
                    db,
                    payment_token=refund_request.refund_token,
                    event_type='refund_two_phase_failed',
                    title='Критическая ошибка возврата',
                    description=f'Средства зарезервированы, но возврат не выполнен: {commit_result["error"]}',
                    actor='system',
                    source='two_phase_refund',
                    status='error'
                )
                
                db.commit()
                
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "failed",
                    "error": commit_result["error"],
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result["results"],
                    "requires_manual_intervention": True
                }
                
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка при выполнении возврата {transaction_id}: {e}")
            
            refund_request.status = RefundStatus.FAILED
            refund_request.completed_at = datetime.now()
            
            # Запись в таймлайн об ошибке
            TimelineService.record_event(
                db,
                payment_token=refund_request.refund_token,
                event_type='refund_two_phase_error',
                title='Ошибка выполнения возврата',
                description=f'Неожиданная ошибка: {str(e)}',
                actor='system',
                source='two_phase_refund',
                status='error'
            )
            
            db.commit()
            
            return {
                "success": False,
                "transaction_id": transaction_id,
                "status": "failed",
                "error": str(e),
                "requires_manual_intervention": True
            }
    
    def _validate_refund_request(
        self, 
        db: Session,
        refund_request: RefundRequest, 
        original_payment: UnifiedPayment
    ) -> RefundValidationResult:
        """Валидация запроса на возврат"""
        
        validation = RefundValidationResult(valid=True)
        
        # Проверяем статус оригинального платежа
        if original_payment.status.value.lower() != "completed":
            validation.add_error(
                "original_payment_status", 
                "Возврат возможен только для завершенных платежей",
                "invalid_payment_status"
            )
        
        # Проверяем сумму возврата
        if refund_request.amount <= 0:
            validation.add_error(
                "amount", 
                "Сумма возврата должна быть больше нуля",
                "invalid_amount"
            )
        
        if refund_request.amount > original_payment.amount:
            validation.add_error(
                "amount", 
                "Сумма возврата не может превышать сумму оригинального платежа",
                "amount_exceeds_original"
            )
        
        # Проверяем уже возвращенные суммы
        existing_refunds = db.query(RefundRequest).filter(
            and_(
                RefundRequest.original_payment_id == original_payment.id,
                RefundRequest.status == RefundStatus.COMPLETED
            )
        ).all()
        
        total_refunded = sum(refund.amount for refund in existing_refunds)
        remaining_amount = original_payment.amount - total_refunded
        
        if refund_request.amount > remaining_amount:
            validation.add_error(
                "amount", 
                f"Сумма возврата превышает доступную для возврата сумму ({remaining_amount})",
                "amount_exceeds_remaining"
            )
        
        # Проверяем банковские коды
        # Проверяем, что у платежа есть банковская информация
        if not original_payment.payer_bank_code:
            validation.add_error(
                "payer_bank_code", 
                "Банк покупателя не указан в оригинальном платеже",
                "missing_payer_bank"
            )
        
        if not original_payment.payer_bank_code:
            validation.add_error(
                "payer_bank_code", 
                "Банк покупателя не указан в оригинальном платеже",
                "missing_payer_bank"
            )
        
        return validation
    
    async def _execute_refund_prepare_phase(
        self, 
        db: Session, 
        refund_request: RefundRequest,
        original_payment: UnifiedPayment
    ) -> Dict[str, Any]:
        """Выполнение фазы подготовки возврата"""
        
        logger.info(f"💳 Начало фазы prepare возврата для {refund_request.transaction_id}")
        
        # Получаем банки
        logger.error(f"🔍 Поиск банка отправителя по коду: {refund_request.sender_bank_code}")
        logger.error(f"🔍 Поиск банка получателя по коду: {refund_request.receiver_bank_code}")
        
        sender_bank = db.query(Bank).filter(Bank.code == refund_request.sender_bank_code).first()
        receiver_bank = db.query(Bank).filter(Bank.code == refund_request.receiver_bank_code).first()
        
        if not sender_bank:
            logger.error(f"❌ Банк отправителя не найден: {refund_request.sender_bank_code}")
        if not receiver_bank:
            logger.error(f"❌ Банк получателя не найден: {refund_request.receiver_bank_code}")
        
        if not sender_bank or not receiver_bank:
            # Показываем все доступные банки для отладки
            all_banks = db.query(Bank).all()
            bank_codes = [bank.code for bank in all_banks]
            logger.error(f"🔍 Доступные банки в системе: {bank_codes}")
            
            return {
                "success": False,
                "error": "Банки не найдены в системе"
            }
        
        # Базовые данные для запросов
        base_request_data = {
            "transaction_id": refund_request.transaction_id,
            "refund_token": refund_request.refund_token,
            "original_payment_id": original_payment.id,
            "reason": refund_request.reason,
            "amount": refund_request.amount,
            "currency": refund_request.currency,
            "timeout_seconds": self.default_timeout,
            "metadata": {
                "operation_type": "refund",
                "original_payment_id": original_payment.id,
                "reason": refund_request.reason,
                "refund_type": refund_request.refund_type.value
            }
        }
        
        # Получаем информацию о продавце для банковских данных
        merchant = db.query(Merchant).filter(Merchant.id == original_payment.merchant_id).first()
        
        # Запрос для банка отправителя (продавца) - возвращает средства
        sender_request = RefundPrepareRequest(
            **base_request_data,
            bank_role=BankRole.SENDER,
            sender_account=merchant.bank_account if merchant else "DEMO_ACCOUNT",
            sender_phone=merchant.phone if merchant else "DEMO_PHONE",
            # Получатель - покупатель (данные из original_payment)
            receiver_account=original_payment.sender_account,
            receiver_phone=original_payment.payer_phone
        )
        
        # Запрос для банка получателя (покупателя) - получает средства
        receiver_request = RefundPrepareRequest(
            **base_request_data,
            bank_role=BankRole.RECEIVER,
            # Отправитель - продавец (данные из merchant)
            sender_account=merchant.bank_account if merchant else "DEMO_ACCOUNT",
            sender_phone=merchant.phone if merchant else "DEMO_PHONE",
            # Получатель - покупатель (данные из original_payment)
            receiver_account=original_payment.sender_account,
            receiver_phone=original_payment.payer_phone
        )
        
        # Создаем запросы для симулятора банков (только для демонстрации)
        # В реальной системе эти запросы создавались бы через API банков
        try:
            from simulation.simulation_router import add_bank_request
            
            # Запрос для банка отправителя (продавца)
            sender_bank_request = {
                "transaction_id": refund_request.transaction_id,
                "phase": "refund_prepare",  # Исправляем phase
                "operation_type": "refund",
                "amount": refund_request.amount,
                "currency": refund_request.currency,
                "sender_account": sender_request.sender_account,
                "sender_phone": sender_request.sender_phone,
                "receiver_account": sender_request.receiver_account,
                "receiver_phone": sender_request.receiver_phone,
                "bank_role": "sender",
                "refund_token": refund_request.refund_token,
                "original_payment_id": original_payment.id,
                "reason": refund_request.reason
            }
            add_bank_request("sender_bank", sender_bank_request)
            
            # Запрос для банка получателя (покупателя)
            receiver_bank_request = {
                "transaction_id": refund_request.transaction_id,
                "phase": "refund_prepare",  # Исправляем phase
                "operation_type": "refund",
                "amount": refund_request.amount,
                "currency": refund_request.currency,
                "sender_account": receiver_request.sender_account,
                "sender_phone": receiver_request.sender_phone,
                "receiver_account": receiver_request.receiver_account,
                "receiver_phone": receiver_request.receiver_phone,
                "bank_role": "receiver",
                "refund_token": refund_request.refund_token,
                "original_payment_id": original_payment.id,
                "reason": refund_request.reason
            }
            add_bank_request("receiver_bank", receiver_bank_request)
            
        except ImportError:
            # Если импорт не удался, просто логируем
            logger.info(f"📝 Симулятор банков недоступен, пропускаем создание демо-запросов")
        
        # Отправляем запросы параллельно
        tasks = [
            self._send_refund_prepare_request(db, sender_bank, sender_request),
            self._send_refund_prepare_request(db, receiver_bank, receiver_request)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful_results = []
        partial_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = refund_request.sender_bank_code if i == 0 else refund_request.receiver_bank_code
                logger.error(f"❌ Ошибка при отправке prepare возврата к банку {bank_code}: {result}")
                
                error_result = RefundOperationResult(
                    bank_code=bank_code,
                    bank_role=BankRole.SENDER if i == 0 else BankRole.RECEIVER,
                    operation="prepare",
                    success=False,
                    error_message=str(result)
                )
                partial_results.append(error_result)
            else:
                partial_results.append(result)
                
                if result.success and result.response_status == TwoPhaseOperationStatus.PREPARED:
                    successful_results.append(result)
        
        # Проверяем успешность фазы подготовки
        if len(successful_results) == 2:
            logger.info(f"✅ Фаза подготовки возврата завершена успешно для {refund_request.transaction_id}")
            return {
                "success": True,
                "results": successful_results
            }
        else:
            failed_banks = [r.bank_code for r in partial_results if not r.success]
            logger.warning(f"❌ Фаза подготовки возврата не удалась. Неуспешные банки: {failed_banks}")
            
            return {
                "success": False,
                "error": f"Подготовка возврата не удалась для банков: {', '.join(failed_banks)}",
                "results": partial_results,
                "partial_results": [r for r in partial_results if r.success]
            }
    
    async def _execute_refund_commit_phase(
        self, 
        db: Session, 
        refund_request: RefundRequest,
        prepare_results: List[RefundOperationResult]
    ) -> Dict[str, Any]:
        """Выполнение фазы фиксации возврата (commit)"""
        
        logger.info(f"💳 Начало фазы commit возврата для {refund_request.transaction_id}")
        
        refund_request.status = RefundStatus.COMMITTING
        refund_request.commit_started_at = datetime.now()
        db.commit()
        
        # Готовим запросы commit для каждого банка
        commit_tasks = []
        
        for prepare_result in prepare_results:
            # Получаем банк
            bank = db.query(Bank).filter(Bank.code == prepare_result.bank_code).first()
            if not bank:
                continue
            
            # Извлекаем данные из результата подготовки
            prepared_amount = refund_request.amount
            reservation_id = None
            
            if prepare_result.response_data:
                prepared_amount = prepare_result.response_data.get("reserved_amount", refund_request.amount)
                reservation_id = prepare_result.response_data.get("reservation_id")
            
            # Создаем запрос commit
            commit_request = RefundCommitRequest(
                transaction_id=refund_request.transaction_id,
                refund_token=refund_request.refund_token,
                original_payment_id=refund_request.original_payment_id,
                prepared_amount=prepared_amount,
                reservation_id=reservation_id,
                bank_role=prepare_result.bank_role
            )
            
            commit_tasks.append(
                self._send_refund_commit_request(db, bank, commit_request)
            )
        
        # Выполняем commit параллельно
        results = await asyncio.gather(*commit_tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful_results = []
        failed_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = prepare_results[i].bank_code
                logger.error(f"❌ Ошибка при отправке commit возврата к банку {bank_code}: {result}")
                
                error_result = RefundOperationResult(
                    bank_code=bank_code,
                    bank_role=prepare_results[i].bank_role,
                    operation="commit",
                    success=False,
                    error_message=str(result)
                )
                failed_results.append(error_result)
            else:
                if result.success and result.response_status == TwoPhaseOperationStatus.COMMITTED:
                    successful_results.append(result)
                else:
                    failed_results.append(result)
        
        # Проверяем успешность фазы фиксации
        if len(successful_results) == 2:
            logger.info(f"✅ Фаза фиксации возврата завершена успешно для {refund_request.transaction_id}")
            
            # Обновляем статус на COMPLETED
            refund_request.status = RefundStatus.COMPLETED
            refund_request.commit_completed_at = datetime.now()
            db.commit()
            
            return {
                "success": True,
                "results": successful_results
            }
        else:
            failed_banks = [r.bank_code for r in failed_results]
            logger.error(f"❌ Фаза фиксации возврата не удалась. Неуспешные банки: {failed_banks}")
            
            return {
                "success": False,
                "error": f"Фиксация возврата не удалась для банков: {', '.join(failed_banks)}",
                "results": failed_results,
                "partial_results": successful_results
            }
    
    async def _execute_refund_abort_phase(
        self, 
        db: Session, 
        refund_request: RefundRequest,
        partial_results: List[RefundOperationResult]
    ) -> Dict[str, Any]:
        """Выполнение фазы отмены возврата (abort)"""
        
        logger.info(f"🔄 Начало фазы abort возврата для {refund_request.transaction_id}")
        
        refund_request.status = RefundStatus.ABORTING
        refund_request.abort_started_at = datetime.now()
        db.commit()
        
        # Готовим запросы abort для каждого банка, который успешно подготовился
        abort_tasks = []
        
        for partial_result in partial_results:
            if partial_result.success and partial_result.response_status == TwoPhaseOperationStatus.PREPARED:
                # Получаем банк
                bank = db.query(Bank).filter(Bank.code == partial_result.bank_code).first()
                if not bank:
                    continue
                
                # Извлекаем reservation_id из результата подготовки
                reservation_id = None
                if partial_result.response_data:
                    reservation_id = partial_result.response_data.get("reservation_id")
                
                # Создаем запрос abort
                abort_request = RefundAbortRequest(
                    transaction_id=refund_request.transaction_id,
                    refund_token=refund_request.refund_token,
                    original_payment_id=refund_request.original_payment_id,
                    reservation_id=reservation_id,
                    bank_role=partial_result.bank_role,
                    abort_reason="Подготовка возврата не удалась для всех банков"
                )
                
                abort_tasks.append(
                    self._send_refund_abort_request(db, bank, abort_request)
                )
        
        if not abort_tasks:
            logger.info(f"ℹ️ Нет банков для отмены возврата {refund_request.transaction_id}")
            refund_request.status = RefundStatus.ABORTED
            refund_request.abort_completed_at = datetime.now()
            db.commit()
            
            return {
                "success": True,
                "results": []
            }
        
        # Выполняем abort параллельно
        results = await asyncio.gather(*abort_tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful_results = []
        failed_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = partial_results[i].bank_code
                logger.error(f"❌ Ошибка при отправке abort возврата к банку {bank_code}: {result}")
                
                error_result = RefundOperationResult(
                    bank_code=bank_code,
                    bank_role=partial_results[i].bank_role,
                    operation="abort",
                    success=False,
                    error_message=str(result)
                )
                failed_results.append(error_result)
            else:
                if result.success:
                    successful_results.append(result)
                else:
                    failed_results.append(result)
        
        # Обновляем статус
        if len(failed_results) == 0:
            refund_request.status = RefundStatus.ABORTED
            logger.info(f"✅ Фаза отмены возврата завершена успешно для {refund_request.transaction_id}")
        else:
            refund_request.status = RefundStatus.FAILED
            logger.error(f"❌ Фаза отмены возврата завершилась с ошибками для {refund_request.transaction_id}")
        
        refund_request.abort_completed_at = datetime.now()
        db.commit()
        
        return {
            "success": len(failed_results) == 0,
            "results": successful_results,
            "failed_results": failed_results
        }
    
    async def _send_refund_prepare_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: RefundPrepareRequest
    ) -> RefundOperationResult:
        """Отправка запроса подготовки возврата к банку"""
        
        start_time = datetime.now()
        
        try:
            # Получаем адаптер банка
            adapter = bank_adapter_service.get_adapter(bank.code)
            if not adapter:
                raise Exception(f"Адаптер для банка {bank.code} не найден")
            
            # Специальная обработка для симулятора - устанавливаем правильный base_url
            if hasattr(adapter, 'config') and adapter.config:
                # Для симулятора используем localhost для избежания проблем с сетью
                if "simulation" in str(bank.webhook_url or ""):
                    adapter.config.base_url = "http://localhost:8000/simulation/bank-api"
                    logger.info(f"🔄 Симулятор возврат: используем внутренний URL {adapter.config.base_url}")
            
            # Отправляем запрос
            response = await adapter.prepare_refund(request)
            
            # Логируем операцию
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="prepare",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                response_data=json.dumps(response.dict(), default=str) if response else None,
                response_status=response.status if response else None,
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            # Возвращаем результат
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="prepare",
                success=response.status == TwoPhaseOperationStatus.PREPARED if response else False,
                response_status=response.status if response else None,
                response_data=response.dict() if response else None,  # Pydantic автоматически сериализует datetime
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке prepare возврата к банку {bank.code}: {e}")
            
            # Логируем ошибку
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="prepare",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                error_message=str(e),
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="prepare",
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
    
    async def _send_refund_commit_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: RefundCommitRequest
    ) -> RefundOperationResult:
        """Отправка запроса фиксации возврата к банку"""
        
        start_time = datetime.now()
        
        try:
            # Получаем адаптер банка
            adapter = bank_adapter_service.get_adapter(bank.code)
            if not adapter:
                raise Exception(f"Адаптер для банка {bank.code} не найден")
            
            # Специальная обработка для симулятора - устанавливаем правильный base_url
            if hasattr(adapter, 'config') and adapter.config:
                # Для симулятора используем localhost для избежания проблем с сетью
                if "simulation" in str(bank.webhook_url or ""):
                    adapter.config.base_url = "http://localhost:8000/simulation/bank-api"
                    logger.info(f"🔄 Симулятор возврат commit: используем внутренний URL {adapter.config.base_url}")
            
            # Отправляем запрос
            response = await adapter.commit_refund(request)
            
            # Логируем операцию
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="commit",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                response_data=json.dumps(response.dict(), default=str) if response else None,
                response_status=response.status if response else None,
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            # Возвращаем результат
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="commit",
                success=response.status == TwoPhaseOperationStatus.COMMITTED if response else False,
                response_status=response.status if response else None,
                response_data=response.dict() if response else None,  # Pydantic автоматически сериализует datetime
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке commit возврата к банку {bank.code}: {e}")
            
            # Логируем ошибку
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="commit",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                error_message=str(e),
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="commit",
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
    
    async def _send_refund_abort_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: RefundAbortRequest
    ) -> RefundOperationResult:
        """Отправка запроса отмены возврата к банку"""
        
        start_time = datetime.now()
        
        try:
            # Получаем адаптер банка
            adapter = bank_adapter_service.get_adapter(bank.code)
            if not adapter:
                raise Exception(f"Адаптер для банка {bank.code} не найден")
            
            # Специальная обработка для симулятора - устанавливаем правильный base_url
            if hasattr(adapter, 'config') and adapter.config:
                # Для симулятора используем localhost для избежания проблем с сетью
                if "simulation" in str(bank.webhook_url or ""):
                    adapter.config.base_url = "http://localhost:8000/simulation/bank-api"
                    logger.info(f"🔄 Симулятор возврат abort: используем внутренний URL {adapter.config.base_url}")
            
            # Отправляем запрос
            response = await adapter.abort_refund(request)
            
            # Логируем операцию
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="abort",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                response_data=json.dumps(response.dict(), default=str) if response else None,
                response_status=response.status if response else None,
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            # Возвращаем результат
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="abort",
                success=response.status == TwoPhaseOperationStatus.ABORTED if response else False,
                response_status=response.status if response else None,
                response_data=response.dict() if response else None,  # Pydantic автоматически сериализует datetime
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке abort возврата к банку {bank.code}: {e}")
            
            # Логируем ошибку
            operation = RefundOperation(
                refund_token=request.refund_token,
                transaction_id=request.transaction_id,
                phase="abort",
                operation_type="request",
                bank_code=bank.code,
                bank_role=request.bank_role,
                request_data=json.dumps(request.dict(), default=str),
                error_message=str(e),
                started_at=start_time,
                completed_at=datetime.now(),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
            db.add(operation)
            db.commit()
            
            return RefundOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="abort",
                success=False,
                error_message=str(e),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
    
    def _update_original_payment_refund_status(
        self, 
        db: Session, 
        original_payment: UnifiedPayment,
        refund_request: RefundRequest
    ):
        """Обновление статуса возврата в оригинальном платеже"""
        
        # Получаем все завершенные возвраты для этого платежа
        completed_refunds = db.query(RefundRequest).filter(
            and_(
                RefundRequest.original_payment_id == original_payment.id,
                RefundRequest.status == RefundStatus.COMPLETED
            )
        ).all()
        
        total_refunded = sum(refund.amount for refund in completed_refunds)
        
        # Обновляем поля
        original_payment.total_refunded_amount = total_refunded
        
        if total_refunded >= original_payment.amount:
            original_payment.refund_status = "FULL"
        elif total_refunded > 0:
            original_payment.refund_status = "PARTIAL"
        else:
            original_payment.refund_status = "NONE"
        
        db.commit()

# Создаем глобальный экземпляр сервиса
two_phase_refund_service = TwoPhaseRefundService()
