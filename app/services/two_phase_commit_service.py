"""
Сервис для управления двухфазными транзакциями (Two-Phase Commit Protocol)
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from sqlalchemy.orm import Session

from app.models.bank import Bank
from app.models.unified import UnifiedPayment
from app.schemas.bank import (
    BankOperationResult,
    BankRole,
    TransactionAbortRequest,
    TransactionCommitRequest,
    TransactionPrepareRequest,
    TwoPhaseOperationStatus,
)
from app.schemas.unified_payment import PaymentStatus
from app.services.bank_adapter_service import bank_adapter_service
from app.services.timeline_service import TimelineService

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
        payment: UnifiedPayment,
        sender_bank_code: str,
        payer_phone: Optional[str] = None,
        sender_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Основной метод выполнения двухфазной транзакции
        """
        transaction_id = payment.transaction_id or f"2PC_{payment.id}_{int(datetime.now().timestamp())}"
        payment.transaction_id = transaction_id

        logger.info(f"🔄 Начало двухфазной транзакции {transaction_id}")

        try:
            payment.status = PaymentStatus.PREPARING
            payment.sender_bank_code = sender_bank_code
            payment.payer_phone = payer_phone
            payment.prepare_started_at = datetime.now()

            metadata = {
                "sender_account": sender_account,
                "payer_phone": payer_phone,
                "started_at": datetime.now().isoformat(),
                "timeout_seconds": self.default_timeout,
            }
            payment.two_phase_metadata = json.dumps(metadata)

            db.commit()

            TimelineService.record_event(
                db,
                payment_id=payment.id,
                event_type="two_phase_started",
                title="Начата двухфазная транзакция",
                description=f"ID: {transaction_id}, отправитель: {sender_bank_code}",
                actor="system",
                source="two_phase_commit",
                status="info",
            )

            prepare_result = await self._execute_prepare_phase(
                db, payment, sender_bank_code, sender_account, payer_phone
            )

            if not prepare_result["success"]:
                logger.warning(
                    f"❌ Подготовка транзакции {transaction_id} не удалась: {prepare_result['error']}"
                )
                abort_result = await self._execute_abort_phase(
                    db, payment, prepare_result.get("partial_results", [])
                )
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "aborted",
                    "error": prepare_result["error"],
                    "prepare_results": prepare_result.get("results", []),
                    "abort_results": abort_result.get("results", []),
                }

            payment.status = PaymentStatus.PREPARED
            payment.prepare_completed_at = datetime.now()

            TimelineService.record_event(
                db,
                payment_id=payment.id,
                event_type="two_phase_prepared",
                title="Подготовка транзакции завершена",
                description=f"Банки готовы к выполнению транзакции {transaction_id}",
                actor="system",
                source="two_phase_commit",
                status="success",
            )

            sender_result = next(
                (
                    r
                    for r in prepare_result["results"]
                    if r.bank_role == BankRole.SENDER
                ),
                None,
            )
            receiver_result = next(
                (
                    r
                    for r in prepare_result["results"]
                    if r.bank_role == BankRole.RECEIVER
                ),
                None,
            )

            if sender_result and sender_result.response_data:
                payment.sender_prepare_result = json.dumps(
                    sender_result.response_data
                )
            if receiver_result and receiver_result.response_data:
                payment.receiver_prepare_result = json.dumps(
                    receiver_result.response_data
                )

            db.commit()

            logger.info(f"✅ Подготовка транзакции {transaction_id} завершена успешно")

            commit_result = await self._execute_commit_phase(
                db, payment, prepare_result["results"]
            )

            if commit_result["success"]:
                payment.status = PaymentStatus.COMPLETED
                payment.commit_completed_at = datetime.now()
                payment.is_paid = True
                payment.paid_at = datetime.now()

                for result in commit_result["results"]:
                    if (
                        result.bank_role == BankRole.SENDER
                        and result.response_data
                    ):
                        payment.amount = result.response_data.get(
                            "actual_amount", payment.amount
                        )
                        break

                TimelineService.record_event(
                    db,
                    payment_id=payment.id,
                    event_type="two_phase_completed",
                    title="Двухфазная транзакция завершена",
                    description=f"Платеж {payment.payment_reference} успешно обработан. Сумма: {payment.amount} {payment.currency}",
                    actor="system",
                    source="two_phase_commit",
                    status="success",
                )

                db.commit()

                logger.info(f"🎉 Транзакция {transaction_id} завершена успешно")

                return {
                    "success": True,
                    "transaction_id": transaction_id,
                    "status": "completed",
                    "amount": payment.amount,
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result["results"],
                }
            else:
                logger.error(
                    f"💥 КРИТИЧЕСКАЯ ОШИБКА: Commit транзакции {transaction_id} не удался!"
                )
                payment.status = PaymentStatus.FAILED  # Or a new status like 'COMMIT_FAILED'
                payment.commit_started_at = datetime.now()
                db.commit()

                TimelineService.record_event(
                    db,
                    payment_id=payment.id,
                    event_type="commit_failed",
                    title="КРИТИЧЕСКАЯ ОШИБКА: Commit не удался",
                    description=f'Требуется ручное вмешательство! {commit_result["error"]}',
                    actor="system",
                    source="two_phase_commit",
                    status="error",
                )

                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "status": "commit_failed",
                    "error": commit_result["error"],
                    "requires_manual_intervention": True,
                    "prepare_results": prepare_result["results"],
                    "commit_results": commit_result.get("results", []),
                }

        except Exception as e:
            logger.exception(
                f"💥 Критическая ошибка в двухфазной транзакции {transaction_id}: {e}"
            )
            try:
                payment.status = PaymentStatus.FAILED
                db.commit()
                await self._execute_abort_phase(db, payment, [])
                TimelineService.record_event(
                    db,
                    payment_id=payment.id,
                    event_type="transaction_error",
                    title="Ошибка двухфазной транзакции",
                    description=f"Критическая ошибка: {str(e)}",
                    actor="system",
                    source="two_phase_commit",
                    status="error",
                )
            except Exception as abort_error:
                logger.error(
                    f"💥💥 Ошибка при отмене транзакции {transaction_id}: {abort_error}"
                )

            return {
                "success": False,
                "transaction_id": transaction_id,
                "status": "error",
                "error": str(e),
                "requires_manual_intervention": True,
            }

    async def _execute_prepare_phase(
        self,
        db: Session,
        payment: UnifiedPayment,
        sender_bank_code: str,
        sender_account: Optional[str],
        payer_phone: Optional[str],
    ) -> Dict[str, Any]:
        logger.info(f"📝 Начало фазы подготовки для транзакции {payment.transaction_id}")
        sender_bank = db.query(Bank).filter(Bank.code == sender_bank_code).first()
        receiver_bank = (
            db.query(Bank).filter(Bank.code == payment.receiver_bank_code).first()
        )

        if not sender_bank:
            return {
                "success": False,
                "error": f"Банк отправителя {sender_bank_code} не найден",
            }
        if not receiver_bank:
            return {
                "success": False,
                "error": f"Банк получателя {payment.receiver_bank_code} не найден",
            }

        base_request_data = {
            "transaction_id": payment.transaction_id,
            "payment_token": payment.transaction_id,  # Using transaction_id as payment_token
            "amount": payment.amount,
            "currency": payment.currency,
            "receiver_account": payment.receiver_account,
            "receiver_name": payment.receiver_name,
            "description": payment.description,
            "payment_reference": payment.payment_reference,
            "timeout_seconds": self.default_timeout,
        }

        sender_request = TransactionPrepareRequest(
            **base_request_data,
            bank_role=BankRole.SENDER,
            sender_account=sender_account,
            sender_phone=payer_phone,
        )
        receiver_request = TransactionPrepareRequest(
            **base_request_data, bank_role=BankRole.RECEIVER
        )

        tasks = [
            self._send_prepare_request(db, sender_bank, sender_request, payment.id),
            self._send_prepare_request(db, receiver_bank, receiver_request, payment.id),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful_results = []
        partial_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                bank_code = (
                    sender_bank_code
                    if i == 0
                    else payment.receiver_bank_code
                )
                logger.error(f"❌ Ошибка при отправке prepare к банку {bank_code}: {result}")
                error_result = BankOperationResult(
                    bank_code=bank_code,
                    bank_role=BankRole.SENDER if i == 0 else BankRole.RECEIVER,
                    operation="prepare",
                    success=False,
                    error_message=str(result),
                )
                partial_results.append(error_result)
            else:
                partial_results.append(result)
                if result.success and result.response_status == TwoPhaseOperationStatus.PREPARED:
                    successful_results.append(result)

        if len(successful_results) == 2:
            logger.info(
                f"✅ Фаза подготовки завершена успешно для транзакции {payment.transaction_id}"
            )
            return {"success": True, "results": successful_results}
        else:
            failed_banks = [r.bank_code for r in partial_results if not r.success]
            logger.warning(
                f"❌ Фаза подготовки не удалась. Неуспешные банки: {failed_banks}"
            )
            return {
                "success": False,
                "error": f"Подготовка не удалась для банков: {', '.join(failed_banks)}",
                "results": partial_results,
                "partial_results": [r for r in partial_results if r.success],
            }

    async def _execute_commit_phase(
        self,
        db: Session,
        payment: UnifiedPayment,
        prepare_results: List[BankOperationResult],
    ) -> Dict[str, Any]:
        logger.info(f"💳 Начало фазы commit для транзакции {payment.transaction_id}")
        payment.status = PaymentStatus.COMMITTING
        payment.commit_started_at = datetime.now()
        db.commit()

        commit_tasks = []
        for prepare_result in prepare_results:
            bank = db.query(Bank).filter(Bank.code == prepare_result.bank_code).first()
            if not bank:
                continue

            prepared_amount = payment.amount
            reservation_id = None
            if prepare_result.response_data:
                prepared_amount = prepare_result.response_data.get(
                    "reserved_amount", payment.amount
                )
                reservation_id = prepare_result.response_data.get("reservation_id")

            commit_request = TransactionCommitRequest(
                transaction_id=payment.transaction_id,
                payment_token=payment.transaction_id,
                bank_role=prepare_result.bank_role,
                prepared_amount=prepared_amount,
                reservation_id=reservation_id,
            )
            commit_tasks.append(self._send_commit_request(db, bank, commit_request, payment.id))

        results = await asyncio.gather(*commit_tasks, return_exceptions=True)

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
                    error_message=str(result),
                )
                all_results.append(error_result)
            else:
                all_results.append(result)
                if result.success and result.response_status == TwoPhaseOperationStatus.COMMITTED:
                    successful_results.append(result)

        if len(successful_results) == len(prepare_results):
            logger.info(
                f"✅ Фаза commit завершена успешно для транзакции {payment.transaction_id}"
            )
            return {"success": True, "results": all_results}
        else:
            failed_banks = [r.bank_code for r in all_results if not r.success]
            logger.error(f"💥 Фаза commit не удалась для банков: {failed_banks}")
            return {
                "success": False,
                "error": f"Commit не удался для банков: {', '.join(failed_banks)}",
                "results": all_results,
            }

    async def _execute_abort_phase(
        self,
        db: Session,
        payment: UnifiedPayment,
        prepared_results: List[BankOperationResult],
    ) -> Dict[str, Any]:
        logger.info(f"🚫 Начало фазы abort для транзакции {payment.transaction_id}")
        payment.status = PaymentStatus.ABORTING
        payment.abort_started_at = datetime.now()
        db.commit()

        abort_tasks = []
        for prepare_result in prepared_results:
            if not prepare_result.success:
                continue

            bank = db.query(Bank).filter(Bank.code == prepare_result.bank_code).first()
            if not bank:
                continue

            reservation_id = None
            if prepare_result.response_data:
                reservation_id = prepare_result.response_data.get("reservation_id")

            abort_request = TransactionAbortRequest(
                transaction_id=payment.transaction_id,
                payment_token=payment.transaction_id,
                bank_role=prepare_result.bank_role,
                reservation_id=reservation_id,
                abort_reason="Transaction preparation failed or explicitly aborted",
            )
            abort_tasks.append(self._send_abort_request(db, bank, abort_request, payment.id))

        if abort_tasks:
            results = await asyncio.gather(*abort_tasks, return_exceptions=True)
            all_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    bank_code = prepared_results[i].bank_code
                    logger.error(
                        f"❌ Ошибка при отправке abort к банку {bank_code}: {result}"
                    )
                    error_result = BankOperationResult(
                        bank_code=bank_code,
                        bank_role=prepared_results[i].bank_role,
                        operation="abort",
                        success=False,
                        error_message=str(result),
                    )
                    all_results.append(error_result)
                else:
                    all_results.append(result)
        else:
            all_results = []

        payment.status = PaymentStatus.CANCELLED
        payment.abort_completed_at = datetime.now()
        db.commit()

        TimelineService.record_event(
            db,
            payment_id=payment.id,
            event_type="transaction_aborted",
            title="Двухфазная транзакция отменена",
            description=f"Транзакция {payment.transaction_id} отменена",
            actor="system",
            source="two_phase_commit",
            status="warning",
        )

        logger.info(f"🚫 Фаза abort завершена для транзакции {payment.transaction_id}")
        return {"success": True, "results": all_results}

    async def _send_request(
        self,
        db: Session,
        bank: Bank,
        phase: str,
        request: Any,
        payment_id: int,
    ) -> BankOperationResult:
        start_time = datetime.now()
        payment = db.query(UnifiedPayment).filter(UnifiedPayment.id == payment_id).first()

        try:
            base_url = bank.webhook_url or f"https://api.{bank.code.lower()}.bank"
            if "simulation" in (base_url or ""):
                base_url = "http://localhost:8000/simulation/bank-api"

            url = bank_adapter_service.get_two_phase_endpoint_for_bank(
                bank.code, base_url, phase
            )
            headers = bank_adapter_service.get_two_phase_headers_for_bank(
                bank.code, bank, phase
            )
            
            formatter = getattr(bank_adapter_service, f"format_{phase}_request_for_bank")
            formatted_request = formatter(bank.code, request)

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(
                    url, json=formatted_request, headers=headers
                ) as response:
                    response_data = await response.json()
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                    if response.status == 200:
                        parser = getattr(bank_adapter_service, f"parse_{phase}_response_from_bank")
                        parsed_response = parser(bank.code, response_data)
                        
                        success = parsed_response.status in [TwoPhaseOperationStatus.PREPARED, TwoPhaseOperationStatus.COMMITTED, TwoPhaseOperationStatus.ABORTED]

                        return BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation=phase,
                            success=success,
                            response_status=parsed_response.status,
                            response_data=response_data,
                            duration_ms=duration_ms,
                        )
                    else:
                        error_message = f"HTTP {response.status}: {response_data.get('detail', 'Unknown error')}"
                        logger.error(f"❌ Ошибка {phase} от {bank.code}: {error_message}")
                        return BankOperationResult(
                            bank_code=bank.code,
                            bank_role=request.bank_role,
                            operation=phase,
                            success=False,
                            error_message=error_message,
                            duration_ms=duration_ms,
                        )
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.exception(f"💥 Исключение при {phase} запросе к {bank.code}: {e}")
            return BankOperationResult(
                bank_code=bank.code,
                bank_role=request.bank_role,
                operation=phase,
                success=False,
                error_message=str(e),
                duration_ms=duration_ms,
            )

    async def _send_prepare_request(
        self, db: Session, bank: Bank, request: TransactionPrepareRequest, payment_id: int
    ) -> BankOperationResult:
        return await self._send_request(db, bank, "prepare", request, payment_id)

    async def _send_commit_request(
        self, db: Session, bank: Bank, request: TransactionCommitRequest, payment_id: int
    ) -> BankOperationResult:
        return await self._send_request(db, bank, "commit", request, payment_id)

    async def _send_abort_request(
        self, db: Session, bank: Bank, request: TransactionAbortRequest, payment_id: int
    ) -> BankOperationResult:
        return await self._send_request(db, bank, "abort", request, payment_id)

# Глобальный экземпляр сервиса
two_phase_commit_service = TwoPhaseCommitService()
