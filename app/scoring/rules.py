"""
Базовые классы и правила для системы скоринга

Содержит абстрактный базовый класс BaseRule и конкретные реализации правил
для проверки различных аспектов транзакций.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import logging
import re
from datetime import datetime, timedelta

from .schemas import TransactionDataForScoring, RuleEvaluationResult, ScoringDecision
from .exceptions import RuleValidationError
from .config import get_config_manager
from .repository import TransactionRepository


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
    Правило проверки лимитов сумм транзакций с учетом истории
    """
    
    def __init__(
        self, 
        repository: Optional[TransactionRepository] = None,
        weight: float = 2.0
    ):
        super().__init__("amount_limit", weight)
        self.repository = repository
        self.config_manager = get_config_manager()
        
        # Загружаем конфигурацию из файла
        config = self.config_manager.get_rule_config("amount_limit")
        self.max_single_transaction = config.get("max_single_transaction", 500000.0)
        self.max_daily_amount = config.get("max_daily_amount", 1000000.0)
        self.max_monthly_amount = config.get("max_monthly_amount", 5000000.0)
        self.check_suspicious_round_amounts = config.get("suspicious_round_amounts", True)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить лимиты сумм с учетом истории транзакций"""
        score_contribution = 0
        errors = []
        warnings = []
        metadata = {
            "max_single_transaction": self.max_single_transaction,
            "amount": data.amount,
            "suspicious_amount": False,
            "daily_amount": 0.0,
            "monthly_amount": 0.0
        }
        
        # Проверка максимальной суммы одной транзакции
        if data.amount > self.max_single_transaction:
            score_contribution += 50
            errors.append(f"Превышен лимит одной транзакции: {data.amount} > {self.max_single_transaction}")
        
        # Проверка на подозрительно круглые суммы
        if self.check_suspicious_round_amounts and self._is_suspicious_amount(data.amount):
            score_contribution += 10
            warnings.append(f"Подозрительно круглая сумма: {data.amount}")
            metadata["suspicious_amount"] = True
        
        # Проверка дневных и месячных лимитов (если есть репозиторий)
        if self.repository:
            try:
                # Получаем статистику за день и месяц
                daily_stats = self.repository.get_daily_transaction_stats(
                    identifier=data.payer_phone or data.sender_account or "",
                    identifier_type="phone" if data.payer_phone else "account",
                    days=1
                )
                
                monthly_stats = self.repository.get_daily_transaction_stats(
                    identifier=data.payer_phone or data.sender_account or "",
                    identifier_type="phone" if data.payer_phone else "account",
                    days=30
                )
                
                daily_amount = daily_stats.get("total_amount", 0.0) + data.amount
                monthly_amount = monthly_stats.get("total_amount", 0.0) + data.amount
                
                metadata["daily_amount"] = daily_amount
                metadata["monthly_amount"] = monthly_amount
                
                # Проверка дневного лимита
                if daily_amount > self.max_daily_amount:
                    score_contribution += 30
                    errors.append(f"Превышен дневной лимит: {daily_amount} > {self.max_daily_amount}")
                
                # Проверка месячного лимита
                if monthly_amount > self.max_monthly_amount:
                    score_contribution += 40
                    errors.append(f"Превышен месячный лимит: {monthly_amount} > {self.max_monthly_amount}")
                
                # Предупреждение при приближении к лимитам
                if daily_amount > self.max_daily_amount * 0.8:
                    warnings.append(f"Приближение к дневному лимиту: {daily_amount}/{self.max_daily_amount}")
                
                if monthly_amount > self.max_monthly_amount * 0.8:
                    warnings.append(f"Приближение к месячному лимиту: {monthly_amount}/{self.max_monthly_amount}")
                    
            except Exception as e:
                self.logger.error(f"Ошибка при получении истории транзакций: {e}")
                warnings.append("Не удалось проверить историю транзакций")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata=metadata
        )
    
    def _is_suspicious_amount(self, amount: float) -> bool:
        """Проверить, является ли сумма подозрительной"""
        # Проверяем на круглые суммы (заканчивающиеся на 000)
        return amount % 1000 == 0 and amount >= 10000


class TransactionFrequencyRule(BaseRule):
    """
    Правило проверки частоты транзакций с учетом истории
    """
    
    def __init__(
        self,
        repository: Optional[TransactionRepository] = None,
        weight: float = 1.5
    ):
        super().__init__("transaction_frequency", weight)
        self.repository = repository
        self.config_manager = get_config_manager()
        
        # Загружаем конфигурацию из файла
        config = self.config_manager.get_rule_config("frequency")
        self.max_transactions_per_hour = config.get("max_transactions_per_hour", 10)
        self.max_transactions_per_day = config.get("max_transactions_per_day", 50)
        self.max_transactions_per_week = config.get("max_transactions_per_week", 200)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить частоту транзакций с учетом истории"""
        score_contribution = 0
        errors = []
        warnings = []
        
        metadata = {
            "hourly_count": 0,
            "daily_count": 0,
            "weekly_count": 0,
            "max_hourly": self.max_transactions_per_hour,
            "max_daily": self.max_transactions_per_day,
            "max_weekly": self.max_transactions_per_week
        }
        
        if self.repository:
            try:
                identifier = data.payer_phone or data.sender_account or ""
                identifier_type = "phone" if data.payer_phone else "account"
                
                # Получаем количество транзакций за час
                hourly_count = self.repository.get_hourly_transaction_count(
                    identifier=identifier,
                    identifier_type=identifier_type,
                    hours=1
                ) + 1  # +1 для текущей транзакции
                
                # Получаем статистику за день
                daily_stats = self.repository.get_daily_transaction_stats(
                    identifier=identifier,
                    identifier_type=identifier_type,
                    days=1
                )
                daily_count = daily_stats.get("total_transactions", 0) + 1
                
                # Получаем статистику за неделю
                weekly_stats = self.repository.get_daily_transaction_stats(
                    identifier=identifier,
                    identifier_type=identifier_type,
                    days=7
                )
                weekly_count = weekly_stats.get("total_transactions", 0) + 1
                
                metadata.update({
                    "hourly_count": hourly_count,
                    "daily_count": daily_count,
                    "weekly_count": weekly_count
                })
                
                # Проверка лимитов
                if hourly_count > self.max_transactions_per_hour:
                    score_contribution += 30
                    errors.append(f"Превышен лимит транзакций в час: {hourly_count} > {self.max_transactions_per_hour}")
                
                if daily_count > self.max_transactions_per_day:
                    score_contribution += 20
                    errors.append(f"Превышен лимит транзакций в день: {daily_count} > {self.max_transactions_per_day}")
                
                if weekly_count > self.max_transactions_per_week:
                    score_contribution += 15
                    errors.append(f"Превышен лимит транзакций в неделю: {weekly_count} > {self.max_transactions_per_week}")
                
                # Предупреждения при приближении к лимитам
                if hourly_count > self.max_transactions_per_hour * 0.8:
                    warnings.append(f"Высокая частота транзакций в час: {hourly_count}")
                
                if daily_count > self.max_transactions_per_day * 0.8:
                    warnings.append(f"Высокая частота транзакций в день: {daily_count}")
                
                if weekly_count > self.max_transactions_per_week * 0.8:
                    warnings.append(f"Высокая частота транзакций в неделю: {weekly_count}")
                    
            except Exception as e:
                self.logger.error(f"Ошибка при проверке частоты транзакций: {e}")
                warnings.append("Не удалось проверить частоту транзакций")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata=metadata
        )


