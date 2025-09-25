"""
Кастомные исключения для модуля скоринга
"""

from typing import Optional, Dict, Any


class ScoringError(Exception):
    """Базовое исключение для ошибок скоринга"""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code or "SCORING_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class RuleValidationError(ScoringError):
    """Ошибка валидации правила"""
    
    def __init__(
        self, 
        rule_name: str, 
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.rule_name = rule_name
        super().__init__(
            message=f"Rule '{rule_name}' validation failed: {message}",
            error_code="RULE_VALIDATION_ERROR",
            details=details or {"rule_name": rule_name}
        )


class ComplianceCheckError(ScoringError):
    """Ошибка проверки комплаенса"""
    
    def __init__(
        self, 
        check_type: str, 
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.check_type = check_type
        super().__init__(
            message=f"Compliance check '{check_type}' failed: {message}",
            error_code="COMPLIANCE_CHECK_ERROR",
            details=details or {"check_type": check_type}
        )


class ScoringConfigurationError(ScoringError):
    """Ошибка конфигурации скоринга"""
    
    def __init__(
        self, 
        config_key: str, 
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.config_key = config_key
        super().__init__(
            message=f"Configuration error for '{config_key}': {message}",
            error_code="SCORING_CONFIG_ERROR",
            details=details or {"config_key": config_key}
        )


class TransactionDataError(ScoringError):
    """Ошибка данных транзакции"""
    
    def __init__(
        self, 
        field: str, 
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.field = field
        super().__init__(
            message=f"Transaction data error for field '{field}': {message}",
            error_code="TRANSACTION_DATA_ERROR",
            details=details or {"field": field}
        )


class ScoringServiceError(ScoringError):
    """Ошибка сервиса скоринга"""
    
    def __init__(
        self, 
        operation: str, 
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.operation = operation
        super().__init__(
            message=f"Scoring service error during '{operation}': {message}",
            error_code="SCORING_SERVICE_ERROR",
            details=details or {"operation": operation}
        )