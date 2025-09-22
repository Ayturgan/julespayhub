import re
import hashlib
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity
from app.models.payment import Bank, PaymentRequest
import logging

logger = logging.getLogger(__name__)

class ValidationSeverity(Enum):
    """Уровни серьезности ошибок валидации"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class ValidationResult:
    """Результат валидации"""
    valid: bool
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    info: List[Dict[str, Any]]
    
    def add_error(self, field: str, message: str, code: str = "VALIDATION_ERROR", details: Optional[Dict] = None):
        """Добавление ошибки"""
        self.valid = False
        self.errors.append({
            "field": field,
            "message": message,
            "code": code,
            "severity": ValidationSeverity.ERROR.value,
            "details": details or {}
        })
    
    def add_warning(self, field: str, message: str, code: str = "VALIDATION_WARNING", details: Optional[Dict] = None):
        """Добавление предупреждения"""
        self.warnings.append({
            "field": field,
            "message": message,
            "code": code,
            "severity": ValidationSeverity.WARNING.value,
            "details": details or {}
        })
    
    def add_info(self, field: str, message: str, details: Optional[Dict] = None):
        """Добавление информационного сообщения"""
        self.info.append({
            "field": field,
            "message": message,
            "severity": ValidationSeverity.INFO.value,
            "details": details or {}
        })
    
    def has_errors(self) -> bool:
        """Проверка наличия ошибок"""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Проверка наличия предупреждений"""
        return len(self.warnings) > 0
    
    def get_summary(self) -> Dict[str, Any]:
        """Получение сводки валидации"""
        return {
            "valid": self.valid,
            "total_issues": len(self.errors) + len(self.warnings) + len(self.info),
            "errors_count": len(self.errors),
            "warnings_count": len(self.warnings),
            "info_count": len(self.info)
        }

