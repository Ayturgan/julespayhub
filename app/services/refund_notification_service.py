"""
Сервис уведомлений для возвратов
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
import logging
import json

from app.models.merchant import Merchant
from app.models.refund import RefundRequest, RefundStatus
from app.services.bank_alerts_service import NotificationChannel, NotificationRecipient
from app.core.config import settings

logger = logging.getLogger(__name__)

class RefundNotificationService:
    """Сервис для отправки уведомлений о возвратах"""
    
    @staticmethod
    def notify_refund_created(
        db: Session,
        refund: RefundRequest,
        merchant: Merchant
    ) -> bool:
        """
        Уведомление о создании возврата
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            merchant: Объект продавца
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            # Формируем сообщение
            subject = f"Возврат создан - {refund.refund_token}"
            message = f"""
            Создан новый возврат:
            
            Токен возврата: {refund.refund_token}
            Сумма: {refund.amount} {refund.currency}
            Тип: {refund.refund_type.value}
            Причина: {refund.reason}
            Статус: {refund.status.value}
            Дата создания: {refund.created_at.strftime('%Y-%m-%d %H:%M:%S')}
            
            Оригинальный платеж: {refund.original_payment_id}
            """
            
            # Отправляем уведомление продавцу
            success = RefundNotificationService._send_merchant_notification(
                merchant=merchant,
                subject=subject,
                message=message,
                notification_type="refund_created"
            )
            
            logger.info(f"Refund creation notification sent to merchant {merchant.id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending refund creation notification: {e}")
            return False
    
    @staticmethod
    def notify_refund_execution_started(
        db: Session,
        refund: RefundRequest,
        merchant: Merchant
    ) -> bool:
        """
        Уведомление о начале выполнения возврата
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            merchant: Объект продавца
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            subject = f"Выполнение возврата начато - {refund.refund_token}"
            message = f"""
            Начато выполнение возврата:
            
            Токен возврата: {refund.refund_token}
            Сумма: {refund.amount} {refund.currency}
            Статус: {refund.status.value}
            
            Процесс выполняется через двухфазный протокол.
            Вы получите уведомление по завершении.
            """
            
            success = RefundNotificationService._send_merchant_notification(
                merchant=merchant,
                subject=subject,
                message=message,
                notification_type="refund_execution_started"
            )
            
            logger.info(f"Refund execution started notification sent to merchant {merchant.id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending refund execution started notification: {e}")
            return False
    
    @staticmethod
    def notify_refund_completed(
        db: Session,
        refund: RefundRequest,
        merchant: Merchant
    ) -> bool:
        """
        Уведомление о завершении возврата
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            merchant: Объект продавца
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            subject = f"Возврат выполнен - {refund.refund_token}"
            message = f"""
            Возврат успешно выполнен:
            
            Токен возврата: {refund.refund_token}
            Сумма: {refund.amount} {refund.currency}
            Статус: {refund.status.value}
            Дата завершения: {refund.completed_at.strftime('%Y-%m-%d %H:%M:%S') if refund.completed_at else 'N/A'}
            
            Деньги возвращены покупателю.
            """
            
            success = RefundNotificationService._send_merchant_notification(
                merchant=merchant,
                subject=subject,
                message=message,
                notification_type="refund_completed"
            )
            
            logger.info(f"Refund completed notification sent to merchant {merchant.id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending refund completed notification: {e}")
            return False
    
    @staticmethod
    def notify_refund_failed(
        db: Session,
        refund: RefundRequest,
        merchant: Merchant,
        error_message: str
    ) -> bool:
        """
        Уведомление о неудачном возврате
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            merchant: Объект продавца
            error_message: Сообщение об ошибке
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            subject = f"Ошибка выполнения возврата - {refund.refund_token}"
            message = f"""
            Возврат не выполнен:
            
            Токен возврата: {refund.refund_token}
            Сумма: {refund.amount} {refund.currency}
            Статус: {refund.status.value}
            Ошибка: {error_message}
            
            Обратитесь в службу поддержки для решения проблемы.
            """
            
            success = RefundNotificationService._send_merchant_notification(
                merchant=merchant,
                subject=subject,
                message=message,
                notification_type="refund_failed"
            )
            
            logger.info(f"Refund failed notification sent to merchant {merchant.id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending refund failed notification: {e}")
            return False
    
    @staticmethod
    def notify_refund_cancelled(
        db: Session,
        refund: RefundRequest,
        merchant: Merchant,
        reason: str
    ) -> bool:
        """
        Уведомление об отмене возврата
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            merchant: Объект продавца
            reason: Причина отмены
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            subject = f"Возврат отменен - {refund.refund_token}"
            message = f"""
            Возврат отменен:
            
            Токен возврата: {refund.refund_token}
            Сумма: {refund.amount} {refund.currency}
            Статус: {refund.status.value}
            Причина отмены: {reason}
            
            Возврат больше не будет выполнен.
            """
            
            success = RefundNotificationService._send_merchant_notification(
                merchant=merchant,
                subject=subject,
                message=message,
                notification_type="refund_cancelled"
            )
            
            logger.info(f"Refund cancelled notification sent to merchant {merchant.id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending refund cancelled notification: {e}")
            return False
    
    @staticmethod
    def notify_admin_refund_action(
        db: Session,
        refund: RefundRequest,
        admin_id: int,
        action: str,
        description: str
    ) -> bool:
        """
        Уведомление администратора о действии с возвратом
        
        Args:
            db: Сессия базы данных
            refund: Объект возврата
            admin_id: ID администратора
            action: Тип действия
            description: Описание действия
            
        Returns:
            bool: Успешность отправки уведомления
        """
        
        try:
            subject = f"Административное действие с возвратом - {refund.refund_token}"
            message = f"""
            Административное действие с возвратом:
            
            Токен возврата: {refund.refund_token}
            Действие: {action}
            Описание: {description}
            Администратор: {admin_id}
            Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            
            Сумма: {refund.amount} {refund.currency}
            Продавец: {refund.merchant_id}
            """
            
            # Отправляем уведомление администратору
            success = RefundNotificationService._send_admin_notification(
                admin_id=admin_id,
                subject=subject,
                message=message,
                notification_type="admin_refund_action"
            )
            
            logger.info(f"Admin refund action notification sent to admin {admin_id}: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Error sending admin refund action notification: {e}")
            return False
    
    @staticmethod
    def _send_merchant_notification(
        merchant: Merchant,
        subject: str,
        message: str,
        notification_type: str
    ) -> bool:
        """
        Отправка уведомления продавцу
        
        Args:
            merchant: Объект продавца
            subject: Тема уведомления
            message: Текст уведомления
            notification_type: Тип уведомления
            
        Returns:
            bool: Успешность отправки
        """
        
        try:
            # Проверяем настройки уведомлений продавца
            # Временно отключаем проверку, так как поля email_notifications и sms_notifications не существуют
            # if not merchant.email_notifications and not merchant.sms_notifications:
            #     logger.info(f"Merchant {merchant.id} has notifications disabled")
            #     return False
            
            # Формируем получателей
            recipients = []
            
            # Временно включаем уведомления для всех продавцов
            if merchant.email:
                recipients.append(
                    NotificationRecipient(
                        name=merchant.name,
                        address=merchant.email,
                        channel=NotificationChannel.EMAIL
                    )
                )
            
            if merchant.phone:
                recipients.append(
                    NotificationRecipient(
                        name=merchant.name,
                        address=merchant.phone,
                        channel=NotificationChannel.SMS
                    )
                )
            
            if not recipients:
                logger.warning(f"No valid notification channels for merchant {merchant.id}")
                return False
            
            # Отправляем уведомления
            success_count = 0
            for recipient in recipients:
                try:
                    if recipient.channel == NotificationChannel.EMAIL:
                        success = RefundNotificationService._send_email(
                            recipient=recipient,
                            subject=subject,
                            message=message
                        )
                    elif recipient.channel == NotificationChannel.SMS:
                        success = RefundNotificationService._send_sms(
                            recipient=recipient,
                            message=f"{subject}\n\n{message}"
                        )
                    else:
                        logger.warning(f"Unsupported notification channel: {recipient.channel}")
                        continue
                    
                    if success:
                        success_count += 1
                        
                except Exception as e:
                    logger.error(f"Error sending notification to {recipient.address}: {e}")
            
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Error in _send_merchant_notification: {e}")
            return False
    
    @staticmethod
    def _send_admin_notification(
        admin_id: int,
        subject: str,
        message: str,
        notification_type: str
    ) -> bool:
        """
        Отправка уведомления администратору
        
        Args:
            admin_id: ID администратора
            subject: Тема уведомления
            message: Текст уведомления
            notification_type: Тип уведомления
            
        Returns:
            bool: Успешность отправки
        """
        
        try:
            # Для администраторов используем внутренние уведомления
            recipient = NotificationRecipient(
                name=f"Admin_{admin_id}",
                address=f"admin_{admin_id}@qrpayhub.com",
                channel=NotificationChannel.INTERNAL
            )
            
            success = RefundNotificationService._send_internal(
                recipient=recipient,
                subject=subject,
                message=message
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Error in _send_admin_notification: {e}")
            return False
    
    @staticmethod
    def _send_email(recipient: NotificationRecipient, subject: str, message: str) -> bool:
         """Отправка email уведомления"""
         try:
             # Здесь должна быть интеграция с email сервисом
             # Пока просто логируем
             logger.info(f"Email notification to {recipient.address}: {subject}")
             logger.debug(f"Email content: {message}")
             return True
         except Exception as e:
             logger.error(f"Error sending email: {e}")
             return False
    
    @staticmethod
    def _send_sms(recipient: NotificationRecipient, message: str) -> bool:
         """Отправка SMS уведомления"""
         try:
             # Здесь должна быть интеграция с SMS сервисом
             # Пока просто логируем
             logger.info(f"SMS notification to {recipient.address}: {message[:50]}...")
             return True
         except Exception as e:
             logger.error(f"Error sending SMS: {e}")
             return False
    
    @staticmethod
    def _send_internal(recipient: NotificationRecipient, subject: str, message: str) -> bool:
         """Отправка внутреннего уведомления"""
         try:
             # Здесь должна быть интеграция с внутренней системой уведомлений
             # Пока просто логируем
             logger.info(f"Internal notification to {recipient.address}: {subject}")
             logger.debug(f"Internal content: {message}")
             return True
         except Exception as e:
             logger.error(f"Error sending internal notification: {e}")
             return False

# Глобальный экземпляр сервиса уведомлений
refund_notification_service = RefundNotificationService()
