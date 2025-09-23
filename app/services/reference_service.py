from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.unified import UnifiedPayment
import logging

logger = logging.getLogger(__name__)

class PaymentReferenceService:
    """Сервис для генерации уникальных payment_reference согласно ТЗ"""
    
    @staticmethod
    def generate_payment_reference(
        db: Session,
        custom_prefix: Optional[str] = None
    ) -> str:
        """
        Генерация payment_reference в формате QRHUB-{номер}-{дата}
        
        Args:
            db: Сессия базы данных
            custom_prefix: Кастомный префикс вместо QRHUB
            
        Returns:
            str: Уникальный payment_reference
        """
        
        prefix = custom_prefix or "QRHUB"
        date_str = datetime.now().strftime("%Y%m%d")
        
        # Получаем следующий порядковый номер для сегодняшнего дня
        sequence_number = PaymentReferenceService._get_next_sequence_number(db, date_str)
        
        reference = f"{prefix}-{sequence_number}-{date_str}"
        
        logger.info(f"Generated payment reference: {reference}")
        
        return reference
    
    @staticmethod
    def _get_next_sequence_number(db: Session, date_str: str) -> int:
        """
        Получение следующего порядкового номера для даты
        
        Args:
            db: Сессия базы данных
            date_str: Дата в формате YYYYMMDD
            
        Returns:
            int: Следующий порядковый номер
        """
        
        # Ищем все payment_reference за сегодня
        today_references = db.query(UnifiedPayment.payment_reference).filter(
            UnifiedPayment.payment_reference.like(f"%{date_str}")
        ).all()
        
        if not today_references:
            return 1
        
        # Извлекаем номера из существующих референсов
        max_number = 0
        for ref_tuple in today_references:
            ref = ref_tuple[0]
            try:
                # Парсим формат QRHUB-{номер}-{дата}
                parts = ref.split('-')
                if len(parts) >= 3:
                    number = int(parts[-2])  # Предпоследняя часть - это номер
                    max_number = max(max_number, number)
            except (ValueError, IndexError):
                continue
        
        return max_number + 1
    
    @staticmethod
    def validate_payment_reference(reference: str) -> dict:
        """
        Валидация формата payment_reference
        
        Args:
            reference: Референс для проверки
            
        Returns:
            dict: Результат валидации с деталями
        """
        
        result = {
            "valid": False,
            "prefix": None,
            "number": None,
            "date": None,
            "errors": []
        }
        
        if not reference:
            result["errors"].append("Reference is empty")
            return result
        
        # Разбираем по частям
        parts = reference.split('-')
        
        if len(parts) < 3:
            result["errors"].append("Invalid format: should be PREFIX-NUMBER-DATE")
            return result
        
        prefix = parts[0]
        number_str = parts[1]
        date_str = parts[2]
        
        # Валидируем префикс
        if not prefix.isalpha():
            result["errors"].append("Prefix should contain only letters")
        else:
            result["prefix"] = prefix
        
        # Валидируем номер
        try:
            number = int(number_str)
            if number <= 0:
                result["errors"].append("Number should be positive")
            else:
                result["number"] = number
        except ValueError:
            result["errors"].append("Number should be integer")
        
        # Валидируем дату
        if len(date_str) != 8:
            result["errors"].append("Date should be in YYYYMMDD format")
        else:
            try:
                datetime.strptime(date_str, "%Y%m%d")
                result["date"] = date_str
            except ValueError:
                result["errors"].append("Invalid date format")
        
        result["valid"] = len(result["errors"]) == 0
        
        return result
    
    @staticmethod
    def get_reference_statistics(
        db: Session,
        days: int = 30
    ) -> dict:
        """
        Статистика по payment_reference
        
        Args:
            db: Сессия базы данных
            days: За сколько дней
            
        Returns:
            dict: Статистика
        """
        from datetime import timedelta
        
        start_date = datetime.now() - timedelta(days=days)
        
        # Получаем все референсы за период
        references = db.query(UnifiedPayment.payment_reference).filter(
            UnifiedPayment.created_at >= start_date
        ).all()
        
        stats = {
            "total_references": len(references),
            "by_date": {},
            "by_prefix": {},
            "invalid_references": []
        }
        
        for ref_tuple in references:
            ref = ref_tuple[0]
            
            # Валидируем референс
            validation = PaymentReferenceService.validate_payment_reference(ref)
            
            if validation["valid"]:
                # Группируем по дате
                date = validation["date"]
                if date not in stats["by_date"]:
                    stats["by_date"][date] = 0
                stats["by_date"][date] += 1
                
                # Группируем по префиксу
                prefix = validation["prefix"]
                if prefix not in stats["by_prefix"]:
                    stats["by_prefix"][prefix] = 0
                stats["by_prefix"][prefix] += 1
            else:
                stats["invalid_references"].append({
                    "reference": ref,
                    "errors": validation["errors"]
                })
        
        return stats
    
    @staticmethod
    def find_duplicate_references(db: Session) -> list:
        """
        Поиск дублированных payment_reference
        
        Args:
            db: Сессия базы данных
            
        Returns:
            list: Список дубликатов
        """
        
        # Ищем дубликаты через GROUP BY
        duplicates = db.query(
            UnifiedPayment.payment_reference,
            func.count(UnifiedPayment.id).label('count')
        ).group_by(
            UnifiedPayment.payment_reference
        ).having(
            func.count(UnifiedPayment.id) > 1
        ).all()
        
        result = []
        for duplicate in duplicates:
            reference = duplicate[0]
            count = duplicate[1]
            
            # Получаем детали всех записей с этим референсом
            records = db.query(UnifiedPayment).filter(
                UnifiedPayment.payment_reference == reference
            ).all()
            
            result.append({
                "reference": reference,
                "count": count,
                "records": [
                    {
                        "id": r.id,
                        "token": r.token,
                        "created_at": r.created_at.isoformat()
                    }
                    for r in records
                ]
            })
        
        return result
