# Модуль комплаенса и скоринга QRPayHub

## Обзор

Модуль скоринга обеспечивает автоматическую оценку рисков транзакций в соответствии с регулятивными требованиями Кыргызстана и международными стандартами.

## Основные возможности

- **Соответствие регулятивным требованиям** Кыргызстана и международным стандартам
- **Предотвращение мошенничества** и отмывания денег
- **Оценка рисков** клиентов и транзакций
- **Автоматизация процессов** проверки и валидации
- **Повышение доверия** со стороны банков-партнеров

## Архитектура

### Основные компоненты

- `service.py` - Основной сервис скоринга
- `schemas.py` - Pydantic схемы данных
- `rules.py` - Правила оценки рисков
- `exceptions.py` - Кастомные исключения

### Правила скоринга

1. **AmountLimitRule** - Проверка лимитов сумм
2. **FrequencyRule** - Проверка частоты транзакций
3. **GeolocationRule** - Проверка геолокации по IP
4. **PhoneNumberRule** - Проверка номера телефона
5. **BankCodeRule** - Проверка кодов банков
6. **TimeBasedRule** - Проверка времени транзакции

## Использование

### Базовое использование

```python
from app.scoring.service import get_scoring_service
from app.scoring.schemas import TransactionDataForScoring

# Создание данных транзакции
transaction_data = TransactionDataForScoring(
    amount=15000.0,
    currency="KGS",
    payment_reference="PAY-001",
    payer_phone="+996555123456",
    payer_bank_code="DEMIR",
    sender_account="1234567890123456",
    receiver_account="9876543210987654",
    receiver_bank_code="OPTIMA",
    receiver_name="Test Merchant"
)

# Получение сервиса скоринга
scoring_service = get_scoring_service()

# Оценка транзакции
result = scoring_service.evaluate_transaction(transaction_data)

print(f"Балл: {result.score}/100")
print(f"Решение: {result.decision.value}")
```

### Конфигурация

```python
from app.scoring.schemas import ScoringConfig

config = ScoringConfig(
    allow_threshold=30,      # Порог для разрешения
    review_threshold=70,     # Порог для ручной проверки
    enabled_rules=["amount_limit", "geolocation", "phone_number"],
    daily_transaction_limit=1000000.0,
    monthly_transaction_limit=30000000.0
)

scoring_service = get_scoring_service(config)
```

## Результаты скоринга

### ScoringDecision

- `ALLOW` - Разрешить транзакцию
- `REVIEW` - Требуется ручная проверка
- `BLOCK` - Заблокировать транзакцию

### ScoringResult

```python
class ScoringResult(BaseModel):
    score: int                    # Скоринговый балл (0-100)
    decision: ScoringDecision     # Решение системы
    errors: List[str]            # Ошибки
    warnings: List[str]          # Предупреждения
    metadata: Dict[str, Any]     # Дополнительные данные
    processing_time_ms: int      # Время обработки
```

## Интеграция с основным приложением

### Точка интеграции

Модуль интегрируется в точку обработки транзакций в `app/api/v1/endpoints/payment.py` в методе `initiate_two_phase_payment`.

### Пример интеграции

```python
from app.scoring.service import get_scoring_service
from app.scoring.schemas import TransactionDataForScoring

# В методе обработки платежа
scoring_service = get_scoring_service()

transaction_data = TransactionDataForScoring(
    amount=payment_data.amount,
    currency=payment_request.currency,
    payment_reference=payment_request.payment_reference,
    payer_phone=payer_phone,
    payer_bank_code=sender_bank_code,
    # ... другие поля
)

# Оценка рисков
scoring_result = scoring_service.evaluate_transaction(transaction_data)

if scoring_result.decision == ScoringDecision.BLOCK:
    raise HTTPException(status_code=400, detail="Транзакция заблокирована системой скоринга")
elif scoring_result.decision == ScoringDecision.REVIEW:
    # Отправить на ручную проверку
    pass
```

## Настройка правил

### Включение/отключение правил

```python
config = ScoringConfig(
    enabled_rules=["amount_limit", "geolocation", "phone_number", "bank_code", "time_based"]
)
```

### Настройка весов правил

```python
config = ScoringConfig(
    rule_weights={
        "amount_limit": 2.0,    # Высокий приоритет
        "geolocation": 1.5,     # Средний приоритет
        "phone_number": 1.0,    # Стандартный приоритет
        "bank_code": 1.0,
        "time_based": 0.5       # Низкий приоритет
    }
)
```

## Мониторинг и логирование

Модуль использует стандартное логирование Python:

```python
import logging
logger = logging.getLogger("scoring.service")
```

Все операции логируются с соответствующими уровнями:
- INFO - Успешные операции
- WARNING - Предупреждения
- ERROR - Ошибки
- DEBUG - Детальная отладочная информация

## Тестирование

Для тестирования модуля запустите:

```bash
python3 test_scoring.py
```

## Расширение функциональности

### Добавление нового правила

1. Создайте класс, наследующий от `BaseRule`
2. Реализуйте метод `apply()`
3. Добавьте правило в `ScoringService._initialize_rules()`

### Пример нового правила

```python
class CustomRule(BaseRule):
    def __init__(self):
        super().__init__("custom_rule", weight=1.0)
    
    def apply(self, data: TransactionDataForScoring) -> RuleEvaluationResult:
        # Логика правила
        return RuleEvaluationResult(
            rule_name=self.name,
            passed=True,
            score_contribution=0
        )
```

## Безопасность

- Все данные транзакций валидируются
- Ошибки не раскрывают внутреннюю логику
- Поддержка идемпотентности
- Логирование всех операций для аудита

## Производительность

- Время обработки обычно < 10ms
- Кэширование результатов (планируется)
- Асинхронная обработка (планируется)
- Оптимизированные запросы к БД (планируется)