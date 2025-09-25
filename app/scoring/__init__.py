"""
Модуль комплаенса и скоринга для QRPayHub

Этот модуль обеспечивает:
- Соответствие регулятивным требованиям Кыргызстана и международным стандартам
- Предотвращение мошенничества и отмывания денег
- Оценку рисков клиентов и транзакций
- Автоматизацию процессов проверки и валидации
- Повышение доверия со стороны банков-партнеров

Уровень 1 - Базовая безопасность и скоринг
"""

from .service import ScoringService, get_scoring_service
from .schemas import TransactionDataForScoring, ScoringResult, ScoringDecision, ScoringConfig
from .rules import (
    BaseRule, 
    AmountLimitRule, 
    TransactionFrequencyRule, 
    SuspiciousPatternsRule, 
    GeolocationRule, 
    PhoneNumberRule, 
    BankCodeRule, 
    TimeBasedRule
)
from .repository import TransactionRepository, create_transaction_repository
from .config import ScoringConfigManager, get_config_manager
from .exceptions import ScoringError, RuleValidationError

__all__ = [
    "ScoringService",
    "get_scoring_service",
    "TransactionDataForScoring", 
    "ScoringResult",
    "ScoringDecision",
    "ScoringConfig",
    "BaseRule",
    "AmountLimitRule",
    "TransactionFrequencyRule",
    "SuspiciousPatternsRule",
    "GeolocationRule",
    "PhoneNumberRule",
    "BankCodeRule",
    "TimeBasedRule",
    "TransactionRepository",
    "create_transaction_repository",
    "ScoringConfigManager",
    "get_config_manager",
    "ScoringError",
    "RuleValidationError"
]