class EnhancedValidationService:
    """Сервис расширенной валидации входных данных"""
    
    # Регулярные выражения для валидации
    PHONE_PATTERNS = {
        "kyrgyzstan": r"^(\+996|996|0)?[0-9]{9}$",
        "international": r"^\+[1-9]\d{1,14}$",
        "any": r"^[\+]?[0-9\-\(\)\s]{7,20}$"
    }
    
    ACCOUNT_PATTERNS = {
        "numeric": r"^[0-9]{10,20}$",
        "alphanumeric": r"^[A-Z0-9]{8,25}$",
        "iban": r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]?){0,16}$"
    }
    
    BANK_CODE_PATTERNS = {
        "kyrgyzstan": r"^[A-Z]{1,2}[0-9]{3,5}$",
        "swift": r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$",
        "custom": r"^[A-Z0-9]{3,10}$"
    }
    
    # Подозрительные паттерны в описаниях
    SUSPICIOUS_PATTERNS = [
        r"(?i)(наркотик|оружие|взрывчатк)",  # Запрещенные товары
        r"(?i)(отмывание|легализация)",       # Отмывание денег
        r"(?i)(казино|ставки|лотерея)",       # Азартные игры
        r"(?i)(секс|эскорт|проститут)",       # Интимные услуги
        r"(?i)(пирамида|хайп|инвест.*гарант)", # Финансовые пирамиды
        r"(?i)(биткоин|крипто|майнинг)",      # Криптовалюты (если запрещены)
    ]
    
    # Лимиты по умолчанию
    DEFAULT_LIMITS = {
        "min_amount": Decimal("0.01"),
        "max_amount": Decimal("10000000.00"),  # 10 млн
        "max_description_length": 500,
        "max_receiver_name_length": 255,
        "daily_transaction_limit": Decimal("1000000.00"),  # 1 млн в день
        "monthly_transaction_limit": Decimal("10000000.00")  # 10 млн в месяц
    }
    
    @staticmethod
    def validate_payment_request(
        data: Dict[str, Any],
        bank: Optional[Bank] = None,
        strict_mode: bool = False
    ) -> ValidationResult:
        """
        Комплексная валидация платежного запроса
        
        Args:
            data: Данные платежного запроса
            bank: Банк для специфичных проверок
            strict_mode: Строгий режим валидации
            
        Returns:
            ValidationResult: Результат валидации
        """
        
        result = ValidationResult(valid=True, errors=[], warnings=[], info=[])
        
        # 1. Базовая валидация полей
        EnhancedValidationService._validate_required_fields(data, result)
        
        # 2. Валидация форматов данных
        EnhancedValidationService._validate_data_formats(data, result)
        
        # 3. Валидация бизнес-логики
        EnhancedValidationService._validate_business_rules(data, result, bank)
        
        # 4. Проверка на подозрительные паттерны
        EnhancedValidationService._validate_security_patterns(data, result, strict_mode)
        
        # 5. Валидация лимитов
        EnhancedValidationService._validate_limits(data, result, bank)
        
        # 6. Проверка целостности данных
        EnhancedValidationService._validate_data_integrity(data, result)
        
        # 7. Банк-специфичная валидация
        if bank:
            EnhancedValidationService._validate_bank_specific(data, result, bank)
        
        logger.info(f"Payment validation completed: {result.get_summary()}")
        
        return result
    
    @staticmethod
    def _validate_required_fields(data: Dict[str, Any], result: ValidationResult):
        """Валидация обязательных полей"""
        
        required_fields = [
            "receiver_account",
            "receiver_bank_code", 
            "receiver_name",
            "description"
        ]
        
        for field in required_fields:
            if field not in data or not data[field]:
                result.add_error(
                    field=field,
                    message=f"Поле '{field}' обязательно для заполнения",
                    code="MISSING_REQUIRED_FIELD"
                )
            elif isinstance(data[field], str) and not data[field].strip():
                result.add_error(
                    field=field,
                    message=f"Поле '{field}' не может быть пустым",
                    code="EMPTY_REQUIRED_FIELD"
                )
    
    @staticmethod
    def _validate_data_formats(data: Dict[str, Any], result: ValidationResult):
        """Валидация форматов данных"""
        
        # Валидация номера счета
        if "receiver_account" in data and data["receiver_account"]:
            account = str(data["receiver_account"]).strip()
            
            # Проверяем различные форматы счетов
            valid_format = False
            for pattern_name, pattern in EnhancedValidationService.ACCOUNT_PATTERNS.items():
                if re.match(pattern, account):
                    valid_format = True
                    result.add_info(
                        "receiver_account",
                        f"Номер счета соответствует формату: {pattern_name}",
                        {"detected_format": pattern_name}
                    )
                    break
            
            if not valid_format:
                result.add_error(
                    field="receiver_account",
                    message="Неверный формат номера счета",
                    code="INVALID_ACCOUNT_FORMAT",
                    details={"value": account[:10] + "..." if len(account) > 10 else account}
                )
        
        # Валидация кода банка
        if "receiver_bank_code" in data and data["receiver_bank_code"]:
            bank_code = str(data["receiver_bank_code"]).strip().upper()
            
            valid_format = False
            for pattern_name, pattern in EnhancedValidationService.BANK_CODE_PATTERNS.items():
                if re.match(pattern, bank_code):
                    valid_format = True
                    result.add_info(
                        "receiver_bank_code",
                        f"Код банка соответствует формату: {pattern_name}",
                        {"detected_format": pattern_name}
                    )
                    break
            
            if not valid_format:
                result.add_warning(
                    field="receiver_bank_code",
                    message="Нестандартный формат кода банка",
                    code="UNUSUAL_BANK_CODE_FORMAT",
                    details={"value": bank_code}
                )
        
        # Валидация суммы
        if "amount" in data and data["amount"] is not None:
            try:
                amount = Decimal(str(data["amount"]))
                
                # Проверка на отрицательные значения
                if amount <= 0:
                    result.add_error(
                        field="amount",
                        message="Сумма должна быть больше нуля",
                        code="INVALID_AMOUNT_VALUE"
                    )
                
                # Проверка на разумное количество десятичных знаков
                if amount.as_tuple().exponent < -4:  # Более 4 знаков после запятой
                    result.add_warning(
                        field="amount",
                        message="Слишком много десятичных знаков в сумме",
                        code="EXCESSIVE_DECIMAL_PLACES",
                        details={"decimal_places": abs(amount.as_tuple().exponent)}
                    )
                
            except (InvalidOperation, ValueError, TypeError):
                result.add_error(
                    field="amount",
                    message="Неверный формат суммы",
                    code="INVALID_AMOUNT_FORMAT"
                )
        
        # Валидация валюты
        if "currency" in data and data["currency"]:
            currency = str(data["currency"]).upper().strip()
            
            # Список поддерживаемых валют
            supported_currencies = ["KGS", "USD", "EUR", "RUB"]
            
            if currency not in supported_currencies:
                result.add_error(
                    field="currency",
                    message=f"Неподдерживаемая валюта: {currency}",
                    code="UNSUPPORTED_CURRENCY",
                    details={"supported_currencies": supported_currencies}
                )
    
    @staticmethod
    def _validate_business_rules(
        data: Dict[str, Any], 
        result: ValidationResult, 
        bank: Optional[Bank]
    ):
        """Валидация бизнес-правил"""
        
        # Проверка соответствия банка получателя
        if "receiver_bank_code" in data and bank:
            receiver_bank_code = str(data["receiver_bank_code"]).upper()
            
            # Если платеж внутри одного банка - это хорошо для комиссий
            if receiver_bank_code == bank.code.upper():
                result.add_info(
                    "receiver_bank_code",
                    "Платеж внутри банка - комиссия не взимается",
                    {"intra_bank_transfer": True}
                )
            else:
                result.add_info(
                    "receiver_bank_code",
                    "Межбанковский платеж",
                    {"inter_bank_transfer": True, "receiver_bank": receiver_bank_code}
                )
        
        # Проверка длины описания
        if "description" in data and data["description"]:
            description = str(data["description"]).strip()
            
            if len(description) > EnhancedValidationService.DEFAULT_LIMITS["max_description_length"]:
                result.add_error(
                    field="description",
                    message=f"Описание слишком длинное (максимум {EnhancedValidationService.DEFAULT_LIMITS['max_description_length']} символов)",
                    code="DESCRIPTION_TOO_LONG",
                    details={"current_length": len(description)}
                )
            
            if len(description) < 5:
                result.add_warning(
                    field="description",
                    message="Слишком короткое описание платежа",
                    code="DESCRIPTION_TOO_SHORT"
                )
        
        # Проверка длины имени получателя
        if "receiver_name" in data and data["receiver_name"]:
            receiver_name = str(data["receiver_name"]).strip()
            
            if len(receiver_name) > EnhancedValidationService.DEFAULT_LIMITS["max_receiver_name_length"]:
                result.add_error(
                    field="receiver_name",
                    message=f"Имя получателя слишком длинное (максимум {EnhancedValidationService.DEFAULT_LIMITS['max_receiver_name_length']} символов)",
                    code="RECEIVER_NAME_TOO_LONG"
                )
            
            if len(receiver_name) < 2:
                result.add_error(
                    field="receiver_name",
                    message="Имя получателя слишком короткое",
                    code="RECEIVER_NAME_TOO_SHORT"
                )
    
    @staticmethod
    def _validate_security_patterns(
        data: Dict[str, Any], 
        result: ValidationResult, 
        strict_mode: bool
    ):
        """Проверка на подозрительные паттерны"""
        
        # Проверяем описание на подозрительные паттерны
        if "description" in data and data["description"]:
            description = str(data["description"]).lower()
            
            for pattern in EnhancedValidationService.SUSPICIOUS_PATTERNS:
                if re.search(pattern, description):
                    if strict_mode:
                        result.add_error(
                            field="description",
                            message="Описание содержит запрещенные термины",
                            code="SUSPICIOUS_DESCRIPTION_PATTERN",
                            details={"pattern_matched": True}
                        )
                    else:
                        result.add_warning(
                            field="description",
                            message="Описание может содержать подозрительные термины",
                            code="POTENTIALLY_SUSPICIOUS_DESCRIPTION"
                        )
                    break
        
        # Проверяем имя получателя
        if "receiver_name" in data and data["receiver_name"]:
            receiver_name = str(data["receiver_name"]).lower()
            
            # Проверка на подозрительные имена
            suspicious_names = ["test", "admin", "система", "банк", "казино"]
            
            for suspicious in suspicious_names:
                if suspicious in receiver_name:
                    result.add_warning(
                        field="receiver_name",
                        message="Подозрительное имя получателя",
                        code="SUSPICIOUS_RECEIVER_NAME",
                        details={"matched_pattern": suspicious}
                    )
                    break
        
        # Проверка на дублированные символы (возможная атака)
        for field in ["description", "receiver_name"]:
            if field in data and data[field]:
                text = str(data[field])
                
                # Проверяем на повторяющиеся символы
                for char in "abcdefghijklmnopqrstuvwxyz0123456789":
                    if char * 10 in text.lower():  # 10 одинаковых символов подряд
                        result.add_warning(
                            field=field,
                            message="Обнаружены повторяющиеся символы",
                            code="REPEATED_CHARACTERS_DETECTED",
                            details={"repeated_char": char}
                        )
                        break
    
    @staticmethod
    def _validate_limits(
        data: Dict[str, Any], 
        result: ValidationResult, 
        bank: Optional[Bank]
    ):
        """Валидация лимитов"""
        
        if "amount" in data and data["amount"] is not None:
            try:
                amount = Decimal(str(data["amount"]))
                
                # Базовые лимиты
                min_amount = EnhancedValidationService.DEFAULT_LIMITS["min_amount"]
                max_amount = EnhancedValidationService.DEFAULT_LIMITS["max_amount"]
                
                if amount < min_amount:
                    result.add_error(
                        field="amount",
                        message=f"Сумма меньше минимального лимита ({min_amount})",
                        code="AMOUNT_BELOW_MINIMUM",
                        details={"min_amount": str(min_amount)}
                    )
                
                if amount > max_amount:
                    result.add_error(
                        field="amount",
                        message=f"Сумма превышает максимальный лимит ({max_amount})",
                        code="AMOUNT_ABOVE_MAXIMUM",
                        details={"max_amount": str(max_amount)}
                    )
                
                # Предупреждения для больших сумм
                if amount > Decimal("100000"):  # 100k
                    result.add_warning(
                        field="amount",
                        message="Крупная сумма платежа требует дополнительной проверки",
                        code="LARGE_AMOUNT_WARNING",
                        details={"amount": str(amount)}
                    )
                
                # Банк-специфичные лимиты (если банк настроен через адаптер)
                if bank:
                    from app.services.bank_adapter_service import bank_adapter_service
                    
                    validation_errors = bank_adapter_service.validate_payment_for_bank(
                        bank.code, float(amount), data.get("currency", "KGS")
                    )
                    
                    for error in validation_errors:
                        result.add_error(
                            field="amount",
                            message=error,
                            code="BANK_SPECIFIC_LIMIT_VIOLATION"
                        )
                
            except (InvalidOperation, ValueError):
                # Ошибка уже добавлена в _validate_data_formats
                pass
    
    @staticmethod
    def _validate_data_integrity(data: Dict[str, Any], result: ValidationResult):
        """Проверка целостности данных"""
        
        # Проверка на SQL injection паттерны
        sql_patterns = [
            r"(?i)(union\s+select|drop\s+table|delete\s+from)",
            r"(?i)('.*'|\".*\"|\-\-|\*|;)",
            r"(?i)(script|javascript|vbscript|onload|onerror)"
        ]
        
        text_fields = ["description", "receiver_name"]
        
        for field in text_fields:
            if field in data and data[field]:
                text = str(data[field])
                
                for pattern in sql_patterns:
                    if re.search(pattern, text):
                        result.add_error(
                            field=field,
                            message="Обнаружены потенциально опасные символы",
                            code="SECURITY_VIOLATION_DETECTED",
                            details={"security_check": "sql_injection"}
                        )
                        break
        
        # Проверка на XSS паттерны
        xss_patterns = [
            r"(?i)(<script|</script>|<iframe|javascript:|vbscript:)",
            r"(?i)(onload|onerror|onclick|onmouseover)=",
            r"(?i)(<img.*src=|<object|<embed)"
        ]
        
        for field in text_fields:
            if field in data and data[field]:
                text = str(data[field])
                
                for pattern in xss_patterns:
                    if re.search(pattern, text):
                        result.add_error(
                            field=field,
                            message="Обнаружены потенциально опасные HTML/JS конструкции",
                            code="XSS_VIOLATION_DETECTED",
                            details={"security_check": "xss"}
                        )
                        break
        
        # Проверка на чрезмерно длинные строки (возможная DoS атака)
        for field, value in data.items():
            if isinstance(value, str) and len(value) > 10000:  # 10KB
                result.add_error(
                    field=field,
                    message="Значение поля слишком длинное",
                    code="FIELD_TOO_LONG",
                    details={"length": len(value), "max_allowed": 10000}
                )
    
    @staticmethod
    def _validate_bank_specific(
        data: Dict[str, Any], 
        result: ValidationResult, 
        bank: Bank
    ):
        """Банк-специфичная валидация"""
        
        # Проверяем активность банка
        if not bank.is_active:
            result.add_error(
                field="receiver_bank_code",
                message=f"Банк {bank.code} временно недоступен",
                code="BANK_INACTIVE"
            )
        
        # Проверяем последнее использование банка
        if bank.last_used_at:
            time_since_last_use = datetime.now() - bank.last_used_at
            
            if time_since_last_use > timedelta(days=30):
                result.add_warning(
                    field="receiver_bank_code",
                    message="Банк долго не использовался",
                    code="BANK_INACTIVE_WARNING",
                    details={"days_inactive": time_since_last_use.days}
                )
        
        # Дополнительные проверки через адаптер банка
        try:
            from app.services.bank_adapter_service import bank_adapter_service
            
            capabilities = bank_adapter_service.get_bank_capabilities(bank.code)
            
            if "error" not in capabilities:
                # Проверяем поддержку валюты
                currency = data.get("currency", "KGS")
                supported_currencies = capabilities.get("supported_currencies", ["KGS"])
                
                if currency not in supported_currencies:
                    result.add_error(
                        field="currency",
                        message=f"Банк {bank.code} не поддерживает валюту {currency}",
                        code="CURRENCY_NOT_SUPPORTED_BY_BANK",
                        details={"supported_currencies": supported_currencies}
                    )
                
                # Проверяем лимиты банка
                amount_limits = capabilities.get("amount_limits", {})
                if "amount" in data and data["amount"] is not None:
                    amount = Decimal(str(data["amount"]))
                    
                    if amount_limits.get("min") and amount < Decimal(str(amount_limits["min"])):
                        result.add_error(
                            field="amount",
                            message=f"Сумма ниже минимального лимита банка ({amount_limits['min']})",
                            code="BANK_MIN_AMOUNT_VIOLATION"
                        )
                    
                    if amount_limits.get("max") and amount > Decimal(str(amount_limits["max"])):
                        result.add_error(
                            field="amount",
                            message=f"Сумма превышает максимальный лимит банка ({amount_limits['max']})",
                            code="BANK_MAX_AMOUNT_VIOLATION"
                        )
        
        except Exception as e:
            logger.warning(f"Bank-specific validation failed for {bank.code}: {e}")
            result.add_info(
                "validation",
                "Не удалось выполнить банк-специфичную валидацию",
                {"error": str(e)}
            )
    
    @staticmethod
    def validate_webhook_data(
        data: Dict[str, Any],
        bank: Optional[Bank] = None
    ) -> ValidationResult:
        """Валидация данных webhook"""
        
        result = ValidationResult(valid=True, errors=[], warnings=[], info=[])
        
        # Обязательные поля для webhook
        required_fields = ["token", "status", "transaction_id"]
        
        for field in required_fields:
            if field not in data or not data[field]:
                result.add_error(
                    field=field,
                    message=f"Поле '{field}' обязательно для webhook",
                    code="MISSING_WEBHOOK_FIELD"
                )
        
        # Валидация статуса
        if "status" in data:
            valid_statuses = ["success", "failed", "pending", "cancelled"]
            if data["status"] not in valid_statuses:
                result.add_error(
                    field="status",
                    message=f"Неверный статус: {data['status']}",
                    code="INVALID_WEBHOOK_STATUS",
                    details={"valid_statuses": valid_statuses}
                )
        
        # Валидация transaction_id
        if "transaction_id" in data and data["transaction_id"]:
            transaction_id = str(data["transaction_id"])
            
            if len(transaction_id) < 3:
                result.add_error(
                    field="transaction_id",
                    message="ID транзакции слишком короткий",
                    code="TRANSACTION_ID_TOO_SHORT"
                )
            
            if len(transaction_id) > 100:
                result.add_error(
                    field="transaction_id", 
                    message="ID транзакции слишком длинный",
                    code="TRANSACTION_ID_TOO_LONG"
                )
        
        # Валидация суммы (если присутствует)
        if "amount" in data and data["amount"] is not None:
            try:
                amount = Decimal(str(data["amount"]))
                if amount <= 0:
                    result.add_error(
                        field="amount",
                        message="Сумма в webhook должна быть больше нуля",
                        code="INVALID_WEBHOOK_AMOUNT"
                    )
            except (InvalidOperation, ValueError):
                result.add_error(
                    field="amount",
                    message="Неверный формат суммы в webhook",
                    code="INVALID_WEBHOOK_AMOUNT_FORMAT"
                )
        
        # Валидация телефона плательщика
        if "payer_phone" in data and data["payer_phone"]:
            phone = str(data["payer_phone"])
            
            valid_phone = False
            for pattern in EnhancedValidationService.PHONE_PATTERNS.values():
                if re.match(pattern, phone):
                    valid_phone = True
                    break
            
            if not valid_phone:
                result.add_warning(
                    field="payer_phone",
                    message="Нестандартный формат номера телефона",
                    code="UNUSUAL_PHONE_FORMAT"
                )
        
        # Валидация timestamp
        if "timestamp" in data and data["timestamp"]:
            timestamp_str = str(data["timestamp"])
            
            try:
                # Пробуем парсить как ISO формат
                datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Пробуем как Unix timestamp
                    timestamp_int = int(timestamp_str)
                    datetime.fromtimestamp(timestamp_int)
                except (ValueError, OSError):
                    result.add_warning(
                        field="timestamp",
                        message="Неверный формат временной метки",
                        code="INVALID_TIMESTAMP_FORMAT"
                    )
        
        return result
    
    @staticmethod
    def create_validation_summary(validation_results: List[ValidationResult]) -> Dict[str, Any]:
        """Создание сводки по результатам валидации"""
        
        total_validations = len(validation_results)
        successful_validations = len([r for r in validation_results if r.valid])
        
        all_errors = []
        all_warnings = []
        
        for result in validation_results:
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
        
        # Группируем ошибки по кодам
        error_codes = {}
        for error in all_errors:
            code = error.get("code", "UNKNOWN")
            error_codes[code] = error_codes.get(code, 0) + 1
        
        return {
            "total_validations": total_validations,
            "successful_validations": successful_validations,
            "failed_validations": total_validations - successful_validations,
            "success_rate": round((successful_validations / total_validations) * 100, 2) if total_validations > 0 else 0,
            "total_errors": len(all_errors),
            "total_warnings": len(all_warnings),
            "most_common_errors": sorted(error_codes.items(), key=lambda x: x[1], reverse=True)[:5]
        }
