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

from .service import ScoringService
from .schemas import TransactionDataForScoring, ScoringResult, ScoringDecision
from .rules import BaseRule
from .exceptions import ScoringError, RuleValidationError

__all__ = [
    "ScoringService",
    "TransactionDataForScoring", 
    "ScoringResult",
    "ScoringDecision",
    "BaseRule",
    "ScoringError",
    "RuleValidationError"
]