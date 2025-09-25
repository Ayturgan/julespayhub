"""
Репозиторий для доступа к истории транзакций в модуле скоринга

Обеспечивает изолированный доступ к данным транзакций
без прямых зависимостей от основных моделей приложения.
"""

from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import logging

from app.models.unified import UnifiedPayment
from app.models.payment import TransactionRecord, BillingRecord
from app.models.merchant import Merchant


class TransactionRepository:
    """
    Репозиторий для работы с историей транзакций
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger("scoring.repository")
    
    def get_transactions_by_phone(
        self, 
        phone: str, 
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Получить транзакции по номеру телефона за период
        
        Args:
            phone: Номер телефона плательщика
            days: Количество дней для поиска
            
        Returns:
            Список транзакций с метаданными
        """
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Ищем в UnifiedPayment
            payments = self.db.query(UnifiedPayment).filter(
                and_(
                    UnifiedPayment.payer_phone == phone,
                    UnifiedPayment.created_at >= start_date,
                    UnifiedPayment.status.in_(['completed', 'prepared'])
                )
            ).order_by(UnifiedPayment.created_at.desc()).all()
            
            # Ищем в TransactionRecord
            transactions = self.db.query(TransactionRecord).filter(
                and_(
                    TransactionRecord.payer_phone == phone,
                    TransactionRecord.processed_at >= start_date,
                    TransactionRecord.status == 'success'
                )
            ).order_by(TransactionRecord.processed_at.desc()).all()
            
            # Ищем в BillingRecord
            billing_records = self.db.query(BillingRecord).filter(
                and_(
                    BillingRecord.payer_phone == phone,
                    BillingRecord.payment_date >= start_date,
                    BillingRecord.billing_status == 'processed'
                )
            ).order_by(BillingRecord.payment_date.desc()).all()
            
            # Объединяем результаты
            results = []
            
            # Добавляем UnifiedPayment
            for payment in payments:
                results.append({
                    'id': payment.id,
                    'amount': payment.amount,
                    'currency': payment.currency,
                    'status': payment.status.value if payment.status else 'unknown',
                    'created_at': payment.created_at,
                    'transaction_id': payment.transaction_id,
                    'receiver_bank_code': payment.receiver_bank_code,
                    'description': payment.description,
                    'source': 'unified_payment'
                })
            
            # Добавляем TransactionRecord
            for transaction in transactions:
                results.append({
                    'id': transaction.id,
                    'amount': transaction.amount,
                    'currency': 'KGS',  # По умолчанию
                    'status': transaction.status,
                    'created_at': transaction.processed_at,
                    'transaction_id': transaction.transaction_id,
                    'receiver_bank_code': None,
                    'description': None,
                    'source': 'transaction_record'
                })
            
            # Добавляем BillingRecord
            for billing in billing_records:
                results.append({
                    'id': billing.id,
                    'amount': billing.amount,
                    'currency': billing.currency,
                    'status': billing.billing_status,
                    'created_at': billing.payment_date,
                    'transaction_id': billing.transaction_id,
                    'receiver_bank_code': billing.receiver_bank_code,
                    'description': billing.payment_description,
                    'source': 'billing_record'
                })
            
            # Сортируем по дате
            results.sort(key=lambda x: x['created_at'], reverse=True)
            
            self.logger.info(f"Найдено {len(results)} транзакций для телефона {phone} за {days} дней")
            return results
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении транзакций по телефону {phone}: {e}")
            return []
    
    def get_transactions_by_account(
        self, 
        account: str, 
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Получить транзакции по номеру счета за период
        
        Args:
            account: Номер счета отправителя
            days: Количество дней для поиска
            
        Returns:
            Список транзакций с метаданными
        """
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Ищем в UnifiedPayment
            payments = self.db.query(UnifiedPayment).filter(
                and_(
                    UnifiedPayment.sender_account == account,
                    UnifiedPayment.created_at >= start_date,
                    UnifiedPayment.status.in_(['completed', 'prepared'])
                )
            ).order_by(UnifiedPayment.created_at.desc()).all()
            
            # Объединяем результаты
            results = []
            
            for payment in payments:
                results.append({
                    'id': payment.id,
                    'amount': payment.amount,
                    'currency': payment.currency,
                    'status': payment.status.value if payment.status else 'unknown',
                    'created_at': payment.created_at,
                    'transaction_id': payment.transaction_id,
                    'receiver_bank_code': payment.receiver_bank_code,
                    'description': payment.description,
                    'source': 'unified_payment'
                })
            
            results.sort(key=lambda x: x['created_at'], reverse=True)
            
            self.logger.info(f"Найдено {len(results)} транзакций для счета {account} за {days} дней")
            return results
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении транзакций по счету {account}: {e}")
            return []
    
    def get_daily_transaction_stats(
        self, 
        identifier: str, 
        identifier_type: str = "phone",
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Получить статистику транзакций по дням
        
        Args:
            identifier: Телефон или счет
            identifier_type: "phone" или "account"
            days: Количество дней для анализа
            
        Returns:
            Словарь со статистикой
        """
        try:
            transactions = []
            
            if identifier_type == "phone":
                transactions = self.get_transactions_by_phone(identifier, days)
            elif identifier_type == "account":
                transactions = self.get_transactions_by_account(identifier, days)
            
            if not transactions:
                return {
                    'total_transactions': 0,
                    'total_amount': 0.0,
                    'daily_counts': [],
                    'daily_amounts': [],
                    'average_amount': 0.0,
                    'max_daily_transactions': 0,
                    'max_daily_amount': 0.0
                }
            
            # Группируем по дням
            daily_stats = {}
            total_amount = 0.0
            
            for transaction in transactions:
                date_key = transaction['created_at'].date()
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'count': 0, 'amount': 0.0}
                
                daily_stats[date_key]['count'] += 1
                daily_stats[date_key]['amount'] += transaction['amount']
                total_amount += transaction['amount']
            
            # Создаем списки для всех дней
            daily_counts = []
            daily_amounts = []
            
            for i in range(days):
                date = (datetime.now() - timedelta(days=i)).date()
                count = daily_stats.get(date, {'count': 0})['count']
                amount = daily_stats.get(date, {'amount': 0.0})['amount']
                
                daily_counts.append(count)
                daily_amounts.append(amount)
            
            max_daily_transactions = max(daily_counts) if daily_counts else 0
            max_daily_amount = max(daily_amounts) if daily_amounts else 0.0
            average_amount = total_amount / len(transactions) if transactions else 0.0
            
            return {
                'total_transactions': len(transactions),
                'total_amount': total_amount,
                'daily_counts': daily_counts,
                'daily_amounts': daily_amounts,
                'average_amount': average_amount,
                'max_daily_transactions': max_daily_transactions,
                'max_daily_amount': max_daily_amount
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики для {identifier}: {e}")
            return {
                'total_transactions': 0,
                'total_amount': 0.0,
                'daily_counts': [],
                'daily_amounts': [],
                'average_amount': 0.0,
                'max_daily_transactions': 0,
                'max_daily_amount': 0.0
            }
    
    def get_hourly_transaction_count(
        self, 
        identifier: str, 
        identifier_type: str = "phone",
        hours: int = 24
    ) -> int:
        """
        Получить количество транзакций за последние N часов
        
        Args:
            identifier: Телефон или счет
            identifier_type: "phone" или "account"
            hours: Количество часов для поиска
            
        Returns:
            Количество транзакций
        """
        try:
            start_time = datetime.now() - timedelta(hours=hours)
            
            if identifier_type == "phone":
                # UnifiedPayment
                count_up = self.db.query(UnifiedPayment).filter(
                    and_(
                        UnifiedPayment.payer_phone == identifier,
                        UnifiedPayment.created_at >= start_time,
                        UnifiedPayment.status.in_(['completed', 'prepared'])
                    )
                ).count()
                
                # TransactionRecord
                count_tr = self.db.query(TransactionRecord).filter(
                    and_(
                        TransactionRecord.payer_phone == identifier,
                        TransactionRecord.processed_at >= start_time,
                        TransactionRecord.status == 'success'
                    )
                ).count()
                
                # BillingRecord
                count_br = self.db.query(BillingRecord).filter(
                    and_(
                        BillingRecord.payer_phone == identifier,
                        BillingRecord.payment_date >= start_time,
                        BillingRecord.billing_status == 'processed'
                    )
                ).count()
                
                total_count = count_up + count_tr + count_br
                
            elif identifier_type == "account":
                # UnifiedPayment
                count_up = self.db.query(UnifiedPayment).filter(
                    and_(
                        UnifiedPayment.sender_account == identifier,
                        UnifiedPayment.created_at >= start_time,
                        UnifiedPayment.status.in_(['completed', 'prepared'])
                    )
                ).count()
                
                total_count = count_up
            else:
                total_count = 0
            
            self.logger.info(f"Найдено {total_count} транзакций для {identifier} за {hours} часов")
            return total_count
            
        except Exception as e:
            self.logger.error(f"Ошибка при подсчете транзакций для {identifier}: {e}")
            return 0
    
    def get_merchant_transaction_history(
        self, 
        merchant_id: int, 
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Получить историю транзакций продавца
        
        Args:
            merchant_id: ID продавца
            days: Количество дней для поиска
            
        Returns:
            Статистика транзакций продавца
        """
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Получаем все платежи продавца
            payments = self.db.query(UnifiedPayment).filter(
                and_(
                    UnifiedPayment.merchant_id == merchant_id,
                    UnifiedPayment.created_at >= start_date,
                    UnifiedPayment.status.in_(['completed', 'prepared'])
                )
            ).all()
            
            total_amount = sum(p.amount for p in payments)
            successful_count = len([p for p in payments if p.status == 'completed'])
            
            # Группируем по дням
            daily_amounts = {}
            for payment in payments:
                date_key = payment.created_at.date()
                if date_key not in daily_amounts:
                    daily_amounts[date_key] = 0.0
                daily_amounts[date_key] += payment.amount
            
            return {
                'total_transactions': len(payments),
                'total_amount': total_amount,
                'successful_transactions': successful_count,
                'daily_amounts': daily_amounts,
                'average_amount': total_amount / len(payments) if payments else 0.0
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении истории продавца {merchant_id}: {e}")
            return {
                'total_transactions': 0,
                'total_amount': 0.0,
                'successful_transactions': 0,
                'daily_amounts': {},
                'average_amount': 0.0
            }
    
    def check_duplicate_transaction(
        self, 
        amount: float, 
        identifier: str, 
        identifier_type: str = "phone",
        minutes: int = 5
    ) -> bool:
        """
        Проверить наличие дублирующих транзакций
        
        Args:
            amount: Сумма транзакции
            identifier: Телефон или счет
            identifier_type: "phone" или "account"
            minutes: Период для поиска дубликатов в минутах
            
        Returns:
            True если найдены дублирующие транзакции
        """
        try:
            start_time = datetime.now() - timedelta(minutes=minutes)
            
            if identifier_type == "phone":
                # UnifiedPayment
                count_up = self.db.query(UnifiedPayment).filter(
                    and_(
                        UnifiedPayment.payer_phone == identifier,
                        UnifiedPayment.amount == amount,
                        UnifiedPayment.created_at >= start_time,
                        UnifiedPayment.status.in_(['completed', 'prepared'])
                    )
                ).count()
                
                # TransactionRecord
                count_tr = self.db.query(TransactionRecord).filter(
                    and_(
                        TransactionRecord.payer_phone == identifier,
                        TransactionRecord.amount == amount,
                        TransactionRecord.processed_at >= start_time,
                        TransactionRecord.status == 'success'
                    )
                ).count()
                
                total_count = count_up + count_tr
                
            elif identifier_type == "account":
                # UnifiedPayment
                count_up = self.db.query(UnifiedPayment).filter(
                    and_(
                        UnifiedPayment.sender_account == identifier,
                        UnifiedPayment.amount == amount,
                        UnifiedPayment.created_at >= start_time,
                        UnifiedPayment.status.in_(['completed', 'prepared'])
                    )
                ).count()
                
                total_count = count_up
            else:
                total_count = 0
            
            is_duplicate = total_count > 0
            
            if is_duplicate:
                self.logger.warning(f"Найдена дублирующая транзакция: {amount} для {identifier}")
            
            return is_duplicate
            
        except Exception as e:
            self.logger.error(f"Ошибка при проверке дубликатов для {identifier}: {e}")
            return False


# Фабрика для создания репозитория
def create_transaction_repository(db: Session) -> TransactionRepository:
    """Создать экземпляр репозитория транзакций"""
    return TransactionRepository(db)