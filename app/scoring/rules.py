"""
Базовые классы и правила для системы скоринга

Содержит абстрактный базовый класс BaseRule и конкретные реализации правил
для проверки различных аспектов транзакций.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime, timedelta

from .schemas import TransactionDataForScoring, RuleEvaluationResult, ScoringDecision
from .exceptions import RuleValidationError


class BaseRule(ABC):
    """
    Абстрактный базовый класс для правил скоринга
    """
    
    def __init__(self, name: str, weight: float = 1.0, enabled: bool = True):
        self.name = name
        self.weight = weight
        self.enabled = enabled
        self.logger = logging.getLogger(f"scoring.rules.{name}")
    
    @abstractmethod
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """
        Применить правило к данным транзакции
        
        Args:
            data: Данные транзакции для анализа
            
        Returns:
            RuleEvaluationResult: Результат применения правила
        """
        pass
    
    def is_enabled(self) -> bool:
        """Проверить, включено ли правило"""
        return self.enabled
    
    def get_weight(self) -> float:
        """Получить вес правила"""
        return self.weight


class AmountLimitRule(BaseRule):
    """
    Правило проверки лимитов сумм транзакций
    """
    
    def __init__(
        self, 
        max_single_transaction: float = 500000.0,  # 500k KGS
        max_daily_amount: float = 1000000.0,       # 1M KGS
        weight: float = 2.0
    ):
        super().__init__("amount_limit", weight)
        self.max_single_transaction = max_single_transaction
        self.max_daily_amount = max_daily_amount
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить лимиты сумм"""
        score_contribution = 0
        errors = []
        warnings = []
        
        # Проверка максимальной суммы одной транзакции
        if data.amount > self.max_single_transaction:
            score_contribution += 50
            errors.append(f"Превышен лимит одной транзакции: {data.amount} > {self.max_single_transaction}")
        
        # Проверка на подозрительно круглые суммы
        if self._is_suspicious_amount(data.amount):
            score_contribution += 10
            warnings.append(f"Подозрительно круглая сумма: {data.amount}")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "max_single_transaction": self.max_single_transaction,
                "amount": data.amount,
                "suspicious_amount": self._is_suspicious_amount(data.amount)
            }
        )
    
    def _is_suspicious_amount(self, amount: float) -> bool:
        """Проверить, является ли сумма подозрительной"""
        # Проверяем на круглые суммы (заканчивающиеся на 000)
        return amount % 1000 == 0 and amount >= 10000


class FrequencyRule(BaseRule):
    """
    Правило проверки частоты транзакций
    """
    
    def __init__(
        self,
        max_transactions_per_hour: int = 10,
        max_transactions_per_day: int = 50,
        weight: float = 1.5
    ):
        super().__init__("frequency", weight)
        self.max_transactions_per_hour = max_transactions_per_hour
        self.max_transactions_per_day = max_transactions_per_day
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить частоту транзакций"""
        score_contribution = 0
        errors = []
        warnings = []
        
        # Здесь должна быть логика получения истории транзакций
        # Пока используем заглушки
        hourly_count = self._get_transaction_count_for_period(data, "hour")
        daily_count = self._get_transaction_count_for_period(data, "day")
        
        if hourly_count > self.max_transactions_per_hour:
            score_contribution += 30
            errors.append(f"Превышен лимит транзакций в час: {hourly_count} > {self.max_transactions_per_hour}")
        
        if daily_count > self.max_transactions_per_day:
            score_contribution += 20
            errors.append(f"Превышен лимит транзакций в день: {daily_count} > {self.max_transactions_per_day}")
        
        # Предупреждение при высоком количестве транзакций
        if hourly_count > self.max_transactions_per_hour * 0.8:
            warnings.append(f"Высокая частота транзакций в час: {hourly_count}")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "hourly_count": hourly_count,
                "daily_count": daily_count,
                "max_hourly": self.max_transactions_per_hour,
                "max_daily": self.max_transactions_per_day
            }
        )
    
    def _get_transaction_count_for_period(self, data: TransactionDataForScoring, period: str) -> int:
        """Получить количество транзакций за период"""
        # Заглушка - в реальной реализации здесь должен быть запрос к БД
        # по payer_phone или sender_account за указанный период
        return 0


class GeolocationRule(BaseRule):
    """
    Правило проверки геолокации (IP-адрес)
    """
    
    def __init__(self, weight: float = 1.0):
        super().__init__("geolocation", weight)
        # Список разрешенных стран для Кыргызстана
        self.allowed_countries = ["KG", "KZ", "UZ", "TJ", "RU", "CN"]
        self.suspicious_countries = ["AF", "IR", "KP", "SY"]  # Санкционные страны
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить геолокацию по IP-адресу"""
        if not data.ip_address:
            return RuleEvaluationResult(
                rule_name=self.name,
                passed=True,
                score_contribution=0,
                warning_message="IP-адрес не предоставлен",
                metadata={"ip_address": None}
            )
        
        # Заглушка для определения страны по IP
        country = self._get_country_by_ip(data.ip_address)
        
        score_contribution = 0
        errors = []
        warnings = []
        
        if country in self.suspicious_countries:
            score_contribution += 40
            errors.append(f"IP-адрес из санкционной страны: {country}")
        elif country not in self.allowed_countries:
            score_contribution += 20
            warnings.append(f"IP-адрес из неразрешенной страны: {country}")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "ip_address": data.ip_address,
                "country": country,
                "allowed_countries": self.allowed_countries
            }
        )
    
    def _get_country_by_ip(self, ip_address: str) -> str:
        """Определить страну по IP-адресу"""
        # Заглушка - в реальной реализации здесь должен быть вызов
        # к сервису геолокации (например, MaxMind GeoIP)
        return "KG"  # По умолчанию считаем, что это Кыргызстан


