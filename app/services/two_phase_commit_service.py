"""
Сервис для управления двухфазными транзакциями (Two-Phase Commit Protocol)
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

from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.enums import TransactionStatus
from app.models.payment import TwoPhaseOperation, Bank
from app.schemas.bank import (
    TransactionPrepareRequest, TransactionPrepareResponse,
    TransactionCommitRequest, TransactionCommitResponse,
    TransactionAbortRequest, TransactionAbortResponse,
    BankRole, TwoPhaseOperationStatus, BankOperationResult
)
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity
from app.services.timeline_service import TimelineService
from app.services.bank_adapter_service import bank_adapter_service

logger = logging.getLogger(__name__)

class TwoPhaseCommitService:
    """Оркестратор двухфазных транзакций"""
    
    def __init__(self):
        self.default_timeout = 300  # 5 минут по умолчанию
        self.max_retries = 3
        self.retry_delay = 5  # секунд
        
    async def execute_transaction(
        self, 
        db: Session, 
        payment_request: PaymentRequest,
        sender_bank_code: str,
        payer_phone: Optional[str] = None,
        sender_account: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Основной метод выполнения двухфазной транзакции
        
        Args:
            db: Сессия базы данных
            payment_request: Платежный запрос
            sender_bank_code: Код банка отправителя
            payer_phone: Телефон плательщика
            sender_account: Счет отправителя (если известен)
            
        Returns:
            Результат выполнения транзакции
        """
        
        # Генерируем уникальный ID транзакции
        transaction_id = f"2PC_{payment_request.token}_{int(datetime.now().timestamp())}"
        
        logger.info(f"🔄 Начало двухфазной транзакции {transaction_id}")
        
        try:
            # Обновляем статус и сохраняем данные отправителя
            payment_request.status = TransactionStatus.PREPARING
            payment_request.sender_bank_code = sender_bank_code
            payment_request.transaction_id = transaction_id
            payment_request.payer_phone = payer_phone
            payment_request.prepare_started_at = datetime.now()
            
            # Сохраняем метаданные
            metadata = {
                "sender_account": sender_account,
                "payer_phone": payer_phone,
                "started_at": datetime.now().isoformat(),
                "timeout_seconds": self.default_timeout
            }
            payment_request.two_phase_metadata = json.dumps(metadata)
            
            db.commit()
            
            # Запись в таймлайн
            TimelineService.record_event(
                db,
                payment_token=payment_request.token,
                event_type='two_phase_started',
                title='Начата двухфазная транзакция',
                description=f'ID: {transaction_id}, отправитель: {sender_bank_code}',
                actor='system',
                source='two_phase_commit',
                status='info'
            )
            
            # Фаза 1: Подготовка (Prepare)
            prepare_result = await self._execute_prepare_phase(
                db, payment_request, sender_bank_code, sender_account, payer_phone
            )
            
            if not prepare_result["success"]:
                # Подготовка не удалась - переходим к отмене
                logger.warning(f"❌ Подготовка транзакции {transaction_id} не удалась: {prepare_result['error']}")
                
                abort_result = await self._execute_abort_phase(
                    db, payment_request, prepare_result.get("partial_results", [])
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
            payment_request.status = TransactionStatus.PREPARED
            payment_request.prepare_completed_at = datetime.now()
            
            # Запись в таймлайн о завершении подготовки
            TimelineService.record_event(
                db,
                payment_token=payment_request.token,
                event_type='two_phase_prepared',
                title='Подготовка транзакции завершена',
                description=f'Банки готовы к выполнению транзакции {transaction_id}',
                actor='system',
                source='two_phase_commit',
                status='success'
            )
            
            # Сохраняем результаты подготовки
            sender_result = next((r for r in prepare_result["results"] if r.bank_role == BankRole.SENDER), None)
            receiver_result = next((r for r in prepare_result["results"] if r.bank_role == BankRole.RECEIVER), None)
            
            if sender_result and sender_result.response_data:
                payment_request.sender_prepare_result = json.dumps(sender_result.response_data)
            if receiver_result and receiver_result.response_data:
                payment_request.receiver_prepare_result = json.dumps(receiver_result.response_data)
            
            db.commit()
            
            logger.info(f"✅ Подготовка транзакции {transaction_id} завершена успешно")
            
            # Фаза 2: Выполнение (Commit)
            commit_result = await self._execute_commit_phase(
                db, payment_request, prepare_result["results"]
            )
            
            if commit_result["success"]:
                # Транзакция завершена успешно
                payment_request.status = TransactionStatus.COMPLETED
                payment_request.commit_completed_at = datetime.now()
                payment_request.is_paid = True
                payment_request.paid_at = datetime.now()
                
                # Находим сумму из результатов
                for result in commit_result["results"]:
                    if result.bank_role == BankRole.SENDER and result.response_data:
                        payment_request.paid_amount = result.response_data.get("actual_amount", payment_request.amount)
                        break
                
                # Запись в таймлайн о завершении транзакции
                TimelineService.record_event(
                    db,
                    payment_token=payment_request.token,
                    event_type='two_phase_completed',
                    title='Двухфазная транзакция завершена',
                    description=f'Платеж {payment_request.payment_reference} успешно обработан. Сумма: {payment_request.paid_amount} {payment_request.currency}',
                    actor='system',
                    source='two_phase_commit',
                    status='success'
                )
                
                db.commit()
                
                logger.info(f"🎉 Транзакция {transaction_id} завершена успешно")
                
                return {
                    "success": True,
                    "transaction_id": transaction_id,
                    "status": "completed",
                    "amount": payment_request.paid_amount,
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result["results"]
                }
            else:
                # Commit не удался - это критическая ситуация
                # Средства зарезервированы, но транзакция не выполнена
                logger.error(f"💥 КРИТИЧЕСКАЯ ОШИБКА: Commit транзакции {transaction_id} не удался!")
                
                payment_request.status = TransactionStatus.COMMITTING  # Оставляем в промежуточном состоянии
                payment_request.commit_started_at = datetime.now()
                db.commit()
                
                TimelineService.record_event(
                    db,
                    payment_token=payment_request.token,
                    event_type='commit_failed',
                    title='КРИТИЧЕСКАЯ ОШИБКА: Commit не удался',
                    description=f'Требуется ручное вмешательство! {commit_result["error"]}',
                    actor='system',
                    source='two_phase_commit',
                    status='error'
                )
                
                # Возвращаем специальный статус для ручного вмешательства
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "commit_failed",
                    "error": commit_result["error"],
                    "requires_manual_intervention": True,
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result.get("results", [])
                }
                
        except Exception as e:
            logger.error(f"💥 Критическая ошибка в двухфазной транзакции {transaction_id}: {e}")
            
            # Пытаемся отменить транзакцию
            try:
                payment_request.status = TransactionStatus.ABORTING
                db.commit()
                
                await self._execute_abort_phase(db, payment_request, [])
                
                TimelineService.record_event(
                    db,
                    payment_token=payment_request.token,
                    event_type='transaction_error',
                    title='Ошибка двухфазной транзакции',
                    description=f'Критическая ошибка: {str(e)}',
                    actor='system',
                    source='two_phase_commit',
                    status='error'
                )
            except Exception as abort_error:
                logger.error(f"💥💥 Ошибка при отмене транзакции {transaction_id}: {abort_error}")
            
            return {
                "success": False,
                "transaction_id": transaction_id,
                "status": "error",
                "error": str(e),
                "requires_manual_intervention": True
            }
    
    async def _execute_prepare_phase(
        self, 
        db: Session, 
        payment_request: PaymentRequest,
        sender_bank_code: str,
        sender_account: Optional[str],
        payer_phone: Optional[str]
    ) -> Dict[str, Any]:
        """Выполнение фазы подготовки (prepare)"""
        
        logger.info(f"📝 Начало фазы подготовки для транзакции {payment_request.transaction_id}")
        
        # Получаем банки
        sender_bank = db.query(Bank).filter(Bank.code == sender_bank_code).first()
        receiver_bank = db.query(Bank).filter(Bank.code == payment_request.receiver_bank_code).first()
        
        if not sender_bank:
            return {"success": False, "error": f"Банк отправителя {sender_bank_code} не найден"}
        
        if not receiver_bank:
            return {"success": False, "error": f"Банк получателя {payment_request.receiver_bank_code} не найден"}
        
        # Подготавливаем запросы
        base_request_data = {
            "transaction_id": payment_request.transaction_id,
            "payment_token": payment_request.token,
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "receiver_account": payment_request.receiver_account,
            "receiver_name": payment_request.receiver_name,
            "description": payment_request.description,
            "payment_reference": payment_request.payment_reference,
            "timeout_seconds": self.default_timeout
        }
        
        # Запрос для банка отправителя
        sender_request = TransactionPrepareRequest(
            **base_request_data,
            bank_role=BankRole.SENDER,
            sender_account=sender_account,
            sender_phone=payer_phone
        )
        
        # Запрос для банка получателя  
        receiver_request = TransactionPrepareRequest(
            **base_request_data,
            bank_role=BankRole.RECEIVER
        )
        
        # Отправляем запросы параллельно
        tasks = [
            self._send_prepare_request(db, sender_bank, sender_request),
            self._send_prepare_request(db, receiver_bank, receiver_request)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful_results = []
        partial_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = sender_bank_code if i == 0 else payment_request.receiver_bank_code
                logger.error(f"❌ Ошибка при отправке prepare к банку {bank_code}: {result}")
                
                error_result = BankOperationResult(
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
            logger.info(f"✅ Фаза подготовки завершена успешно для транзакции {payment_request.transaction_id}")
            return {
                "success": True,
                "results": successful_results
            }
        else:
            failed_banks = [r.bank_code for r in partial_results if not r.success]
            logger.warning(f"❌ Фаза подготовки не удалась. Неуспешные банки: {failed_banks}")
            
            return {
                "success": False,
                "error": f"Подготовка не удалась для банков: {', '.join(failed_banks)}",
                "results": partial_results,
                "partial_results": [r for r in partial_results if r.success]
            }
    
    async def _execute_commit_phase(
        self, 
        db: Session, 
        payment_request: PaymentRequest,
        prepare_results: List[BankOperationResult]
    ) -> Dict[str, Any]:
        """Выполнение фазы фиксации (commit)"""
        
        logger.info(f"💳 Начало фазы commit для транзакции {payment_request.transaction_id}")
        
        payment_request.status = TransactionStatus.COMMITTING
        payment_request.commit_started_at = datetime.now()
        db.commit()
        
        # Готовим запросы commit для каждого банка
        commit_tasks = []
        
        for prepare_result in prepare_results:
            # Получаем банк
            bank = db.query(Bank).filter(Bank.code == prepare_result.bank_code).first()
            if not bank:
                continue
            
            # Извлекаем данные из результата подготовки
            prepared_amount = payment_request.amount
            reservation_id = None
            
            if prepare_result.response_data:
                prepared_amount = prepare_result.response_data.get("reserved_amount", payment_request.amount)
                reservation_id = prepare_result.response_data.get("reservation_id")
            
            # Создаем запрос commit
            commit_request = TransactionCommitRequest(
                transaction_id=payment_request.transaction_id,
                payment_token=payment_request.token,
                bank_role=prepare_result.bank_role,
                prepared_amount=prepared_amount,
                reservation_id=reservation_id
            )
            
            commit_tasks.append(
                self._send_commit_request(db, bank, commit_request)
            )
        
        # Отправляем все commit запросы параллельно
        results = await asyncio.gather(*commit_tasks, return_exceptions=True)
        
        # Анализируем результаты
        successful_results = []
        all_results = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = prepare_results[i].bank_code
                logger.error(f"❌ Ошибка при отправке commit к банку {bank_code}: {result}")
                
                error_result = BankOperationResult(
                    bank_code=bank_code,
                    bank_role=prepare_results[i].bank_role,
                    operation="commit",
                    success=False,
                    error_message=str(result)
                )
                all_results.append(error_result)
            else:
                all_results.append(result)
                
                if result.success and result.response_status == TwoPhaseOperationStatus.COMMITTED:
                    successful_results.append(result)
        
        # Проверяем успешность фазы commit
        if len(successful_results) == len(prepare_results):
            logger.info(f"✅ Фаза commit завершена успешно для транзакции {payment_request.transaction_id}")
            return {
                "success": True,
                "results": all_results
            }
        else:
            failed_banks = [r.bank_code for r in all_results if not r.success]
            logger.error(f"💥 Фаза commit не удалась для банков: {failed_banks}")
            
            return {
                "success": False,
                "error": f"Commit не удался для банков: {', '.join(failed_banks)}",
                "results": all_results
            }
    
    async def _execute_abort_phase(
        self, 
        db: Session, 
        payment_request: PaymentRequest,
        prepared_results: List[BankOperationResult]
    ) -> Dict[str, Any]:
        """Выполнение фазы отмены (abort)"""
        
        logger.info(f"🚫 Начало фазы abort для транзакции {payment_request.transaction_id}")
        
        payment_request.status = TransactionStatus.ABORTING
        payment_request.abort_started_at = datetime.now()
        db.commit()
        
        # Готовим запросы abort для банков, которые успешно прошли prepare
        abort_tasks = []
        
        for prepare_result in prepared_results:
            if not prepare_result.success:
                continue  # Пропускаем неуспешные результаты
            
            # Получаем банк
            bank = db.query(Bank).filter(Bank.code == prepare_result.bank_code).first()
            if not bank:
                continue
            
            # Извлекаем ID резервирования
            reservation_id = None
            if prepare_result.response_data:
                reservation_id = prepare_result.response_data.get("reservation_id")
            
            # Создаем запрос abort
            abort_request = TransactionAbortRequest(
                transaction_id=payment_request.transaction_id,
                payment_token=payment_request.token,
                bank_role=prepare_result.bank_role,
                reservation_id=reservation_id,
                abort_reason="Transaction preparation failed or explicitly aborted"
            )
            
            abort_tasks.append(
                self._send_abort_request(db, bank, abort_request)
            )
        
        # Отправляем все abort запросы параллельно
        if abort_tasks:
            results = await asyncio.gather(*abort_tasks, return_exceptions=True)
            
            # Обрабатываем результаты
            all_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    bank_code = prepared_results[i].bank_code
                    logger.error(f"❌ Ошибка при отправке abort к банку {bank_code}: {result}")
                    
                    error_result = BankOperationResult(
                        bank_code=bank_code,
                        bank_role=prepared_results[i].bank_role,
                        operation="abort",
                        success=False,
                        error_message=str(result)
                    )
                    all_results.append(error_result)
                else:
                    all_results.append(result)
        else:
            all_results = []
        
        # Завершаем отмену
        payment_request.status = TransactionStatus.ABORTED
        payment_request.abort_completed_at = datetime.now()
        db.commit()
        
        TimelineService.record_event(
            db,
            payment_token=payment_request.token,
            event_type='transaction_aborted',
            title='Двухфазная транзакция отменена',
            description=f'Транзакция {payment_request.transaction_id} отменена',
            actor='system',
            source='two_phase_commit',
            status='warning'
        )
        
        logger.info(f"🚫 Фаза abort завершена для транзакции {payment_request.transaction_id}")
        
        return {
            "success": True,
            "results": all_results
        }
    
    async def _send_prepare_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: TransactionPrepareRequest
    ) -> BankOperationResult:
        """Отправка запроса prepare банку"""
        
        start_time = datetime.now()
        
        # Логируем операцию
        operation_log = TwoPhaseOperation(
            payment_token=request.payment_token,
            transaction_id=request.transaction_id,
            phase="prepare",
            operation_type="request",
            bank_code=bank.code,
            bank_role=request.bank_role.value,
            request_data=request.json(),
            started_at=start_time
        )
        db.add(operation_log)
        db.commit()
        
        try:
            # Используем bank adapter для форматирования запроса и получения URL/заголовков
            base_url = bank.webhook_url or f"https://api.{bank.code.lower()}.bank"
            
            # Специальная обработка для симулятора - всегда используем внутренний URL
            if base_url and "simulation" in base_url:
                # Для симулятора всегда используем localhost для избежания проблем с сетью
                base_url = "http://localhost:8000/simulation/bank-api"
                logger.info(f"🔄 Симулятор: используем внутренний URL {base_url}")
            
            url = bank_adapter_service.get_two_phase_endpoint_for_bank(bank.code, base_url, "prepare")
            headers = bank_adapter_service.get_two_phase_headers_for_bank(bank.code, bank, "prepare")
            formatted_request = bank_adapter_service.format_prepare_request_for_bank(bank.code, request)
            
            # Детальное логирование для отладки
            logger.info(f"🔗 Отправка PREPARE запроса к банку {bank.code}:")
            logger.info(f"  Base URL: {base_url}")
            logger.info(f"  Full URL: {url}")
            logger.info(f"  Headers: {headers}")
            logger.info(f"  Request data: {formatted_request}")
            
            # Отправляем запрос
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(url, json=formatted_request, headers=headers) as response:
                    response_data = await response.json()
                    
                    # Обновляем лог операции
                    operation_log.completed_at = datetime.now()
                    operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
                    operation_log.response_data = json.dumps(response_data)
                    
                    if response.status == 200:
                        # Парсим ответ через адаптер банка
                        prepare_response = bank_adapter_service.parse_prepare_response_from_bank(bank.code, response_data)
                        operation_log.response_status = prepare_response.status.value
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="prepare",
                            success=prepare_response.status == TwoPhaseOperationStatus.PREPARED,
                            response_status=prepare_response.status,
                            response_data=response_data,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.info(f"✅ Prepare ответ от {bank.code}: {prepare_response.status.value}")
                        
                    else:
                        operation_log.response_status = "error"
                        operation_log.error_message = f"HTTP {response.status}: {response_data.get('detail', 'Unknown error')}"
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="prepare",
                            success=False,
                            error_message=operation_log.error_message,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.error(f"❌ Ошибка prepare от {bank.code}: {operation_log.error_message}")
            
            db.commit()
            return result
            
        except Exception as e:
            # Логируем ошибку
            operation_log.completed_at = datetime.now()
            operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
            operation_log.response_status = "error"
            operation_log.error_message = str(e)
            db.commit()
            
            logger.error(f"💥 Исключение при prepare запросе к {bank.code}: {e}")
            logger.error(f"💥 Тип ошибки: {type(e).__name__}")
            logger.error(f"💥 URL: {url}")
            logger.error(f"💥 Продолжительность: {operation_log.duration_ms}ms")
            
            return BankOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="prepare",
                success=False,
                error_message=str(e),
                duration_ms=operation_log.duration_ms
            )
    
    async def _send_commit_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: TransactionCommitRequest
    ) -> BankOperationResult:
        """Отправка запроса commit банку"""
        
        start_time = datetime.now()
        
        # Логируем операцию
        operation_log = TwoPhaseOperation(
            payment_token=request.payment_token,
            transaction_id=request.transaction_id,
            phase="commit",
            operation_type="request",
            bank_code=bank.code,
            bank_role=request.bank_role.value,
            request_data=request.json(),
            started_at=start_time
        )
        db.add(operation_log)
        db.commit()
        
        try:
            # Используем bank adapter
            base_url = bank.webhook_url or f"https://api.{bank.code.lower()}.bank"
            
            # Специальная обработка для симулятора - всегда используем внутренний URL
            if base_url and "simulation" in base_url:
                # Для симулятора всегда используем localhost для избежания проблем с сетью
                base_url = "http://localhost:8000/simulation/bank-api"
                logger.info(f"🔄 Симулятор: используем внутренний URL {base_url}")
            
            url = bank_adapter_service.get_two_phase_endpoint_for_bank(bank.code, base_url, "commit")
            headers = bank_adapter_service.get_two_phase_headers_for_bank(bank.code, bank, "commit")
            formatted_request = bank_adapter_service.format_commit_request_for_bank(bank.code, request)
            
            # Отправляем запрос
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(url, json=formatted_request, headers=headers) as response:
                    response_data = await response.json()
                    
                    # Обновляем лог
                    operation_log.completed_at = datetime.now()
                    operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
                    operation_log.response_data = json.dumps(response_data)
                    
                    if response.status == 200:
                        commit_response = bank_adapter_service.parse_commit_response_from_bank(bank.code, response_data)
                        operation_log.response_status = commit_response.status.value
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="commit",
                            success=commit_response.status == TwoPhaseOperationStatus.COMMITTED,
                            response_status=commit_response.status,
                            response_data=response_data,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.info(f"✅ Commit ответ от {bank.code}: {commit_response.status.value}")
                        
                    else:
                        operation_log.response_status = "error"
                        operation_log.error_message = f"HTTP {response.status}: {response_data.get('detail', 'Unknown error')}"
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="commit",
                            success=False,
                            error_message=operation_log.error_message,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.error(f"❌ Ошибка commit от {bank.code}: {operation_log.error_message}")
            
            db.commit()
            return result
            
        except Exception as e:
            operation_log.completed_at = datetime.now()
            operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
            operation_log.response_status = "error"
            operation_log.error_message = str(e)
            db.commit()
            
            logger.error(f"💥 Исключение при commit запросе к {bank.code}: {e}")
            
            return BankOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="commit",
                success=False,
                error_message=str(e),
                duration_ms=operation_log.duration_ms
            )
    
    async def _send_abort_request(
        self, 
        db: Session, 
        bank: Bank, 
        request: TransactionAbortRequest
    ) -> BankOperationResult:
        """Отправка запроса abort банку"""
        
        start_time = datetime.now()
        
        # Логируем операцию
        operation_log = TwoPhaseOperation(
            payment_token=request.payment_token,
            transaction_id=request.transaction_id,
            phase="abort",
            operation_type="request",
            bank_code=bank.code,
            bank_role=request.bank_role.value,
            request_data=request.json(),
            started_at=start_time
        )
        db.add(operation_log)
        db.commit()
        
        try:
            # Используем bank adapter
            base_url = bank.webhook_url or f"https://api.{bank.code.lower()}.bank"
            
            # Специальная обработка для симулятора - всегда используем внутренний URL
            if base_url and "simulation" in base_url:
                # Для симулятора всегда используем localhost для избежания проблем с сетью
                base_url = "http://localhost:8000/simulation/bank-api"
                logger.info(f"🔄 Симулятор: используем внутренний URL {base_url}")
            
            url = bank_adapter_service.get_two_phase_endpoint_for_bank(bank.code, base_url, "abort")
            headers = bank_adapter_service.get_two_phase_headers_for_bank(bank.code, bank, "abort")
            formatted_request = bank_adapter_service.format_abort_request_for_bank(bank.code, request)
            
            # Отправляем запрос
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(url, json=formatted_request, headers=headers) as response:
                    response_data = await response.json()
                    
                    # Обновляем лог
                    operation_log.completed_at = datetime.now()
                    operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
                    operation_log.response_data = json.dumps(response_data)
                    
                    if response.status == 200:
                        abort_response = bank_adapter_service.parse_abort_response_from_bank(bank.code, response_data)
                        operation_log.response_status = abort_response.status.value
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="abort",
                            success=abort_response.status == TwoPhaseOperationStatus.ABORTED,
                            response_status=abort_response.status,
                            response_data=response_data,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.info(f"✅ Abort ответ от {bank.code}: {abort_response.status.value}")
                        
                    else:
                        operation_log.response_status = "error"
                        operation_log.error_message = f"HTTP {response.status}: {response_data.get('detail', 'Unknown error')}"
                        
                        result = BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation="abort",
                            success=False,
                            error_message=operation_log.error_message,
                            duration_ms=operation_log.duration_ms
                        )
                        
                        logger.warning(f"⚠️ Ошибка abort от {bank.code}: {operation_log.error_message}")
            
            db.commit()
            return result
            
        except Exception as e:
            operation_log.completed_at = datetime.now()
            operation_log.duration_ms = int((operation_log.completed_at - start_time).total_seconds() * 1000)
            operation_log.response_status = "error"
            operation_log.error_message = str(e)
            db.commit()
            
            logger.warning(f"⚠️ Исключение при abort запросе к {bank.code}: {e}")
            
            return BankOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation="abort",
                success=False,
                error_message=str(e),
                duration_ms=operation_log.duration_ms
            )

# Глобальный экземпляр сервиса
two_phase_commit_service = TwoPhaseCommitService()
