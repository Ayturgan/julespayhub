"""
Сервис для работы с платежами продавцов
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models.merchant import Merchant
from app.models.unified import UnifiedPayment
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any
import io
import csv


class MerchantPaymentService:
    """Сервис для работы с платежами продавцов"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def build_payments_query(
        self,
        merchant: Merchant,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        qr_code_id: Optional[int] = None,
        outlet_id: Optional[int] = None
    ):
        """
        Создает базовый запрос для фильтрации платежей продавца
        
        Args:
            merchant: Объект продавца
            **filters: Параметры фильтрации
            
        Returns:
            SQLAlchemy Query: Запрос с примененными фильтрами
        """
        query = self.db.query(UnifiedPayment).filter(
            UnifiedPayment.merchant_id == merchant.id
        )
        
        # Фильтр по статусу
        if status:
            query = query.filter(UnifiedPayment.status == status)
            
        # Фильтры по дате
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
                query = query.filter(UnifiedPayment.created_at >= dt_from)
            except ValueError:
                raise ValueError("Invalid date_from format")
                
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
                query = query.filter(UnifiedPayment.created_at <= dt_to)
            except ValueError:
                raise ValueError("Invalid date_to format")
                
        # Фильтры по сумме
        if min_amount is not None:
            query = query.filter(UnifiedPayment.amount >= min_amount)
        if max_amount is not None:
            query = query.filter(UnifiedPayment.amount <= max_amount)
            
        # Фильтр по QR коду
        if qr_code_id is not None:
            query = query.filter(UnifiedPayment.qr_code_id == qr_code_id)

        # Фильтр по торговой точке
        if outlet_id is not None:
            query = query.filter(UnifiedPayment.outlet_id == outlet_id)
            
        return query
    
    def get_payments_list(
        self,
        merchant: Merchant,
        limit: int = 50,
        offset: int = 0,
        **filters
    ) -> List[UnifiedPayment]:
        """
        Получает список платежей с пагинацией и фильтрацией
        """
        query = self.build_payments_query(merchant, **filters)
        return query.order_by(
            UnifiedPayment.created_at.desc()
        ).offset(offset).limit(limit).all()
    
    def export_payments_csv(
        self,
        merchant: Merchant,
        **filters
    ) -> str:
        """
        Экспортирует платежи в CSV формат
        """
        query = self.build_payments_query(merchant, **filters)
        payments = query.order_by(UnifiedPayment.created_at.desc()).all()
        
        # Формируем CSV
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "date", "amount", "currency", "status", 
            "transaction_id", "payment_reference", "qr_code_id"
        ])
        
        for payment in payments:
            writer.writerow([
                payment.created_at.isoformat() if payment.created_at else "",
                payment.amount,
                payment.currency,
                payment.status.value,
                payment.transaction_id or "",
                payment.payment_reference or "",
                payment.qr_code_id or ""
            ])
        
        return buf.getvalue()
    
    def get_payments_series(
        self,
        merchant: Merchant,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Получает серию данных платежей по дням
        """
        end_date = datetime.now(timezone.utc).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        start_date = end_date - timedelta(days=days-1)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Получаем все платежи за период
        payments = self.db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.merchant_id == merchant.id,
                UnifiedPayment.created_at >= start_date,
                UnifiedPayment.created_at <= end_date
            )
        ).all()
        
        # Группируем платежи по дням в Python
        payments_dict = {}
        for payment in payments:
            payment_date = payment.created_at.date()
            if payment_date not in payments_dict:
                payments_dict[payment_date] = {"count": 0, "amount": 0.0}
            payments_dict[payment_date]["count"] += 1
            payments_dict[payment_date]["amount"] += payment.amount
        
        # Создаем полный список дней (заполняем пропуски нулями)
        series = []
        current_date = start_date.date()
        
        for i in range(days):
            date_str = current_date.strftime("%Y-%m-%d")
            day_data = payments_dict.get(current_date, {"count": 0, "amount": 0.0})
            series.append({
                "date": date_str,
                "payments_count": day_data["count"],
                "total_amount": day_data["amount"]
            })
            current_date += timedelta(days=1)
        
        return {"data": series}
    
    def get_merchant_stats(
        self,
        merchant: Merchant,
        period: str = "month",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Получает статистику продавца за период
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Вычисляем статистику для продавца ID: {merchant.id}")
        
        now = datetime.now(timezone.utc)
        
        # Определяем период
        if start_date and end_date:
            # Используем переданные даты
            start_datetime = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            end_datetime = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        else:
            # Используем период
            if period == "all":
                # За все время - не устанавливаем ограничения по дате
                start_datetime = None
                end_datetime = None
            elif period == "day":
                start_datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_datetime = now
            elif period == "week":
                start_datetime = now - timedelta(days=7)
                end_datetime = now
            else:  # month
                start_datetime = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                end_datetime = now
        
        # Получаем платежи за период
        query = self.db.query(UnifiedPayment).filter(
            UnifiedPayment.merchant_id == merchant.id
        )
        
        if start_datetime:
            query = query.filter(UnifiedPayment.created_at >= start_datetime)
        
        if end_datetime:
            query = query.filter(UnifiedPayment.created_at <= end_datetime)
        
        payments = query.all()
        
        # Вычисляем статистику
        total_payments = len(payments)
        total_amount = sum(p.amount for p in payments)
        successful_payments = len([p for p in payments if p.status.value == "completed"])
        failed_payments = len([p for p in payments if p.status.value == "failed"])
        
        success_rate = (successful_payments / total_payments * 100) if total_payments > 0 else 0
        average_amount = (total_amount / total_payments) if total_payments > 0 else 0
        
        # Получаем распределение по статусам
        status_distribution = {}
        for payment in payments:
            status = payment.status.value
            if status not in status_distribution:
                status_distribution[status] = 0
            status_distribution[status] += 1
        
        result = {
            "total_payments": total_payments,
            "total_amount": total_amount,
            "successful_payments": successful_payments,
            "failed_payments": failed_payments,
            "success_rate": success_rate,
            "average_payment_amount": average_amount,
            "status_distribution": status_distribution
        }
        
        logger.info(f"Статистика для продавца {merchant.id}: {result}")
        return result
    
    def get_quick_stats(self, merchant: Merchant) -> Dict[str, Any]:
        """
        Получает быструю статистику для дашборда
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Вычисляем быструю статистику для продавца ID: {merchant.id}")
        
        # Считаем общие метрики за все время
        total_payments = self.db.query(UnifiedPayment).filter(
            UnifiedPayment.merchant_id == merchant.id
        ).count()
        
        successful_payments = self.db.query(UnifiedPayment).filter(
            and_(
                UnifiedPayment.merchant_id == merchant.id,
                UnifiedPayment.status == 'completed'
            )
        ).count()
        
        total_revenue = self.db.query(func.sum(UnifiedPayment.amount)).filter(
            and_(
                UnifiedPayment.merchant_id == merchant.id,
                UnifiedPayment.status == 'completed'
            )
        ).scalar() or 0
        
        avg_check = self.db.query(func.avg(UnifiedPayment.amount)).filter(
            and_(
                UnifiedPayment.merchant_id == merchant.id,
                UnifiedPayment.status == 'completed'
            )
        ).scalar() or 0
        
        return {
            "total_payments": total_payments,
            "successful_payments": successful_payments,
            "total_revenue": float(total_revenue),
            "avg_check": float(avg_check),
            "success_rate": round((successful_payments / total_payments * 100), 1) if total_payments > 0 else 0
        }