class PhoneNumberRule(BaseRule):
    """
    Правило проверки номера телефона
    """
    
    def __init__(self, weight: float = 1.0):
        super().__init__("phone_number", weight)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить номер телефона"""
        if not data.payer_phone:
            return RuleEvaluationResult(
                rule_name=self.name,
                passed=True,
                score_contribution=0,
                warning_message="Номер телефона не предоставлен",
                metadata={"phone": None}
            )
        
        score_contribution = 0
        errors = []
        warnings = []
        
        # Проверка формата номера
        if not self._is_valid_phone_format(data.payer_phone):
            score_contribution += 20
            errors.append(f"Неверный формат номера телефона: {data.payer_phone}")
        
        # Проверка на подозрительные номера
        if self._is_suspicious_phone(data.payer_phone):
            score_contribution += 15
            warnings.append(f"Подозрительный номер телефона: {data.payer_phone}")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "phone": data.payer_phone,
                "valid_format": self._is_valid_phone_format(data.payer_phone),
                "suspicious": self._is_suspicious_phone(data.payer_phone)
            }
        )
    
    def _is_valid_phone_format(self, phone: str) -> bool:
        """Проверить формат номера телефона"""
        # Простая проверка для кыргызских номеров
        import re
        # Форматы: +996XXXXXXXXX, 996XXXXXXXXX, 0XXXXXXXXX
        patterns = [
            r'^\+996\d{9}$',  # +996XXXXXXXXX
            r'^996\d{9}$',    # 996XXXXXXXXX
            r'^0\d{9}$'       # 0XXXXXXXXX
        ]
        return any(re.match(pattern, phone) for pattern in patterns)
    
    def _is_suspicious_phone(self, phone: str) -> bool:
        """Проверить, является ли номер подозрительным"""
        # Проверяем на последовательные цифры или повторяющиеся
        clean_phone = ''.join(filter(str.isdigit, phone))
        if len(clean_phone) >= 9:
            # Проверка на последовательные цифры (123456789)
            if clean_phone in '123456789':
                return True
            # Проверка на повторяющиеся цифры (111111111)
            if len(set(clean_phone)) <= 2:
                return True
        return False


class BankCodeRule(BaseRule):
    """
    Правило проверки кодов банков
    """
    
    def __init__(self, weight: float = 1.0):
        super().__init__("bank_code", weight)
        # Список известных банков Кыргызстана
        self.valid_bank_codes = [
            "DEMIR", "OPTIMA", "MOBILE", "BTA", "RSK", "KYRGYZSTAN"
        ]
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить коды банков"""
        score_contribution = 0
        errors = []
        warnings = []
        
        # Проверка кода банка плательщика
        if data.payer_bank_code not in self.valid_bank_codes:
            score_contribution += 25
            errors.append(f"Неизвестный банк плательщика: {data.payer_bank_code}")
        
        # Проверка кода банка получателя
        if data.receiver_bank_code not in self.valid_bank_codes:
            score_contribution += 25
            errors.append(f"Неизвестный банк получателя: {data.receiver_bank_code}")
        
        # Проверка на самоплатеж
        if data.payer_bank_code == data.receiver_bank_code and data.sender_account == data.receiver_account:
            score_contribution += 5
            warnings.append("Обнаружен самоплатеж")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "payer_bank": data.payer_bank_code,
                "receiver_bank": data.receiver_bank_code,
                "valid_payer_bank": data.payer_bank_code in self.valid_bank_codes,
                "valid_receiver_bank": data.receiver_bank_code in self.valid_bank_codes,
                "self_payment": data.payer_bank_code == data.receiver_bank_code and data.sender_account == data.receiver_account
            }
        )


class TimeBasedRule(BaseRule):
    """
    Правило проверки времени транзакции
    """
    
    def __init__(self, weight: float = 0.5):
        super().__init__("time_based", weight)
        # Рабочие часы в Кыргызстане (UTC+6)
        self.business_hours_start = 9  # 9:00
        self.business_hours_end = 18   # 18:00
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить время транзакции"""
        if not data.created_at:
            return RuleEvaluationResult(
                rule_name=self.name,
                passed=True,
                score_contribution=0,
                warning_message="Время создания транзакции не указано",
                metadata={"created_at": None}
            )
        
        # Конвертируем в местное время (UTC+6)
        local_time = data.created_at + timedelta(hours=6)
        hour = local_time.hour
        weekday = local_time.weekday()  # 0 = Monday, 6 = Sunday
        
        score_contribution = 0
        errors = []
        warnings = []
        
        # Проверка на выходные
        if weekday >= 5:  # Суббота или воскресенье
            score_contribution += 5
            warnings.append(f"Транзакция в выходной день: {local_time.strftime('%A')}")
        
        # Проверка на нерабочие часы
        if hour < self.business_hours_start or hour > self.business_hours_end:
            score_contribution += 3
            warnings.append(f"Транзакция вне рабочих часов: {hour}:00")
        
        # Проверка на ночные часы (подозрительно)
        if hour >= 23 or hour <= 5:
            score_contribution += 10
            warnings.append(f"Ночная транзакция: {hour}:00")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata={
                "created_at": data.created_at.isoformat(),
                "local_time": local_time.isoformat(),
                "hour": hour,
                "weekday": weekday,
                "business_hours": self.business_hours_start <= hour <= self.business_hours_end,
                "is_weekend": weekday >= 5,
                "is_night": hour >= 23 or hour <= 5
            }
        )