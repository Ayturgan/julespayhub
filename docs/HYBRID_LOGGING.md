# Гибридная система логирования QRPayHub

## Обзор

QRPayHub использует гибридную систему логирования, которая сочетает в себе:
- **База данных** - для критических событий (платежи, админские действия, аудит)
- **Файлы** - для высокообъемных логов (API запросы, ошибки, мониторинг)

## Архитектура

### Компоненты

1. **HybridLoggingService** (`app/services/hybrid_logging_service.py`)
   - Основной сервис логирования
   - Асинхронная очередь для обработки событий
   - Автоматическое определение назначения логирования

2. **LoggingMiddleware** (`app/core/middleware.py`)
   - Автоматическое логирование всех API запросов
   - Интеграция с системой мониторинга
   - Санитизация чувствительных данных

3. **Структуры данных**
   - `LogEvent` - основная структура события
   - `LogLevel` - уровни логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - `LogDestination` - назначения (DATABASE, FILE, BOTH)

## Типы событий и их назначения

### В базу данных (критические события)

- ✅ **Успешные платежи** - `BillingRecord`
- ✅ **Админские действия** - `AuditLog`
- ✅ **Ключевые события жизненного цикла** - `TimelineEvent`
- ✅ **Критические ошибки** - `AuditLog`

### В файлы (высокообъемные логи)

- 📄 **Все API запросы** - `logs/qrpayhub_api.jsonl`
- 📄 **Ошибки** - `logs/qrpayhub_errors.jsonl`
- 📄 **Общие логи** - `logs/qrpayhub_all.jsonl`
- 📄 **Безопасность** - `logs/qrpayhub_security.jsonl`

## Использование

### Базовое логирование

```python
from app.services.hybrid_logging_service import hybrid_logging_service, LogEvent, LogLevel, LogDestination

# Критическое событие (в БД и файлы)
event = LogEvent(
    timestamp=datetime.utcnow(),
    level=LogLevel.CRITICAL,
    destination=LogDestination.BOTH,
    event_type="payment_success",
    event_source="payment_api",
    actor_type="bank",
    actor_id="MBANK",
    status="success",
    payment_token="token_123",
    amount=1000.0,
    currency="KGS"
)

hybrid_logging_service.log_event(event, db)
```

### Специальные методы

```python
# API запрос (только в файлы)
hybrid_logging_service.log_api_request(
    request_type="payment",
    endpoint="/api/v1/payment",
    method="POST",
    status_code=200,
    duration_ms=150,
    ip_address="127.0.0.1",
    bank_code="MBANK"
)

# Админское действие (в БД и файлы)
hybrid_logging_service.log_admin_action(
    db=db,
    action="create_user",
    target="user_123",
    details={"role": "admin"},
    actor_id="admin_user"
)

# Успешный платеж (в БД и файлы)
hybrid_logging_service.log_payment_success(
    payment_token="token_123",
    transaction_id="txn_456",
    bank_code="MBANK",
    amount=1000.0,
    currency="KGS",
    db=db
)
```

## Файловая структура логов

```
logs/
├── qrpayhub_all.jsonl          # Все логи
├── qrpayhub_api.jsonl          # API запросы
├── qrpayhub_errors.jsonl       # Ошибки
├── qrpayhub_security.jsonl     # События безопасности
├── qrpayhub_payments.jsonl     # Платежные события
├── qrpayhub_qr.jsonl          # QR-код события
└── archive/                    # Архивные файлы
    ├── qrpayhub_all.jsonl.2025-08-20.gz
    └── ...
```

## Формат логов

### JSON Lines формат

Каждая строка - валидный JSON объект:

```json
{
  "timestamp": "2025-08-26T10:15:03.533462Z",
  "level": "INFO",
  "event_type": "api_request",
  "event_source": "payment_api",
  "actor_type": "bank",
  "actor_id": "MBANK",
  "ip_address": "127.0.0.1",
  "status": "success",
  "duration_ms": 150,
  "payment_token": "token_123",
  "bank_code": "MBANK",
  "details": {
    "endpoint": "/api/v1/payment",
    "method": "POST",
    "status_code": 200
  }
}
```

## Мониторинг и анализ

### Анализ логов

```bash
# Подсчет API запросов за последний час
grep "$(date -d '1 hour ago' -u +%Y-%m-%dT%H)" logs/qrpayhub_api.jsonl | wc -l

# Поиск ошибок
grep '"level":"ERROR"' logs/qrpayhub_errors.jsonl

# Анализ по банкам
jq '.bank_code' logs/qrpayhub_api.jsonl | sort | uniq -c

# Среднее время ответа
jq '.duration_ms' logs/qrpayhub_api.jsonl | awk '{sum+=$1; count++} END {print sum/count}'
```

### Интеграция с мониторингом

Система автоматически интегрируется с `realtime_monitoring_service` для:
- Сбора метрик производительности
- Отслеживания ошибок
- Мониторинга банков
- Генерации алертов

## Конфигурация

### Настройки логирования

```python
# app/core/logging_config.py
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(timestamp)s %(level)s %(logger)s %(message)s"
        }
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/qrpayhub_all.jsonl",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "formatter": "json"
        }
    }
}
```

### Ротация логов

Логи автоматически ротируются:
- **Ежедневно** - создание новых файлов
- **После 7 дней** - сжатие в .gz
- **После 30 дней** - удаление старых файлов

## Миграция с старой системы

### Что изменилось

1. **API логи** - больше не хранятся в БД, только в файлах
2. **PaymentLog** - заменен на гибридную систему
3. **AuditLog** - используется для критических событий
4. **TimelineEvent** - для ключевых событий жизненного цикла

### Совместимость

- ✅ Старые эндпоинты аудита работают
- ✅ Админские действия логируются как раньше
- ✅ Критические события сохраняются в БД
- ⚠️ API логи теперь доступны только через файлы

## Производительность

### Преимущества

- **Скорость** - асинхронная обработка не блокирует API
- **Масштабируемость** - файлы не ограничены размером БД
- **Гибкость** - разные стратегии для разных типов событий
- **Надежность** - критичные события дублируются

### Метрики

- **API запросы**: ~1000 записей/сек в файлы
- **Критические события**: ~100 записей/сек в БД
- **Задержка**: <1ms для файлов, <10ms для БД

## Устранение неполадок

### Частые проблемы

1. **Логи не записываются**
   - Проверьте права доступа к папке `logs/`
   - Убедитесь, что очередь не переполнена

2. **Медленная работа**
   - Проверьте размер лог-файлов
   - Включите ротацию логов

3. **Ошибки БД**
   - Проверьте подключение к БД
   - Убедитесь, что таблицы созданы

### Отладка

```python
# Включение отладочного логирования
import logging
logging.getLogger('app.services.hybrid_logging_service').setLevel(logging.DEBUG)
```

## Заключение

Гибридная система логирования обеспечивает оптимальный баланс между производительностью и функциональностью, сохраняя критичные события в БД для быстрого доступа и записывая высокообъемные логи в файлы для эффективного хранения и анализа.
