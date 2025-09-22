"""
Сервис для управления возвратами платежей
"""

from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc
from datetime import datetime, timedelta
import logging
import json
import asyncio

from app.models.refund import RefundRequest, RefundOperation, RefundStatus, RefundType
from app.models.merchant import MerchantPayment, Merchant
from app.schemas.refund import (
    RefundCreate, RefundResponse, RefundListResponse, RefundSummary,
    RefundValidationResult
)
from app.services.token_service import SecureTokenService
from app.services.two_phase_refund_service import two_phase_refund_service
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity
from app.services.timeline_service import TimelineService
from app.services.refund_notification_service import RefundNotificationService

logger = logging.getLogger(__name__)

class RefundService:
    """Сервис для управления возвратами"""
    
    def __init__(self):
        self.secure_token_service = SecureTokenService()
    
    async def create_refund(
        self, 
        db: Session, 
        merchant_id: int, 
        original_payment_id: int, 
        refund_data: RefundCreate
    ) -> RefundResponse:
        """
        Создание нового запроса на возврат
        
        Args:
            db: Сессия базы данных
            merchant_id: ID мерчанта
            original_payment_id: ID оригинального платежа
            refund_data: Данные для создания возврата
            
        Returns:
            Созданный запрос на возврат
        """
        
        logger.error(f"🔄 Создание возврата для платежа {original_payment_id} мерчантом {merchant_id}")
        
        # Получаем оригинальный платеж
        original_payment = db.query(MerchantPayment).filter(
            and_(
                MerchantPayment.id == original_payment_id,
                MerchantPayment.merchant_id == merchant_id
            )
        ).first()
        
        logger.error(f"🔍 Оригинальный платеж найден: {original_payment is not None}")
        if original_payment:
            logger.error(f"🔍 Данные платежа: ID={original_payment.id}, статус={original_payment.status}, сумма={original_payment.amount}")
        
        if not original_payment:
            raise StandardError(
                error_code=ErrorCode.PAYMENT_NOT_FOUND,
                message="Оригинальный платеж не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Валидируем возможность возврата
        validation_result = self._validate_refund_creation(refund_data, original_payment)
        if not validation_result.valid:
            errors = [err.dict() for err in validation_result.errors]
            raise StandardError(
                error_code=ErrorCode.REFUND_VALIDATION_FAILED,
                message="Ошибка валидации возврата",
                details=errors,
                severity=ErrorSeverity.ERROR
            )
        
        # Генерируем уникальный токен возврата
        refund_token = self.secure_token_service.generate_refund_token(original_payment_id)
        
        # Генерируем transaction_id для возврата
        transaction_id = f"REFUND_{original_payment_id}_{int(datetime.now().timestamp())}"
        
        # Создаем запрос на возврат
        refund_request = RefundRequest(
            original_payment_id=original_payment_id,
            merchant_id=merchant_id,
            amount=refund_data.amount,
            currency=refund_data.currency,
            reason=refund_data.reason,
            refund_type=refund_data.refund_type,
            refund_token=refund_token,
            transaction_id=transaction_id,
            status=RefundStatus.PENDING
        )
        
        db.add(refund_request)
        db.commit()
        db.refresh(refund_request)
        
        # Запись в таймлайн
        TimelineService.record_event(
            db,
            payment_token=refund_token,
            event_type='refund_created',
            title='Создан запрос на возврат',
            description=f'Сумма: {refund_data.amount} {refund_data.currency}, причина: {refund_data.reason}',
            actor='merchant',
            source='refund_service',
            status='info'
        )
        
        # Отправляем уведомление о создании возврата
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if merchant:
            RefundNotificationService.notify_refund_created(db, refund_request, merchant)
        
        logger.info(f"✅ Создан запрос на возврат {refund_request.id} с токеном {refund_token}")
        
        return RefundResponse.from_orm(refund_request)
    
    async def execute_refund(
        self, 
        db: Session, 
        refund_id: int, 
        merchant_id: int
    ) -> Dict[str, Any]:
        """
        Выполнение возврата через двухфазный протокол
        
        Args:
            db: Сессия базы данных
            refund_id: ID запроса на возврат
            merchant_id: ID мерчанта
            
        Returns:
            Результат выполнения возврата
        """
        
        logger.info(f"🚀 Выполнение возврата {refund_id} для мерчанта {merchant_id}")
        
        # Получаем запрос на возврат
        refund_request = db.query(RefundRequest).filter(
            and_(
                RefundRequest.id == refund_id,
                RefundRequest.merchant_id == merchant_id
            )
        ).first()
        
        if not refund_request:
            raise StandardError(
                error_code=ErrorCode.REFUND_NOT_FOUND,
                message="Запрос на возврат не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Проверяем статус
        if refund_request.status != RefundStatus.PENDING:
            raise StandardError(
                error_code=ErrorCode.REFUND_INVALID_STATUS,
                message=f"Невозможно выполнить возврат в статусе {refund_request.status.value}",
                severity=ErrorSeverity.ERROR
            )
        
        # Получаем оригинальный платеж
        original_payment = db.query(MerchantPayment).filter(
            MerchantPayment.id == refund_request.original_payment_id
        ).first()
        
        if not original_payment:
            raise StandardError(
                error_code=ErrorCode.PAYMENT_NOT_FOUND,
                message="Оригинальный платеж не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Запись в таймлайн о начале выполнения
        TimelineService.record_event(
            db,
            payment_token=refund_request.refund_token,
            event_type='refund_execution_started',
            title='Начато выполнение возврата',
            description=f'Запуск двухфазного протокола возврата',
            actor='system',
            source='refund_service',
            status='info'
        )
        
        # Отправляем уведомление о начале выполнения
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if merchant:
            RefundNotificationService.notify_refund_execution_started(db, refund_request, merchant)
        
        # Вместо автоматического выполнения, только создаем запросы в банках
        # и переводим возврат в статус "В процессе"
        logger.info(f"🔄 Создание запросов в банках для возврата {refund_id}")
        
        # Обновляем статус на "В процессе"
        refund_request.status = RefundStatus.PROCESSING
        db.commit()
        
        # Определяем банки для возврата (обратные роли)
        # Банк отправителя = банк продавца (который возвращает средства)
        # Банк получателя = банк покупателя (который получает средства обратно)
        
        # Получаем банк продавца из профиля
        sender_bank_code = "DEMO"  # По умолчанию
        if merchant and merchant.bank_name:
            # Ищем банк по названию из профиля продавца
            from app.models.payment import Bank
            seller_bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
            if seller_bank:
                sender_bank_code = seller_bank.code
        
        # Банк получателя = банк покупателя из оригинального платежа
        receiver_bank_code = original_payment.payer_bank_code if original_payment.payer_bank_code else "DEMO"
        
        # Устанавливаем банковские коды
        refund_request.sender_bank_code = sender_bank_code
        refund_request.receiver_bank_code = receiver_bank_code
        
        # Сохраняем изменения в базе данных
        db.commit()
        
        logger.info(f"🏦 Установлены банковские коды: sender={sender_bank_code}, receiver={receiver_bank_code}")
        
        # Создаем запросы в банках (только prepare, без автоматического commit)
        prepare_result = await two_phase_refund_service._execute_refund_prepare_phase(
            db, refund_request, original_payment
        )
        
        if prepare_result["success"]:
            # Запросы успешно созданы в банках
            TimelineService.record_event(
                db,
                payment_token=refund_request.refund_token,
                event_type='refund_requests_created',
                title='Запросы возврата созданы в банках',
                description=f'Ожидание подтверждения в банках. Сумма: {refund_request.amount} {refund_request.currency}',
                actor='system',
                source='refund_service',
                status='info'
            )
            
            # Запускаем мониторинг подтверждения от банков в фоновом режиме
            asyncio.create_task(self._auto_complete_refund_after_confirmation(
                db, refund_request, original_payment
            ))
            
            return {
                "success": True,
                "status": "requests_created",
                "message": "Запросы возврата созданы в банках. Возврат будет автоматически завершен после подтверждения в банках.",
                "transaction_id": refund_request.transaction_id
            }
        else:
            # Ошибка создания запросов
            refund_request.status = RefundStatus.FAILED
            db.commit()
            
            TimelineService.record_event(
                db,
                payment_token=refund_request.refund_token,
                event_type='refund_requests_failed',
                title='Ошибка создания запросов возврата',
                description=f'Ошибка: {prepare_result.get("error", "Неизвестная ошибка")}',
                actor='system',
                source='refund_service',
                status='error'
            )
            
            return {
                "success": False,
                "status": "requests_failed",
                "error": prepare_result.get("error", "Неизвестная ошибка")
            }
    
    def get_refund(
        self, 
        db: Session, 
        refund_id: int, 
        merchant_id: int
    ) -> RefundResponse:
        """
        Получение информации о возврате
        
        Args:
            db: Сессия базы данных
            refund_id: ID запроса на возврат
            merchant_id: ID мерчанта
            
        Returns:
            Информация о возврате
        """
        
        refund_request = db.query(RefundRequest).filter(
            and_(
                RefundRequest.id == refund_id,
                RefundRequest.merchant_id == merchant_id
            )
        ).first()
        
        if not refund_request:
            raise StandardError(
                error_code=ErrorCode.REFUND_NOT_FOUND,
                message="Запрос на возврат не найден",
                severity=ErrorSeverity.ERROR
            )
        
        return RefundResponse.from_orm(refund_request)
    
    def get_refunds(
        self, 
        db: Session, 
        merchant_id: int, 
        page: int = 1, 
        per_page: int = 20,
        status: Optional[RefundStatus] = None,
        refund_type: Optional[RefundType] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        original_payment_id: Optional[int] = None
    ) -> RefundListResponse:
        """
        Получение списка возвратов мерчанта
        
        Args:
            db: Сессия базы данных
            merchant_id: ID мерчанта
            page: Номер страницы
            per_page: Количество элементов на странице
            status: Фильтр по статусу
            original_payment_id: Фильтр по ID оригинального платежа
            
        Returns:
            Список возвратов с пагинацией
        """
        
        # Базовый запрос
        query = db.query(RefundRequest).filter(RefundRequest.merchant_id == merchant_id)
        
        # Применяем фильтры
        if status:
            query = query.filter(RefundRequest.status == status)
        
        if refund_type:
            query = query.filter(RefundRequest.refund_type == refund_type)
        
        if start_date:
            query = query.filter(RefundRequest.created_at >= start_date)
        
        if end_date:
            query = query.filter(RefundRequest.created_at <= end_date)
        
        if original_payment_id:
            query = query.filter(RefundRequest.original_payment_id == original_payment_id)
        
        # Сортируем по дате создания (новые сначала)
        query = query.order_by(desc(RefundRequest.created_at))
        
        # Подсчитываем общее количество
        total = query.count()
        
        # Применяем пагинацию
        offset = (page - 1) * per_page
        refunds = query.offset(offset).limit(per_page).all()
        
        # Вычисляем общее количество страниц
        total_pages = (total + per_page - 1) // per_page
        
        return RefundListResponse(
            refunds=[RefundResponse.from_orm(refund) for refund in refunds],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )
    
    def get_refund_summary(
        self, 
        db: Session, 
        merchant_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        days: int = 30
    ) -> RefundSummary:
        """
        Получение сводки по возвратам мерчанта
        
        Args:
            db: Сессия базы данных
            merchant_id: ID мерчанта
            start_date: Начальная дата (если не указана, используется days)
            end_date: Конечная дата (если не указана, используется текущая дата)
            days: Количество дней для анализа (используется если не указаны даты)
            
        Returns:
            Сводка по возвратам
        """
        
        # Определяем даты периода
        if start_date is None:
            start_date = datetime.now() - timedelta(days=days)
        if end_date is None:
            end_date = datetime.now()
        
        # Базовый запрос
        query = db.query(RefundRequest).filter(
            and_(
                RefundRequest.merchant_id == merchant_id,
                RefundRequest.created_at >= start_date,
                RefundRequest.created_at <= end_date
            )
        )
        
        # Общее количество возвратов
        total_refunds = query.count()
        
        # Общая сумма возвратов
        total_amount = db.query(func.sum(RefundRequest.amount)).filter(
            and_(
                RefundRequest.merchant_id == merchant_id,
                RefundRequest.created_at >= start_date,
                RefundRequest.created_at <= end_date,
                RefundRequest.status == RefundStatus.COMPLETED
            )
        ).scalar() or 0.0
        
        # Количество завершенных возвратов
        completed_refunds = query.filter(RefundRequest.status == RefundStatus.COMPLETED).count()
        
        # Количество ожидающих возвратов
        pending_refunds = query.filter(RefundRequest.status == RefundStatus.PENDING).count()
        
        # Количество неудачных возвратов
        failed_refunds = query.filter(RefundRequest.status == RefundStatus.FAILED).count()
        
        return RefundSummary(
            total_refunds=total_refunds,
            total_amount=total_amount,
            currency="KGS",
            completed_refunds=completed_refunds,
            pending_refunds=pending_refunds,
            failed_refunds=failed_refunds
        )
    
    def get_payment_refunds(
        self, 
        db: Session, 
        payment_id: int, 
        merchant_id: int
    ) -> List[RefundResponse]:
        """
        Получение всех возвратов для конкретного платежа
        
        Args:
            db: Сессия базы данных
            payment_id: ID платежа
            merchant_id: ID мерчанта
            
        Returns:
            Список возвратов для платежа
        """
        
        # Проверяем, что платеж принадлежит мерчанту
        payment = db.query(MerchantPayment).filter(
            and_(
                MerchantPayment.id == payment_id,
                MerchantPayment.merchant_id == merchant_id
            )
        ).first()
        
        if not payment:
            raise StandardError(
                error_code=ErrorCode.PAYMENT_NOT_FOUND,
                message="Платеж не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Получаем все возвраты для этого платежа
        refunds = db.query(RefundRequest).filter(
            RefundRequest.original_payment_id == payment_id
        ).order_by(desc(RefundRequest.created_at)).all()
        
        return [RefundResponse.from_orm(refund) for refund in refunds]
    
    def cancel_refund(
        self, 
        db: Session, 
        refund_id: int, 
        merchant_id: int
    ) -> RefundResponse:
        """
        Отмена запроса на возврат (только для PENDING)
        
        Args:
            db: Сессия базы данных
            refund_id: ID запроса на возврат
            merchant_id: ID мерчанта
            
        Returns:
            Обновленный запрос на возврат
        """
        
        refund_request = db.query(RefundRequest).filter(
            and_(
                RefundRequest.id == refund_id,
                RefundRequest.merchant_id == merchant_id
            )
        ).first()
        
        if not refund_request:
            raise StandardError(
                error_code=ErrorCode.REFUND_NOT_FOUND,
                message="Запрос на возврат не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Проверяем, что возврат можно отменить
        if refund_request.status != RefundStatus.PENDING:
            raise StandardError(
                error_code=ErrorCode.REFUND_CANNOT_CANCEL,
                message=f"Невозможно отменить возврат в статусе {refund_request.status.value}",
                severity=ErrorSeverity.ERROR
            )
        
        # Отменяем возврат
        refund_request.status = RefundStatus.ABORTED
        refund_request.completed_at = datetime.now()
        
        db.commit()
        db.refresh(refund_request)
        
        # Запись в таймлайн
        TimelineService.record_event(
            db,
            payment_token=refund_request.refund_token,
            event_type='refund_cancelled',
            title='Возврат отменен',
            description=f'Отменен мерчантом',
            actor='merchant',
            source='refund_service',
            status='warning'
        )
        
        # Отправляем уведомление об отмене
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if merchant:
            RefundNotificationService.notify_refund_cancelled(db, refund_request, merchant, "Отменен мерчантом")
        
        logger.info(f"✅ Возврат {refund_id} отменен мерчантом {merchant_id}")
        
        return RefundResponse.from_orm(refund_request)
    
    def _validate_refund_creation(
        self, 
        refund_data: RefundCreate, 
        original_payment: MerchantPayment
    ) -> RefundValidationResult:
        """Валидация создания возврата"""
        
        validation = RefundValidationResult(valid=True)
        
        # Проверяем статус оригинального платежа
        logger.error(f"🔍 Проверка статуса платежа: {original_payment.status} (тип: {type(original_payment.status)})")
        if original_payment.status != "completed":
            validation.add_error(
                "original_payment_status", 
                f"Возврат возможен только для завершенных платежей. Текущий статус: {original_payment.status}",
                "invalid_payment_status"
            )
        
        # Проверяем сумму возврата
        if refund_data.amount <= 0:
            validation.add_error(
                "amount", 
                "Сумма возврата должна быть больше нуля",
                "invalid_amount"
            )
        
        if refund_data.amount > original_payment.amount:
            validation.add_error(
                "amount", 
                "Сумма возврата не может превышать сумму оригинального платежа",
                "amount_exceeds_original"
            )
        
        # Проверяем уже возвращенные суммы
        # Примечание: для валидации создания возврата мы не можем проверить существующие возвраты
        # так как у нас нет доступа к сессии БД. Эта проверка будет выполнена в двухфазном сервисе.
        existing_refunds = []
        
        total_refunded = sum(refund.amount for refund in existing_refunds)
        remaining_amount = original_payment.amount - total_refunded
        
        if refund_data.amount > remaining_amount:
            validation.add_error(
                "amount", 
                f"Сумма возврата превышает доступную для возврата сумму ({remaining_amount})",
                "amount_exceeds_remaining"
            )
        
        # Проверяем банковские коды
        if not original_payment.payer_bank_code:
            validation.add_error(
                "payer_bank_code", 
                "Банк покупателя не указан в оригинальном платеже",
                "missing_payer_bank"
            )
        
        # Проверяем причину возврата
        if not refund_data.reason or len(refund_data.reason.strip()) == 0:
            validation.add_error(
                "reason", 
                "Причина возврата обязательна",
                "missing_reason"
            )
        
        if len(refund_data.reason) > 500:
            validation.add_error(
                "reason", 
                "Причина возврата не может превышать 500 символов",
                "reason_too_long"
            )
        
        return validation
    
    # === АДМИНИСТРАТИВНЫЕ МЕТОДЫ ===
    
    def admin_get_refunds(
        self,
        db: Session,
        page: int = 1,
        per_page: int = 20,
        status: Optional[RefundStatus] = None,
        refund_type: Optional[RefundType] = None,
        merchant_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> tuple[list[RefundRequest], int]:
        """
        Административное получение списка возвратов с фильтрацией
        """
        
        # Базовый запрос
        query = db.query(RefundRequest)
        
        # Применяем фильтры
        if status:
            query = query.filter(RefundRequest.status == status)
        
        if refund_type:
            query = query.filter(RefundRequest.refund_type == refund_type)
        
        if merchant_id:
            query = query.filter(RefundRequest.merchant_id == merchant_id)
        
        if start_date:
            query = query.filter(RefundRequest.created_at >= start_date)
        
        if end_date:
            query = query.filter(RefundRequest.created_at <= end_date)
        
        # Сортируем по дате создания (новые сначала)
        query = query.order_by(desc(RefundRequest.created_at))
        
        # Подсчитываем общее количество
        total = query.count()
        
        # Применяем пагинацию
        offset = (page - 1) * per_page
        refunds = query.offset(offset).limit(per_page).all()
        
        return refunds, total
    
    def admin_get_refund_summary(
        self,
        db: Session,
        merchant_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> RefundSummary:
        """
        Административное получение сводки по возвратам
        """
        
        # Базовый запрос
        query = db.query(RefundRequest)
        
        # Применяем фильтры
        if merchant_id:
            query = query.filter(RefundRequest.merchant_id == merchant_id)
        
        if start_date:
            query = query.filter(RefundRequest.created_at >= start_date)
        
        if end_date:
            query = query.filter(RefundRequest.created_at <= end_date)
        
        # Общее количество возвратов
        total_refunds = query.count()
        
        # Общая сумма возвратов
        total_amount = db.query(db.func.sum(RefundRequest.amount)).filter(
            query.whereclause
        ).scalar() or 0.0
        
        # Количество завершенных возвратов
        completed_refunds = query.filter(RefundRequest.status == RefundStatus.COMPLETED).count()
        
        # Количество ожидающих возвратов
        pending_refunds = query.filter(RefundRequest.status == RefundStatus.PENDING).count()
        
        # Количество неудачных возвратов
        failed_refunds = query.filter(RefundRequest.status == RefundStatus.FAILED).count()
        
        return RefundSummary(
            total_refunds=total_refunds,
            total_amount=total_amount,
            currency="KGS",
            completed_refunds=completed_refunds,
            pending_refunds=pending_refunds,
            failed_refunds=failed_refunds
        )
    
    def admin_force_execute_refund(
        self,
        db: Session,
        refund_id: int,
        admin_id: int
    ) -> RefundRequest:
        """
        Принудительное выполнение возврата администратором
        """
        
        # Получаем возврат
        refund_request = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
        if not refund_request:
            raise StandardError(
                error_code=ErrorCode.REFUND_NOT_FOUND,
                message="Запрос на возврат не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Принудительно выполняем возврат
        refund_request.status = RefundStatus.COMPLETED
        refund_request.completed_at = datetime.now()
        
        db.commit()
        db.refresh(refund_request)
        
        return refund_request
    
    def admin_cancel_refund(
        self,
        db: Session,
        refund_id: int,
        admin_id: int
    ) -> RefundRequest:
        """
        Административная отмена возврата
        """
        
        # Получаем возврат
        refund_request = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
        if not refund_request:
            raise StandardError(
                error_code=ErrorCode.REFUND_NOT_FOUND,
                message="Запрос на возврат не найден",
                severity=ErrorSeverity.ERROR
            )
        
        # Отменяем возврат
        refund_request.status = RefundStatus.ABORTED
        refund_request.completed_at = datetime.now()
        
        db.commit()
        db.refresh(refund_request)
        
        return refund_request
    
    def get_merchant_refund_analytics(
        self,
        db: Session,
        merchant_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Аналитика возвратов для конкретного продавца
        """
        
        query = db.query(RefundRequest).filter(RefundRequest.merchant_id == merchant_id)
        
        if start_date:
            query = query.filter(RefundRequest.created_at >= start_date)
        
        if end_date:
            query = query.filter(RefundRequest.created_at <= end_date)
        
        refunds = query.all()
        
        # Статистика по статусам
        status_counts = {}
        for status in RefundStatus:
            status_counts[status.value] = len([r for r in refunds if r.status == status])
        
        # Статистика по типам
        type_counts = {}
        for refund_type in RefundType:
            type_counts[refund_type.value] = len([r for r in refunds if r.refund_type == refund_type])
        
        # Общая сумма
        total_amount = sum(r.amount for r in refunds if r.status == RefundStatus.COMPLETED)
        
        return {
            "merchant_id": merchant_id,
            "total_refunds": len(refunds),
            "status_counts": status_counts,
            "type_counts": type_counts,
            "total_amount": total_amount,
            "currency": "KGS"
        }
    
    def get_global_refund_analytics(
        self,
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Глобальная аналитика возвратов
        """
        
        query = db.query(RefundRequest)
        
        if start_date:
            query = query.filter(RefundRequest.created_at >= start_date)
        
        if end_date:
            query = query.filter(RefundRequest.created_at <= end_date)
        
        refunds = query.all()
        
        # Статистика по статусам
        status_counts = {}
        for status in RefundStatus:
            status_counts[status.value] = len([r for r in refunds if r.status == status])
        
        # Статистика по типам
        type_counts = {}
        for refund_type in RefundType:
            type_counts[refund_type.value] = len([r for r in refunds if r.refund_type == refund_type])
        
        # Общая сумма
        total_amount = sum(r.amount for r in refunds if r.status == RefundStatus.COMPLETED)
        
        # Уникальные мерчанты
        unique_merchants = len(set(r.merchant_id for r in refunds))
        
        return {
            "total_refunds": len(refunds),
            "unique_merchants": unique_merchants,
            "status_counts": status_counts,
            "type_counts": type_counts,
            "total_amount": total_amount,
            "currency": "KGS"
        }

    async def _auto_complete_refund_after_confirmation(
        self,
        db: Session,
        refund_request: RefundRequest,
        original_payment: MerchantPayment
    ):
        """
        Автоматическое завершение возврата после подтверждения в банках
        """
        
        logger.info(f"🔄 Запуск мониторинга подтверждения возврата {refund_request.id}")
        
        # Мониторим статус запросов в банках каждые 5 секунд
        max_wait_time = 300  # 5 минут максимум
        check_interval = 5   # проверяем каждые 5 секунд
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            try:
                # Проверяем, что возврат все еще в статусе PROCESSING
                fresh_refund = db.query(RefundRequest).filter(RefundRequest.id == refund_request.id).first()
                if not fresh_refund or fresh_refund.status != RefundStatus.PROCESSING:
                    logger.info(f"ℹ️ Возврат {refund_request.id} уже не в статусе PROCESSING, прекращаем мониторинг")
                    return
                
                # Проверяем статус запросов в банках через симулятор
                # В реальной системе здесь был бы API для проверки статуса
                from simulation.simulation_router import active_requests
                
                # Ищем запросы для этого возврата
                sender_requests = [req for req in active_requests.get("sender_bank", []) 
                                 if req.get("transaction_id") == refund_request.transaction_id]
                receiver_requests = [req for req in active_requests.get("receiver_bank", []) 
                                   if req.get("transaction_id") == refund_request.transaction_id]
                
                # Проверяем, что оба банка подтвердили запросы prepare
                sender_confirmed = any(req.get("phase") == "refund_prepare" and req.get("confirmed", False) for req in sender_requests)
                receiver_confirmed = any(req.get("phase") == "refund_prepare" and req.get("confirmed", False) for req in receiver_requests)
                
                if sender_confirmed and receiver_confirmed:
                    logger.info(f"✅ Оба банка подтвердили возврат {refund_request.id}, выполняем commit")
                    
                    # Создаем фиктивные результаты prepare для commit фазы
                    from app.services.two_phase_refund_service import RefundOperationResult, BankRole, TwoPhaseOperationStatus
                    
                    prepare_results = [
                        RefundOperationResult(
                            bank_code=refund_request.sender_bank_code,
                            bank_role=BankRole.SENDER,
                            operation="prepare",
                            success=True,
                            response_status=TwoPhaseOperationStatus.PREPARED
                        ),
                        RefundOperationResult(
                            bank_code=refund_request.receiver_bank_code,
                            bank_role=BankRole.RECEIVER,
                            operation="prepare",
                            success=True,
                            response_status=TwoPhaseOperationStatus.PREPARED
                        )
                    ]
                    
                    # Выполняем commit фазу двухфазного возврата
                    result = await two_phase_refund_service._execute_refund_commit_phase(
                        db, fresh_refund, prepare_results
                    )
                    
                    if result["success"]:
                        # Возврат успешно завершен
                        fresh_refund.status = RefundStatus.COMPLETED
                        fresh_refund.completed_at = datetime.now()
                        db.commit()
                        
                        # Отправляем уведомление об успешном завершении
                        merchant = db.query(Merchant).filter(Merchant.id == fresh_refund.merchant_id).first()
                        if merchant:
                            RefundNotificationService.notify_refund_completed(db, fresh_refund, merchant)
                        
                        logger.info(f"✅ Возврат {refund_request.id} успешно завершен после подтверждения банков")
                        
                        # Запись в таймлайн
                        TimelineService.record_event(
                            db,
                            payment_token=fresh_refund.refund_token,
                            event_type='refund_completed_after_confirmation',
                            title='Возврат завершен после подтверждения банков',
                            description=f'Возврат {fresh_refund.amount} {fresh_refund.currency} завершен после подтверждения обоих банков',
                            actor='system',
                            source='refund_service',
                            status='success'
                        )
                        return
                    else:
                        # Ошибка завершения
                        fresh_refund.status = RefundStatus.FAILED
                        db.commit()
                        
                        error_msg = result.get("error", "Неизвестная ошибка завершения возврата")
                        logger.error(f"❌ Ошибка завершения возврата {refund_request.id}: {error_msg}")
                        
                        # Запись в таймлайн
                        TimelineService.record_event(
                            db,
                            payment_token=fresh_refund.refund_token,
                            event_type='refund_completion_failed',
                            title='Ошибка завершения возврата',
                            description=f'Ошибка: {error_msg}',
                            actor='system',
                            source='refund_service',
                            status='error'
                        )
                        return
                
                # Ждем перед следующей проверкой
                await asyncio.sleep(check_interval)
                elapsed_time += check_interval
                
                logger.info(f"⏳ Ожидание подтверждения банков для возврата {refund_request.id}... ({elapsed_time}s)")
                
            except Exception as e:
                logger.error(f"❌ Ошибка мониторинга возврата {refund_request.id}: {e}")
                await asyncio.sleep(check_interval)
                elapsed_time += check_interval
        
        # Если время истекло, но банки не подтвердили
        logger.warning(f"⏰ Время ожидания подтверждения банков истекло для возврата {refund_request.id}")
        
        try:
            fresh_refund = db.query(RefundRequest).filter(RefundRequest.id == refund_request.id).first()
            if fresh_refund and fresh_refund.status == RefundStatus.PROCESSING:
                fresh_refund.status = RefundStatus.FAILED
                db.commit()
                
                # Запись в таймлайн
                TimelineService.record_event(
                    db,
                    payment_token=fresh_refund.refund_token,
                    event_type='refund_timeout',
                    title='Таймаут ожидания подтверждения банков',
                    description=f'Банки не подтвердили возврат в течение {max_wait_time} секунд',
                    actor='system',
                    source='refund_service',
                    status='error'
                )
        except Exception as commit_error:
            logger.error(f"❌ Не удалось обновить статус возврата {refund_request.id}: {commit_error}")

# Создаем глобальный экземпляр сервиса
refund_service = RefundService()