class GeolocationRule(BaseRule):
    """
    Правило проверки геолокации (IP-адрес) с улучшенной заглушкой
    """
    
    def __init__(self, weight: float = 1.0):
        super().__init__("geolocation", weight)
        self.config_manager = get_config_manager()
        
        # Загружаем конфигурацию из файла
        config = self.config_manager.get_rule_config("geolocation")
        self.allowed_countries = config.get("allowed_countries", ["KG", "KZ", "UZ", "TJ", "RU", "CN"])
        self.suspicious_countries = config.get("suspicious_countries", ["AF", "IR", "KP", "SY"])
        self.require_ip = config.get("require_ip", False)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить геолокацию по IP-адресу"""
        if not data.ip_address:
            if self.require_ip:
                return RuleEvaluationResult(
                    rule_name=self.name,
                    passed=False,
                    score_contribution=10,
                    error_message="IP-адрес обязателен для проверки геолокации",
                    metadata={"ip_address": None, "country": None}
                )
            else:
                return RuleEvaluationResult(
                    rule_name=self.name,
                    passed=True,
                    score_contribution=0,
                    warning_message="IP-адрес не предоставлен",
                    metadata={"ip_address": None, "country": None}
                )
        
        # Определяем страну по IP-адресу
        country_info = self._get_country_by_ip(data.ip_address)
        country = country_info.get("country", "UNKNOWN")
        
        score_contribution = 0
        errors = []
        warnings = []
        
        metadata = {
            "ip_address": data.ip_address,
            "country": country,
            "country_info": country_info,
            "allowed_countries": self.allowed_countries,
            "suspicious_countries": self.suspicious_countries
        }
        
        # Проверка на санкционные страны
        if country in self.suspicious_countries:
            score_contribution += 40
            errors.append(f"IP-адрес из санкционной страны: {country}")
        
        # Проверка на неразрешенные страны
        elif country not in self.allowed_countries and country != "UNKNOWN":
            score_contribution += 20
            warnings.append(f"IP-адрес из неразрешенной страны: {country}")
        
        # Проверка на неизвестную страну
        elif country == "UNKNOWN":
            score_contribution += 5
            warnings.append("Не удалось определить страну по IP-адресу")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata=metadata
        )
    
    def _get_country_by_ip(self, ip_address: str) -> Dict[str, Any]:
        """
        Определить страну по IP-адресу (улучшенная заглушка)
        
        В реальной реализации здесь должен быть вызов к сервису геолокации
        (например, MaxMind GeoIP2, ipapi.co, ipgeolocation.io)
        """
        try:
            # Простая заглушка на основе диапазонов IP
            # В реальной реализации использовать библиотеку типа geoip2
            
            # Локальные IP-адреса
            if ip_address.startswith(("192.168.", "10.", "172.")):
                return {
                    "country": "LOCAL",
                    "country_name": "Local Network",
                    "region": "Local",
                    "city": "Local",
                    "confidence": 1.0
                }
            
            # Заглушка для тестовых IP
            if ip_address.startswith("127.") or ip_address == "localhost":
                return {
                    "country": "KG",
                    "country_name": "Kyrgyzstan",
                    "region": "Bishkek",
                    "city": "Bishkek",
                    "confidence": 0.8
                }
            
            # Простая эмуляция по последним октетам IP
            # Это НЕ реальная геолокация, только для демонстрации
            last_octet = int(ip_address.split('.')[-1]) if '.' in ip_address else 0
            
            if last_octet < 50:
                return {
                    "country": "KG",
                    "country_name": "Kyrgyzstan",
                    "region": "Bishkek",
                    "city": "Bishkek",
                    "confidence": 0.6
                }
            elif last_octet < 100:
                return {
                    "country": "KZ",
                    "country_name": "Kazakhstan",
                    "region": "Almaty",
                    "city": "Almaty",
                    "confidence": 0.6
                }
            elif last_octet < 150:
                return {
                    "country": "RU",
                    "country_name": "Russia",
                    "region": "Moscow",
                    "city": "Moscow",
                    "confidence": 0.6
                }
            elif last_octet < 200:
                return {
                    "country": "UZ",
                    "country_name": "Uzbekistan",
                    "region": "Tashkent",
                    "city": "Tashkent",
                    "confidence": 0.6
                }
            else:
                # Подозрительные IP (имитируем)
                return {
                    "country": "AF",
                    "country_name": "Afghanistan",
                    "region": "Unknown",
                    "city": "Unknown",
                    "confidence": 0.4
                }
                
        except Exception as e:
            self.logger.error(f"Ошибка при определении геолокации для IP {ip_address}: {e}")
            return {
                "country": "UNKNOWN",
                "country_name": "Unknown",
                "region": "Unknown",
                "city": "Unknown",
                "confidence": 0.0,
                "error": str(e)
            }


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


class SuspiciousPatternsRule(BaseRule):
    """
    Правило проверки подозрительных паттернов в описании транзакции
    """
    
    def __init__(self, weight: float = 3.0):
        super().__init__("suspicious_patterns", weight)
        self.config_manager = get_config_manager()
        
        # Загружаем конфигурацию из файла
        config = self.config_manager.get_rule_config("suspicious_patterns")
        self.case_sensitive = config.get("case_sensitive", False)
        self.exact_match = config.get("exact_match", False)
        self.enabled_categories = config.get("categories", ["fraud_keywords", "money_laundering_keywords"])
        
        # Загружаем подозрительные слова
        self.suspicious_words = {}
        for category in self.enabled_categories:
            self.suspicious_words[category] = self.config_manager.get_suspicious_words(category)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Проверить подозрительные паттерны в описании"""
        score_contribution = 0
        errors = []
        warnings = []
        
        metadata = {
            "description": data.description,
            "found_patterns": [],
            "categories_checked": list(self.suspicious_words.keys()),
            "case_sensitive": self.case_sensitive,
            "exact_match": self.exact_match
        }
        
        if not data.description:
            return RuleEvaluationResult(
                rule_name=self.name,
                passed=True,
                score_contribution=0,
                warning_message="Описание транзакции не предоставлено",
                metadata=metadata
            )
        
        # Проверяем каждую категорию подозрительных слов
        found_patterns = []
        
        for category, words in self.suspicious_words.items():
            for word in words:
                if self._check_word_in_description(data.description, word):
                    found_patterns.append({
                        "category": category,
                        "word": word,
                        "severity": self._get_category_severity(category)
                    })
        
        metadata["found_patterns"] = found_patterns
        
        if found_patterns:
            # Вычисляем балл на основе найденных паттернов
            for pattern in found_patterns:
                severity = pattern["severity"]
                if severity == "high":
                    score_contribution += 25
                elif severity == "medium":
                    score_contribution += 15
                else:  # low
                    score_contribution += 10
            
            # Формируем сообщения об ошибках
            high_severity = [p for p in found_patterns if p["severity"] == "high"]
            medium_severity = [p for p in found_patterns if p["severity"] == "medium"]
            low_severity = [p for p in found_patterns if p["severity"] == "low"]
            
            if high_severity:
                high_words = [p["word"] for p in high_severity]
                errors.append(f"Найдены высокорисковые слова в описании: {', '.join(high_words)}")
            
            if medium_severity:
                medium_words = [p["word"] for p in medium_severity]
                errors.append(f"Найдены среднерисковые слова в описании: {', '.join(medium_words)}")
            
            if low_severity:
                low_words = [p["word"] for p in low_severity]
                warnings.append(f"Найдены низкорисковые слова в описании: {', '.join(low_words)}")
        
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=len(errors) == 0,
            score_contribution=score_contribution,
            error_message="; ".join(errors) if errors else None,
            warning_message="; ".join(warnings) if warnings else None,
            metadata=metadata
        )
    
    def _check_word_in_description(self, description: str, word: str) -> bool:
        """Проверить наличие слова в описании"""
        if not description or not word:
            return False
        
        # Подготавливаем текст для поиска
        search_text = description if self.case_sensitive else description.lower()
        search_word = word if self.case_sensitive else word.lower()
        
        if self.exact_match:
            # Точное совпадение (слово целиком)
            import re
            pattern = r'\b' + re.escape(search_word) + r'\b'
            return bool(re.search(pattern, search_text))
        else:
            # Частичное совпадение
            return search_word in search_text
    
    def _get_category_severity(self, category: str) -> str:
        """Получить уровень серьезности категории"""
        severity_map = {
            "fraud_keywords": "high",
            "money_laundering_keywords": "high",
            "terrorism_keywords": "high",
            "drugs_keywords": "medium",
            "weapons_keywords": "medium",
            "prostitution_keywords": "medium",
            "gambling_keywords": "low",
            "sanctions_keywords": "medium"
        }
        return severity_map.get(category, "low")
    
    def add_custom_pattern(self, category: str, word: str) -> None:
        """Добавить пользовательское подозрительное слово"""
        if category not in self.suspicious_words:
            self.suspicious_words[category] = []
        
        if word not in self.suspicious_words[category]:
            self.suspicious_words[category].append(word)
            # Сохраняем в конфигурацию
            self.config_manager.update_suspicious_words(category, self.suspicious_words[category])
            self.logger.info(f"Добавлено новое подозрительное слово: '{word}' в категорию '{category}'")


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