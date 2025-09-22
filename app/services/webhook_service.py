import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.payment import PaymentRequest, TransactionRecord
from app.models.merchant import Merchant, MerchantPayment, QRCode
from app.schemas.payment import PaymentStatusWebhook
from app.services.token_service import SecureTokenService
from app.services.billing_service import BillingService
from app.services.merchant_auth_service import MerchantAuthService
from app.services.timeline_service import TimelineService
from app.services.bank_alerts_service import bank_alerts_service, AlertType
from app.services.realtime_monitoring_service import AlertSeverity
from app.services.bank_alerts_service import bank_alerts_service, AlertType
from app.services.realtime_monitoring_service import AlertSeverity

class WebhookService:
    """Сервис для идемпотентной обработки webhook"""
    
    @staticmethod
    def process_payment_webhook(
        db: Session,
        webhook_data: PaymentStatusWebhook,
        bank_code: str,
        token: str
    ) -> Dict[str, Any]:
        """
        Идемпотентная обработка webhook о статусе платежа
        
        Args:
            db: Сессия базы данных
            webhook_data: Данные webhook
            bank_code: Код банка, отправившего webhook
            token: Полный токен (с подписью)
            
        Returns:
            dict: Результат обработки
        """
        
        # Извлекаем UUID из токена
        token_uuid = SecureTokenService.extract_uuid_from_token(token)
        if not token_uuid:
            return {
                "success": False,
                "message": "Invalid token format",
                "status_code": 400
            }
        
        # Проверяем существование транзакции для идемпотентности
        existing_transaction = db.query(TransactionRecord).filter(
            TransactionRecord.transaction_id == webhook_data.transaction_id
        ).first()
        
        if existing_transaction:
            # Транзакция уже обработана - возвращаем успешный ответ
            return {
                "success": True,
                "message": "Transaction already processed",
                "status_code": 200,
                "idempotent": True,
                "original_processed_at": existing_transaction.processed_at.isoformat()
            }
        
        # Ищем платежный запрос
        payment_request = db.query(PaymentRequest).filter(
            PaymentRequest.token == token_uuid
        ).first()
        
        if not payment_request:
            return {
                "success": False,
                "message": "Payment request not found",
                "status_code": 404
            }
        
        # Создаем запись о транзакции для идемпотентности
        try:
            transaction_record = TransactionRecord(
                transaction_id=webhook_data.transaction_id,
                payment_token=token_uuid,
                bank_code=bank_code,
                amount=webhook_data.amount,
                payer_phone=webhook_data.payer_phone,
                status=webhook_data.status,
                webhook_data=json.dumps(webhook_data.dict(), default=str)
            )
            
            db.add(transaction_record)
            db.flush()  # Проверяем уникальность transaction_id
            # Событие: транзакция зафиксирована (после webhook_received)
            try:
                TimelineService.record_event(
                    db,
                    payment_token=token_uuid,
                    transaction_id=webhook_data.transaction_id,
                    event_type='transaction_recorded',
                    title='Транзакция зафиксирована',
                    description=f'ID {webhook_data.transaction_id}, сумма {webhook_data.amount}',
                    actor='system',
                    source='service',
                    status='info',
                    metadata={"bank_code": bank_code}
                )
            except Exception:
                pass
            
        except IntegrityError:
            # Конкурентный запрос - транзакция уже создана
            db.rollback()
            
            existing_transaction = db.query(TransactionRecord).filter(
                TransactionRecord.transaction_id == webhook_data.transaction_id
            ).first()
            
            # Создаем WARNING алерт о дублировании transaction_id
            try:
                bank_alerts_service.create_alert(
                    alert_type=AlertType.DUPLICATE_TRANSACTION_ID,
                    severity=AlertSeverity.WARNING,
                    bank_code=bank_code,
                    title="DUPLICATE_TRANSACTION_ID",
                    message=f"Received duplicate transaction_id {webhook_data.transaction_id}",
                    details={
                        "transaction_id": webhook_data.transaction_id,
                        "payment_token": token_uuid,
                        "bank_code": bank_code,
                        "original_processed_at": existing_transaction.processed_at.isoformat() if existing_transaction else None
                    }
                )
            except Exception:
                pass

            return {
                "success": True,
                "message": "Transaction processed concurrently",
                "status_code": 200,
                "idempotent": True,
                "original_processed_at": existing_transaction.processed_at.isoformat()
            }
        
        # Обновляем статус платежа
        # CRITICAL: Проверка несовпадения суммы при фиксированной сумме в QR
        if payment_request.amount is not None:
            try:
                expected = float(payment_request.amount)
                actual = float(webhook_data.amount)
            except Exception:
                expected = payment_request.amount
                actual = webhook_data.amount
            if expected != actual:
                # Создаем критический алерт
                try:
                    bank_alerts_service.create_alert(
                        alert_type=AlertType.PAYMENT_MISMATCH,
                        severity=AlertSeverity.CRITICAL,
                        bank_code=bank_code,
                        title="PAYMENT_MISMATCH",
                        message=f"Сумма из webhook ({actual}) не совпадает с ожидаемой из QR ({expected}).",
                        details={
                            "token": token_uuid,
                            "transaction_id": webhook_data.transaction_id,
                            "expected_amount": expected,
                            "actual_amount": actual,
                            "currency": payment_request.currency,
                        }
                    )
                except Exception:
                    pass
                return {
                    "success": False,
                    "message": "Payment amount mismatch",
                    "status_code": 400
                }

        # Переносим outlet_id из PaymentRequest/QRCode в запись платежа
        try:
            # попытаемся извлечь outlet_id из QRCode или самого payment_request
            outlet_id = None
            try:
                from app.models.merchant import QRCode
                qr = db.query(QRCode).filter(QRCode.qr_token == payment_request.token).first()
                outlet_id = getattr(qr, 'outlet_id', None)
            except Exception:
                outlet_id = None
            if getattr(payment_request, 'outlet_id', None):
                outlet_id = payment_request.outlet_id
            if outlet_id:
                transaction_record.outlet_id = outlet_id
                db.commit()
        except Exception:
            pass

        result = WebhookService._update_payment_status(
            payment_request, webhook_data
        )
        
        if not result["success"]:
            db.rollback()
            return result
        
        # Обрабатываем уведомления для продавцов
        merchant_notification_result = WebhookService._process_merchant_notification(
            db, payment_request, webhook_data, transaction_record
        )
        
        # Создаем биллинговую запись для успешных платежей
        if webhook_data.status == "success" and result["updated"]:
            try:
                billing_record = BillingService.create_billing_record(
                    db=db,
                    payment_request=payment_request,
                    transaction_record=transaction_record,
                    webhook_data=webhook_data,
                    payer_bank_code=bank_code  # Банк, отправивший webhook
                )
                result["billing_record_id"] = billing_record.id
                # Событие: создана биллинговая запись (после transaction_recorded)
                try:
                    TimelineService.record_event(
                        db,
                        payment_token=token_uuid,
                        transaction_id=webhook_data.transaction_id,
                        event_type='billing_recorded',
                        title='Создана биллинговая запись',
                        description=f'transaction {billing_record.transaction_id}, {billing_record.amount} {billing_record.currency}',
                        actor='system',
                        source='service',
                        status='success'
                    )
                except Exception:
                    pass
            except Exception as e:
                # Логируем ошибку, но не прерываем процесс
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to create billing record: {e}")
                result["billing_error"] = str(e)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Payment status updated: {webhook_data.status}",
            "status_code": 200,
            "idempotent": False,
            "payment_updated": result["updated"],
            "merchant_notified": merchant_notification_result.get("notified", False)
        }
    
    @staticmethod
    def _process_merchant_notification(
        db: Session,
        payment_request: PaymentRequest,
        webhook_data: PaymentStatusWebhook,
        transaction_record: TransactionRecord
    ) -> Dict[str, Any]:
        """
        Обработка уведомлений для продавцов
        
        Args:
            db: Сессия базы данных
            payment_request: Платежный запрос
            webhook_data: Данные webhook
            transaction_record: Запись о транзакции
            
        Returns:
            dict: Результат обработки уведомлений
        """
        
        # Проверяем, связан ли платеж с продавцом
        if not payment_request.merchant_id:
            return {"notified": False, "reason": "No merchant associated"}
        
        try:
            # Получаем информацию о продавце
            merchant = db.query(Merchant).filter(
                Merchant.id == payment_request.merchant_id
            ).first()
            
            if not merchant:
                return {"notified": False, "reason": "Merchant not found"}
            
            # Создаем или обновляем запись о платеже продавца
            # Ищем по transaction_id, так как payment_request_id не существует в модели
            merchant_payment = db.query(MerchantPayment).filter(
                MerchantPayment.transaction_id == webhook_data.transaction_id,
                MerchantPayment.merchant_id == merchant.id
            ).first()
            
            # Маппинг статуса из webhook -> статус продавца
            status_in = (webhook_data.status or "").lower()
            if status_in in ("success", "completed"):
                mapped_status = "completed"
            elif status_in == "failed":
                mapped_status = "failed"
            else:
                mapped_status = "pending"

            if not merchant_payment:
                # Создаем новую запись о платеже продавца
                merchant_payment = MerchantPayment(
                    merchant_id=merchant.id,
                    qr_code_id=None,  # Заполним ниже, если найдём QR-код
                    outlet_id=payment_request.outlet_id,  # Берем из payment_request
                    amount=webhook_data.amount,
                    currency=payment_request.currency,
                    status=mapped_status,
                    payer_phone=webhook_data.payer_phone,
                    payer_bank_code=transaction_record.bank_code,
                    sender_account=payment_request.sender_account,  # Счет плательщика из PaymentRequest
                    transaction_id=webhook_data.transaction_id,
                    bank_transaction_id=webhook_data.bank_transaction_id,  # ID банка
                    paid_at=datetime.now() if mapped_status == "completed" else None
                )
                db.add(merchant_payment)
            else:
                # Обновляем существующую запись
                merchant_payment.status = mapped_status
                merchant_payment.amount = webhook_data.amount
                merchant_payment.payer_phone = webhook_data.payer_phone
                merchant_payment.transaction_id = webhook_data.transaction_id
                merchant_payment.bank_transaction_id = webhook_data.bank_transaction_id  # ID банка
                merchant_payment.payer_bank_code = transaction_record.bank_code
                merchant_payment.sender_account = payment_request.sender_account  # Счет плательщика из PaymentRequest
                merchant_payment.outlet_id = payment_request.outlet_id  # Обновляем outlet_id
                merchant_payment.paid_at = datetime.now() if mapped_status == "completed" else merchant_payment.paid_at
            
            # Ищем связанный QR-код (если платеж был через QR-код продавца)
            qr_code = db.query(QRCode).filter(
                QRCode.qr_token == payment_request.token
            ).first()
            
            if qr_code and qr_code.merchant_id == merchant.id:
                merchant_payment.qr_code_id = qr_code.id
                
                # Обновляем счетчик использований QR-кода
                if webhook_data.status == "success":
                    qr_code.current_uses += 1
                    
                    # Деактивируем QR-код, если достигнут лимит использований
                    if qr_code.max_uses and qr_code.current_uses >= qr_code.max_uses:
                        qr_code.is_active = False
            
            # Отправляем уведомление продавцу (здесь можно добавить email, SMS, webhook)
            notification_sent = WebhookService._send_merchant_notification(
                merchant, merchant_payment, webhook_data
            )
            
            return {
                "notified": True,
                "notification_sent": notification_sent,
                "merchant_payment_id": merchant_payment.id
            }
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing merchant notification: {e}")
            return {"notified": False, "error": str(e)}
    
    @staticmethod
    def _send_merchant_notification(
        merchant: Merchant,
        merchant_payment: MerchantPayment,
        webhook_data: PaymentStatusWebhook
    ) -> bool:
        """
        Отправка уведомления продавцу
        
        Args:
            merchant: Объект продавца
            merchant_payment: Запись о платеже продавца
            webhook_data: Данные webhook
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            # Здесь можно реализовать отправку уведомлений:
            # - Email уведомления
            # - SMS уведомления
            # - Webhook уведомления на URL продавца
            # - Push уведомления в мобильное приложение
            
            # Пример логирования уведомления
            import logging
            logger = logging.getLogger(__name__)
            
            notification_message = f"""
            Новый платеж для {merchant.name}:
            - Сумма: {merchant_payment.amount} {merchant_payment.currency}
            - Статус: {merchant_payment.status}
            - Плательщик: {merchant_payment.payer_phone}
            - Транзакция: {merchant_payment.transaction_id}
            """
            
            logger.info(f"Merchant notification: {notification_message}")
            
            # TODO: Реализовать реальную отправку уведомлений
            # - Email: merchant.email
            # - Webhook: merchant.webhook_url (если настроен)
            # - SMS: merchant.phone
            
            return True
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to send merchant notification: {e}")
            return False
    
    @staticmethod
    def _update_payment_status(
        payment_request: PaymentRequest,
        webhook_data: PaymentStatusWebhook
    ) -> Dict[str, Any]:
        """
        Обновление статуса платежа
        
        Args:
            payment_request: Объект платежного запроса
            webhook_data: Данные webhook
            
        Returns:
            dict: Результат обновления
        """
        
        try:
            if webhook_data.status == "success":
                # Проверяем, не был ли платеж уже оплачен
                if payment_request.is_paid:
                    return {
                        "success": True,
                        "updated": False,
                        "message": "Payment already marked as paid"
                    }
                
                # Обновляем статус на успешный
                payment_request.is_paid = True
                payment_request.is_used = True
                payment_request.transaction_id = webhook_data.transaction_id
                payment_request.payer_phone = webhook_data.payer_phone
                payment_request.paid_amount = webhook_data.amount
                payment_request.paid_at = webhook_data.timestamp
                
                return {
                    "success": True,
                    "updated": True,
                    "message": "Payment marked as successful"
                }
                
            elif webhook_data.status == "failed":
                # Обрабатываем неудачный платеж
                payment_request.transaction_id = webhook_data.transaction_id
                # is_used остается False для возможности повторной оплаты
                
                return {
                    "success": True,
                    "updated": True,
                    "message": "Payment marked as failed"
                }
                
            else:
                return {
                    "success": False,
                    "updated": False,
                    "message": f"Unknown payment status: {webhook_data.status}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "updated": False,
                "message": f"Error updating payment status: {str(e)}"
            }
    
    @staticmethod
    def get_transaction_history(
        db: Session,
        transaction_id: Optional[str] = None,
        payment_token: Optional[str] = None,
        bank_code: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """
        Получение истории транзакций для мониторинга
        
        Args:
            db: Сессия базы данных
            transaction_id: ID конкретной транзакции
            payment_token: Токен платежа
            bank_code: Код банка
            limit: Лимит записей
            
        Returns:
            list: Список транзакций
        """
        
        query = db.query(TransactionRecord)
        
        if transaction_id:
            query = query.filter(TransactionRecord.transaction_id == transaction_id)
        
        if payment_token:
            query = query.filter(TransactionRecord.payment_token == payment_token)
        
        if bank_code:
            query = query.filter(TransactionRecord.bank_code == bank_code)
        
        return query.order_by(TransactionRecord.processed_at.desc()).limit(limit).all()
    
    @staticmethod
    def get_merchant_payment_history(
        db: Session,
        merchant: Merchant,
        skip: int = 0,
        limit: int = 100
    ) -> list:
        """
        Получение истории платежей для конкретного продавца
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            skip: Количество записей для пропуска
            limit: Лимит записей
            
        Returns:
            list: Список платежей продавца
        """
        
        return db.query(MerchantPayment).filter(
            MerchantPayment.merchant_id == merchant.id
        ).order_by(MerchantPayment.processed_at.desc()).offset(skip).limit(limit).all()
