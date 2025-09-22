from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from app.models.payment import BillingRecord, PaymentRequest, TransactionRecord
from app.models.merchant import Merchant, MerchantPayment, QRCode
from app.models.refund import RefundRequest, RefundOperation, RefundStatus, RefundType
from app.schemas.payment import PaymentStatusWebhook
from app.schemas.merchant import MerchantStats, PaymentSummary
from app.schemas.refund import RefundSummary
import logging

logger = logging.getLogger(__name__)

class BillingService:
    """Сервис для биллинговой системы и финансовой отчетности"""
    
    @staticmethod
    def create_billing_record(
        db: Session,
        payment_request: PaymentRequest,
        transaction_record: TransactionRecord,
        webhook_data: PaymentStatusWebhook,
        payer_bank_code: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> BillingRecord:
        """
        Создание биллинговой записи для успешного платежа
        
        Args:
            db: Сессия базы данных
            payment_request: Запрос на платеж
            transaction_record: Запись о транзакции
            webhook_data: Данные webhook от банка
            payer_bank_code: Код банка плательщика
            ip_address: IP адрес при создании платежа
            user_agent: User-Agent при создании платежа
            
        Returns:
            BillingRecord: Созданная биллинговая запись
        """
        
        # Проверяем, что запись еще не создана (идемпотентность)
        existing_record = db.query(BillingRecord).filter(
            BillingRecord.transaction_id == webhook_data.transaction_id
        ).first()
        
        if existing_record:
            logger.info(f"Billing record already exists for transaction {webhook_data.transaction_id}")
            return existing_record
        
        # Создаем биллинговую запись
        billing_record = BillingRecord(
            payment_token=payment_request.token,
            transaction_id=webhook_data.transaction_id,
            amount=webhook_data.amount,
            currency=payment_request.currency,
            payer_phone=webhook_data.payer_phone,
            payer_bank_code=payer_bank_code,
            receiver_account=payment_request.receiver_account,
            receiver_bank_code=payment_request.receiver_bank_code,
            receiver_name=payment_request.receiver_name,
            payment_description=payment_request.description,
            payment_reference=payment_request.payment_reference,
            payment_date=webhook_data.timestamp,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(billing_record)
        db.commit()
        db.refresh(billing_record)
        
        logger.info(
            f"Created billing record for transaction {webhook_data.transaction_id}, "
            f"amount: {webhook_data.amount} {payment_request.currency}"
        )
        
        return billing_record

    @staticmethod
    def create_refund_billing_record(
        db: Session,
        refund_request: RefundRequest,
        refund_operation: RefundOperation,
        merchant: Merchant,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> BillingRecord:
        """
        Создание биллинговой записи для возврата
        
        Args:
            db: Сессия базы данных
            refund_request: Запрос на возврат
            refund_operation: Операция возврата
            merchant: Продавец
            ip_address: IP адрес при создании возврата
            user_agent: User-Agent при создании возврата
            
        Returns:
            BillingRecord: Созданная биллинговая запись для возврата
        """
        
        # Проверяем, что запись еще не создана (идемпотентность)
        existing_record = db.query(BillingRecord).filter(
            BillingRecord.transaction_id == refund_operation.operation_id
        ).first()
        
        if existing_record:
            logger.info(f"Refund billing record already exists for operation {refund_operation.operation_id}")
            return existing_record
        
        # Создаем биллинговую запись для возврата
        billing_record = BillingRecord(
            payment_token=refund_request.refund_token,
            transaction_id=refund_operation.operation_id,
            amount=-refund_request.amount,  # Отрицательная сумма для возврата
            currency=refund_request.currency,
            payer_phone=merchant.phone,  # Продавец становится плательщиком
            payer_bank_code=merchant.bank_code,
            receiver_account=refund_request.original_payer_phone,  # Изначальный покупатель
            receiver_bank_code=refund_request.original_payer_bank_code,
            receiver_name=refund_request.original_payer_name,
            payment_description=f"Возврат: {refund_request.reason}",
            payment_reference=f"REFUND_{refund_request.refund_token}",
            payment_date=refund_operation.completed_at or datetime.utcnow(),
            ip_address=ip_address,
            user_agent=user_agent,
            is_refund=True,  # Новое поле для обозначения возврата
            original_payment_id=refund_request.original_payment_id
        )
        
        db.add(billing_record)
        db.commit()
        db.refresh(billing_record)
        
        logger.info(
            f"Created refund billing record for operation {refund_operation.operation_id}, "
            f"amount: -{refund_request.amount} {refund_request.currency}"
        )
        
        return billing_record

    @staticmethod
    def get_merchant_billing_summary(
        db: Session,
        merchant: Merchant,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> MerchantStats:
        """
        Получение сводки по биллингу для продавца (включая возвраты)
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            start_date: Начальная дата
            end_date: Конечная дата
            
        Returns:
            MerchantStats: Сводка по биллингу продавца
        """
        
        # По умолчанию за последние 30 дней
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()
        
        # Базовый запрос для платежей
        base_query = db.query(BillingRecord).filter(
            and_(
                BillingRecord.receiver_account == merchant.phone,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        )
        
        # Статистика по платежам (положительные суммы)
        payments_query = base_query.filter(BillingRecord.amount > 0)
        total_payments = payments_query.count()
        total_payment_amount = payments_query.with_entities(
            func.sum(BillingRecord.amount)
        ).scalar() or 0.0
        
        # Статистика по возвратам (отрицательные суммы)
        refunds_query = base_query.filter(BillingRecord.amount < 0)
        total_refunds = refunds_query.count()
        total_refund_amount = abs(refunds_query.with_entities(
            func.sum(BillingRecord.amount)
        ).scalar() or 0.0)
        
        # Чистая сумма (платежи - возвраты)
        net_amount = total_payment_amount - total_refund_amount
        
        # Статистика по дням
        daily_stats = db.query(
            func.date(BillingRecord.payment_date).label('date'),
            func.count(BillingRecord.id).label('count'),
            func.sum(BillingRecord.amount).label('amount')
        ).filter(
            and_(
                BillingRecord.receiver_account == merchant.phone,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).group_by(
            func.date(BillingRecord.payment_date)
        ).order_by(
            func.date(BillingRecord.payment_date)
        ).all()
        
        return MerchantStats(
            merchant_id=merchant.id,
            total_payments=total_payments,
            total_payment_amount=total_payment_amount,
            total_refunds=total_refunds,
            total_refund_amount=total_refund_amount,
            net_amount=net_amount,
            currency=merchant.currency or "KGS",
            period_start=start_date,
            period_end=end_date,
            daily_stats=[
                PaymentSummary(
                    date=stat.date,
                    count=stat.count,
                    amount=stat.amount
                ) for stat in daily_stats
            ]
        )

    @staticmethod
    def get_refund_billing_summary(
        db: Session,
        merchant_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> RefundSummary:
        """
        Получение сводки по возвратам для продавца
        
        Args:
            db: Сессия базы данных
            merchant_id: ID продавца
            start_date: Начальная дата
            end_date: Конечная дата
            
        Returns:
            RefundSummary: Сводка по возвратам
        """
        
        # По умолчанию за последние 30 дней
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()
        
        # Запрос возвратов продавца
        refunds_query = db.query(RefundRequest).filter(
            and_(
                RefundRequest.merchant_id == merchant_id,
                RefundRequest.created_at >= start_date,
                RefundRequest.created_at <= end_date
            )
        )
        
        # Общая статистика
        total_refunds = refunds_query.count()
        
        # Статистика по статусам
        completed_refunds = refunds_query.filter(RefundRequest.status == RefundStatus.COMPLETED).count()
        pending_refunds = refunds_query.filter(RefundRequest.status == RefundStatus.PENDING).count()
        failed_refunds = refunds_query.filter(RefundRequest.status == RefundStatus.FAILED).count()
        cancelled_refunds = refunds_query.filter(RefundRequest.status == RefundStatus.CANCELLED).count()
        
        # Суммы по статусам
        completed_amount = refunds_query.filter(
            RefundRequest.status == RefundStatus.COMPLETED
        ).with_entities(
            func.sum(RefundRequest.amount)
        ).scalar() or 0.0
        
        pending_amount = refunds_query.filter(
            RefundRequest.status == RefundStatus.PENDING
        ).with_entities(
            func.sum(RefundRequest.amount)
        ).scalar() or 0.0
        
        # Статистика по типам возвратов
        full_refunds = refunds_query.filter(RefundRequest.refund_type == RefundType.FULL).count()
        partial_refunds = refunds_query.filter(RefundRequest.refund_type == RefundType.PARTIAL).count()
        
        # Получаем валюту продавца
        merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
        currency = merchant.currency if merchant else "KGS"
        
        return RefundSummary(
            total_refunds=total_refunds,
            completed_refunds=completed_refunds,
            pending_refunds=pending_refunds,
            failed_refunds=failed_refunds,
            cancelled_refunds=cancelled_refunds,
            total_amount=completed_amount + pending_amount,
            completed_amount=completed_amount,
            pending_amount=pending_amount,
            full_refunds=full_refunds,
            partial_refunds=partial_refunds,
            currency=currency,
            period_start=start_date,
            period_end=end_date
        )

    @staticmethod
    def get_global_billing_summary(
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Получение глобальной сводки по биллингу (включая возвраты)
        
        Args:
            db: Сессия базы данных
            start_date: Начальная дата
            end_date: Конечная дата
            
        Returns:
            Dict: Глобальная сводка по биллингу
        """
        
        # По умолчанию за последние 30 дней
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()
        
        # Общая статистика по платежам
        total_payments = db.query(BillingRecord).filter(
            and_(
                BillingRecord.amount > 0,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).count()
        
        total_payment_amount = db.query(BillingRecord).filter(
            and_(
                BillingRecord.amount > 0,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).with_entities(
            func.sum(BillingRecord.amount)
        ).scalar() or 0.0
        
        # Общая статистика по возвратам
        total_refunds = db.query(BillingRecord).filter(
            and_(
                BillingRecord.amount < 0,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).count()
        
        total_refund_amount = abs(db.query(BillingRecord).filter(
            and_(
                BillingRecord.amount < 0,
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).with_entities(
            func.sum(BillingRecord.amount)
        ).scalar() or 0.0)
        
        # Чистая сумма
        net_amount = total_payment_amount - total_refund_amount
        
        # Статистика по банкам
        bank_stats = db.query(
            BillingRecord.payer_bank_code,
            func.count(BillingRecord.id).label('count'),
            func.sum(BillingRecord.amount).label('amount')
        ).filter(
            and_(
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date
            )
        ).group_by(
            BillingRecord.payer_bank_code
        ).all()
        
        return {
            "total_payments": total_payments,
            "total_payment_amount": total_payment_amount,
            "total_refunds": total_refunds,
            "total_refund_amount": total_refund_amount,
            "net_amount": net_amount,
            "refund_rate": (total_refund_amount / total_payment_amount * 100) if total_payment_amount > 0 else 0,
            "period_start": start_date,
            "period_end": end_date,
            "bank_statistics": [
                {
                    "bank_code": stat.payer_bank_code,
                    "count": stat.count,
                    "amount": stat.amount
                } for stat in bank_stats
            ]
        }
    
    @staticmethod
    def get_merchant_daily_stats(
        db: Session,
        merchant: Merchant,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Получение ежедневной статистики для продавца
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            days: Количество дней назад
            
        Returns:
            List[Dict[str, Any]]: Ежедневная статистика
        """
        
        start_date = datetime.now() - timedelta(days=days)
        
        results = db.query(
            func.date(MerchantPayment.processed_at).label('date'),
            func.count(MerchantPayment.id).label('payment_count'),
            func.sum(MerchantPayment.amount).label('total_amount'),
            func.avg(MerchantPayment.amount).label('avg_amount')
        ).filter(
            and_(
                MerchantPayment.merchant_id == merchant.id,
                MerchantPayment.processed_at >= start_date,
                MerchantPayment.status == "success"
            )
        ).group_by(
            func.date(MerchantPayment.processed_at)
        ).order_by(
            func.date(MerchantPayment.processed_at).desc()
        ).all()
        
        return [
            {
                "date": result.date.isoformat(),
                "payment_count": result.payment_count,
                "total_amount": round(float(result.total_amount or 0), 2),
                "avg_amount": round(float(result.avg_amount or 0), 2)
            }
            for result in results
        ]
    
    @staticmethod
    def get_merchant_payment_summary(
        db: Session,
        merchant: Merchant,
        skip: int = 0,
        limit: int = 100
    ) -> List[PaymentSummary]:
        """
        Получение сводки платежей для продавца
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            skip: Количество записей для пропуска
            limit: Лимит записей
            
        Returns:
            List[PaymentSummary]: Сводка платежей
        """
        
        payments = db.query(MerchantPayment).filter(
            MerchantPayment.merchant_id == merchant.id
        ).order_by(
            MerchantPayment.processed_at.desc()
        ).offset(skip).limit(limit).all()
        
        return [
            PaymentSummary(
                id=payment.id,
                amount=payment.amount,
                currency=payment.currency,
                status=payment.status,
                payer_phone=payment.payer_phone,
                payer_name=payment.payer_name,
                transaction_id=payment.transaction_id,
                bank_code=payment.bank_code,
                processed_at=payment.processed_at,
                qr_code_id=payment.qr_code_id
            )
            for payment in payments
        ]
    
    @staticmethod
    def get_merchant_qr_code_stats(
        db: Session,
        merchant: Merchant
    ) -> Dict[str, Any]:
        """
        Получение статистики QR-кодов для продавца
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            
        Returns:
            Dict[str, Any]: Статистика QR-кодов
        """
        
        qr_codes = db.query(QRCode).filter(
            QRCode.merchant_id == merchant.id
        ).all()
        
        total_qr_codes = len(qr_codes)
        active_qr_codes = len([qr for qr in qr_codes if qr.is_active])
        expired_qr_codes = len([qr for qr in qr_codes if qr.expires_at and qr.expires_at < datetime.now()])
        
        total_uses = sum(qr.current_uses for qr in qr_codes)
        total_amount = sum(qr.amount * qr.current_uses for qr in qr_codes if qr.amount)
        
        return {
            "total_qr_codes": total_qr_codes,
            "active_qr_codes": active_qr_codes,
            "expired_qr_codes": expired_qr_codes,
            "total_uses": total_uses,
            "total_amount": round(total_amount, 2),
            "avg_uses_per_qr": round(total_uses / max(total_qr_codes, 1), 2)
        }
    
    @staticmethod
    def export_merchant_data(
        db: Session,
        merchant: Merchant,
        start_date: datetime,
        end_date: datetime,
        export_type: str = "payments"
    ) -> List[Dict[str, Any]]:
        """
        Экспорт данных продавца для отчетности
        
        Args:
            db: Сессия базы данных
            merchant: Объект продавца
            start_date: Начальная дата
            end_date: Конечная дата
            export_type: Тип экспорта (payments, qr_codes, billing)
            
        Returns:
            List[Dict[str, Any]]: Данные для экспорта
        """
        
        if export_type == "payments":
            records = db.query(MerchantPayment).filter(
                and_(
                    MerchantPayment.merchant_id == merchant.id,
                    MerchantPayment.processed_at >= start_date,
                    MerchantPayment.processed_at <= end_date
                )
            ).order_by(MerchantPayment.processed_at.desc()).all()
            
            export_data = []
            for record in records:
                export_data.append({
                    "payment_id": record.id,
                    "amount": record.amount,
                    "currency": record.currency,
                    "status": record.status,
                    "payer_phone": record.payer_phone,
                    "payer_name": record.payer_name,
                    "transaction_id": record.transaction_id,
                    "bank_code": record.bank_code,
                    "processed_at": record.processed_at.isoformat(),
                    "qr_code_id": record.qr_code_id
                })
            
            return export_data
            
        elif export_type == "qr_codes":
            records = db.query(QRCode).filter(
                and_(
                    QRCode.merchant_id == merchant.id,
                    QRCode.created_at >= start_date,
                    QRCode.created_at <= end_date
                )
            ).order_by(QRCode.created_at.desc()).all()
            
            export_data = []
            for record in records:
                export_data.append({
                    "qr_code_id": record.id,
                    "name": record.name,
                    "description": record.description,
                    "amount": record.amount,
                    "currency": record.currency,
                    "qr_token": record.qr_token,
                    "qr_url": record.qr_url,
                    "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                    "max_uses": record.max_uses,
                    "current_uses": record.current_uses,
                    "is_active": record.is_active,
                    "created_at": record.created_at.isoformat()
                })
            
            return export_data
            
        else:
            return []
    
    @staticmethod
    def get_billing_summary(
        db: Session,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        bank_code: Optional[str] = None,
        currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение сводки по биллингу
        
        Args:
            db: Сессия базы данных
            start_date: Начальная дата
            end_date: Конечная дата
            bank_code: Фильтр по банку
            currency: Фильтр по валюте
            
        Returns:
            Dict[str, Any]: Сводка по биллингу
        """
        
        # По умолчанию за последние 30 дней
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()
        
        query = db.query(BillingRecord).filter(
            and_(
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date,
                BillingRecord.billing_status == "processed"
            )
        )
        
        if bank_code:
            query = query.filter(
                or_(
                    BillingRecord.payer_bank_code == bank_code,
                    BillingRecord.receiver_bank_code == bank_code
                )
            )
        
        if currency:
            query = query.filter(BillingRecord.currency == currency)
        
        records = query.all()
        
        # Вычисляем статистику
        total_transactions = len(records)
        total_amount = sum(r.amount for r in records)
        total_fees = sum(r.platform_fee + r.bank_fee for r in records)
        
        # Группировка по валютам
        currency_stats = {}
        for record in records:
            if record.currency not in currency_stats:
                currency_stats[record.currency] = {
                    "count": 0,
                    "total_amount": 0,
                    "avg_amount": 0
                }
            currency_stats[record.currency]["count"] += 1
            currency_stats[record.currency]["total_amount"] += record.amount
        
        # Вычисляем средние значения
        for currency_code, stats in currency_stats.items():
            stats["avg_amount"] = round(stats["total_amount"] / stats["count"], 2)
        
        # Группировка по банкам
        bank_stats = {}
        for record in records:
            if record.payer_bank_code not in bank_stats:
                bank_stats[record.payer_bank_code] = {
                    "transactions": 0,
                    "total_amount": 0
                }
            bank_stats[record.payer_bank_code]["transactions"] += 1
            bank_stats[record.payer_bank_code]["total_amount"] += record.amount
        
        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "summary": {
                "total_transactions": total_transactions,
                "total_amount": round(total_amount, 2),
                "total_fees": round(total_fees, 2),
                "avg_transaction_amount": round(total_amount / max(total_transactions, 1), 2)
            },
            "by_currency": currency_stats,
            "by_bank": bank_stats
        }
    
    @staticmethod
    def get_daily_stats(
        db: Session,
        days: int = 30,
        bank_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Получение ежедневной статистики
        
        Args:
            db: Сессия базы данных
            days: Количество дней назад
            bank_code: Фильтр по банку
            
        Returns:
            List[Dict[str, Any]]: Ежедневная статистика
        """
        
        start_date = datetime.now() - timedelta(days=days)
        
        query = db.query(
            func.date(BillingRecord.payment_date).label('date'),
            func.count(BillingRecord.id).label('transaction_count'),
            func.sum(BillingRecord.amount).label('total_amount'),
            func.avg(BillingRecord.amount).label('avg_amount')
        ).filter(
            and_(
                BillingRecord.payment_date >= start_date,
                BillingRecord.billing_status == "processed"
            )
        )
        
        if bank_code:
            query = query.filter(
                or_(
                    BillingRecord.payer_bank_code == bank_code,
                    BillingRecord.receiver_bank_code == bank_code
                )
            )
        
        results = query.group_by(
            func.date(BillingRecord.payment_date)
        ).order_by(
            func.date(BillingRecord.payment_date).desc()
        ).all()
        
        return [
            {
                "date": result.date.isoformat(),
                "transaction_count": result.transaction_count,
                "total_amount": round(float(result.total_amount or 0), 2),
                "avg_amount": round(float(result.avg_amount or 0), 2)
            }
            for result in results
        ]
    
    @staticmethod
    def get_top_receivers(
        db: Session,
        days: int = 30,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Получение топ получателей платежей
        
        Args:
            db: Сессия базы данных
            days: За сколько дней
            limit: Количество записей
            
        Returns:
            List[Dict[str, Any]]: Топ получателей
        """
        
        start_date = datetime.now() - timedelta(days=days)
        
        results = db.query(
            BillingRecord.receiver_name,
            BillingRecord.receiver_account,
            BillingRecord.receiver_bank_code,
            func.count(BillingRecord.id).label('transaction_count'),
            func.sum(BillingRecord.amount).label('total_amount')
        ).filter(
            and_(
                BillingRecord.payment_date >= start_date,
                BillingRecord.billing_status == "processed"
            )
        ).group_by(
            BillingRecord.receiver_name,
            BillingRecord.receiver_account,
            BillingRecord.receiver_bank_code
        ).order_by(
            func.sum(BillingRecord.amount).desc()
        ).limit(limit).all()
        
        return [
            {
                "receiver_name": result.receiver_name,
                "receiver_account": result.receiver_account,
                "receiver_bank_code": result.receiver_bank_code,
                "transaction_count": result.transaction_count,
                "total_amount": round(float(result.total_amount), 2)
            }
            for result in results
        ]
    
    @staticmethod
    def export_billing_data(
        db: Session,
        start_date: datetime,
        end_date: datetime,
        format_type: str = "csv"
    ) -> List[Dict[str, Any]]:
        """
        Экспорт биллинговых данных для отчетности
        
        Args:
            db: Сессия базы данных
            start_date: Начальная дата
            end_date: Конечная дата
            format_type: Формат экспорта
            
        Returns:
            List[Dict[str, Any]]: Данные для экспорта
        """
        
        records = db.query(BillingRecord).filter(
            and_(
                BillingRecord.payment_date >= start_date,
                BillingRecord.payment_date <= end_date,
                BillingRecord.billing_status == "processed"
            )
        ).order_by(BillingRecord.payment_date.desc()).all()
        
        export_data = []
        for record in records:
            export_data.append({
                "transaction_id": record.transaction_id,
                "payment_date": record.payment_date.isoformat(),
                "amount": record.amount,
                "currency": record.currency,
                "payer_phone": record.payer_phone,
                "payer_bank": record.payer_bank_code,
                "receiver_name": record.receiver_name,
                "receiver_account": record.receiver_account,
                "receiver_bank": record.receiver_bank_code,
                "description": record.payment_description,
                "reference": record.payment_reference,
                "platform_fee": record.platform_fee,
                "bank_fee": record.bank_fee
            })
        
        return export_data
    
    @staticmethod
    def update_billing_status(
        db: Session,
        transaction_id: str,
        new_status: str,
        reason: Optional[str] = None
    ) -> Optional[BillingRecord]:
        """
        Обновление статуса биллинговой записи
        
        Args:
            db: Сессия базы данных
            transaction_id: ID транзакции
            new_status: Новый статус
            reason: Причина изменения
            
        Returns:
            BillingRecord: Обновленная запись
        """
        
        record = db.query(BillingRecord).filter(
            BillingRecord.transaction_id == transaction_id
        ).first()
        
        if not record:
            return None
        
        old_status = record.billing_status
        record.billing_status = new_status
        record.updated_at = datetime.now()
        
        db.commit()
        db.refresh(record)
        
        logger.info(
            f"Updated billing status for transaction {transaction_id}: "
            f"{old_status} -> {new_status}. Reason: {reason}"
        )
        
        return record
