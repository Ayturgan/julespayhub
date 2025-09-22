# QRPayHub Python SDK

[![PyPI version](https://badge.fury.io/py/qrpayhub-sdk.svg)](https://badge.fury.io/py/qrpayhub-sdk)
[![Python Support](https://img.shields.io/pypi/pyversions/qrpayhub-sdk.svg)](https://pypi.org/project/qrpayhub-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Официальный Python SDK для интеграции с QRPayHub API - межбанковской платформой для приёма платежей через QR-коды без комиссий.

## 🚀 Быстрый старт

### Установка

```bash
pip install qrpayhub-sdk
```

### Базовое использование

```python
from qrpayhub_sdk import QRPayHubClient, PaymentStatus

# Инициализация клиента
client = QRPayHubClient(
    base_url="https://api.qrpayhub.com",
    access_token="your-bank-access-token",
    hmac_secret="your-hmac-secret",
    user_agent="MyBank-Backend/1.0.0"
)

# Получение информации о платеже
try:
    payment_info = client.get_payment_info("qr_token_from_scan")
    print(f"Платеж: {payment_info.amount} {payment_info.currency}")
    print(f"Получатель: {payment_info.receiver_name}")
    print(f"Описание: {payment_info.description}")
except Exception as e:
    print(f"Ошибка: {e}")

# Отправка webhook о статусе платежа
try:
    result = client.send_payment_status(
        token="qr_token_from_scan",
        status=PaymentStatus.SUCCESS,
        transaction_id="TXN123456789",
        amount=1500.00,
        payer_phone="+996555123456",
        currency="KGS"
    )
    print(f"Webhook отправлен: {result['message']}")
except Exception as e:
    print(f"Ошибка webhook: {e}")

# Закрытие клиента
client.close()
```

## 📚 Документация

### Инициализация клиента

```python
client = QRPayHubClient(
    base_url="https://api.qrpayhub.com",     # URL API
    access_token="your-access-token",        # Токен доступа банка
    hmac_secret="your-hmac-secret",          # Секрет для HMAC подписи
    user_agent="MyBank-Backend/1.0.0",      # User-Agent приложения
    timeout=30,                              # Таймаут запросов (сек)
    max_retries=3                            # Количество повторов
)
```

### Получение информации о платеже

```python
from qrpayhub_sdk.exceptions import PaymentNotFoundError, AuthenticationError

try:
    payment_info = client.get_payment_info(
        token="qr_token_from_scan",
        device_id="mobile-device-12345",     # Опционально
        app_version="1.0.0"                  # Опционально
    )
    
    # Доступные поля
    print(f"Счет получателя: {payment_info.receiver_account}")
    print(f"Банк получателя: {payment_info.receiver_bank_code}")
    print(f"Имя получателя: {payment_info.receiver_name}")
    print(f"Описание: {payment_info.description}")
    print(f"Сумма: {payment_info.amount}")
    print(f"Валюта: {payment_info.currency}")
    print(f"Референс: {payment_info.payment_reference}")
    
except PaymentNotFoundError as e:
    print(f"Платеж не найден: {e.user_message}")
except AuthenticationError as e:
    print(f"Ошибка аутентификации: {e.user_message}")
```

### Отправка webhook о статусе

```python
from qrpayhub_sdk import PaymentStatus
from qrpayhub_sdk.exceptions import WebhookError, ValidationError

# Успешный платеж
try:
    result = client.send_payment_status(
        token="qr_token_from_scan",
        status=PaymentStatus.SUCCESS,
        transaction_id="TXN123456789",
        amount=2500.00,
        payer_phone="+996555123456",
        currency="KGS",                      # По умолчанию KGS
        timestamp="2024-01-01T12:00:00Z",    # Опционально (автоматически)
        fee_amount=25.00,                    # Опционально
        processing_time_ms=1250              # Опционально
    )
    print(f"Успех: {result['message']}")
    
except WebhookError as e:
    print(f"Ошибка webhook: {e.user_message}")
except ValidationError as e:
    print(f"Ошибка валидации: {e.user_message}")

# Неуспешный платеж
try:
    result = client.send_payment_status(
        token="qr_token_from_scan",
        status=PaymentStatus.FAILED,
        transaction_id="TXN123456790",
        amount=0,                            # Обычно 0 при неуспехе
        payer_phone="+996555123456",
        error_code="INSUFFICIENT_FUNDS",     # Код ошибки
        error_message="Недостаточно средств" # Описание ошибки
    )
    print(f"Неуспешный платеж зафиксирован: {result['message']}")
    
except Exception as e:
    print(f"Ошибка: {e}")
```

### Использование с Context Manager

```python
# Автоматическое закрытие соединения
with QRPayHubClient(
    base_url="https://api.qrpayhub.com",
    access_token="your-access-token",
    hmac_secret="your-hmac-secret"
) as client:
    payment_info = client.get_payment_info("token")
    client.send_payment_status(
        token="token",
        status=PaymentStatus.SUCCESS,
        transaction_id="TXN123",
        amount=1000.00,
        payer_phone="+996555123456"
    )
# Клиент автоматически закрывается
```

## 🔐 Безопасность

### HMAC подпись

SDK автоматически создает HMAC-SHA256 подпись для всех webhook запросов:

```python
# Подпись создается автоматически
signature = hmac_sha256(
    secret=hmac_secret,
    message=f"{method}\n{path}\n{body}\n{timestamp}"
)
```

### Обработка ошибок

```python
from qrpayhub_sdk.exceptions import (
    QRPayHubError,           # Базовое исключение
    AuthenticationError,     # 401, 403 ошибки
    ValidationError,         # 400 ошибки валидации
    PaymentNotFoundError,    # 404 платеж не найден
    RateLimitError,          # 429 превышен лимит
    WebhookError,            # Ошибки webhook
    NetworkError,            # Сетевые ошибки
    TimeoutError             # Таймауты
)

try:
    payment_info = client.get_payment_info("token")
except PaymentNotFoundError:
    # Платеж не найден - показать ошибку пользователю
    pass
except AuthenticationError:
    # Проблема с токеном - проверить настройки
    pass
except RateLimitError as e:
    # Превышен лимит - подождать retry_after секунд
    time.sleep(e.retry_after or 60)
except QRPayHubError as e:
    # Общая ошибка API
    print(f"API Error [{e.error_code}]: {e.user_message}")
```

## 🧪 Тестирование

### Sandbox окружение

```python
# Для тестирования используйте sandbox
client = QRPayHubClient(
    base_url="https://sandbox.qrpayhub.com",
    access_token="test_bank_token_12345",
    hmac_secret="test_hmac_secret_67890"
)

# Тестовые токены
test_tokens = [
    "test_token_success_1000",    # Успешный платеж 1000 KGS
    "test_token_failed_invalid",  # Неуспешный платеж
    "test_token_expired_old"      # Истекший токен
]
```

### Unit тесты

```python
import unittest
from unittest.mock import patch, MagicMock
from qrpayhub_sdk import QRPayHubClient, PaymentStatus

class TestQRPayHubClient(unittest.TestCase):
    def setUp(self):
        self.client = QRPayHubClient(
            base_url="https://api.qrpayhub.com",
            access_token="test-token",
            hmac_secret="test-secret"
        )
    
    @patch('requests.Session.get')
    def test_get_payment_info_success(self, mock_get):
        # Мокаем успешный ответ
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "receiver_account": "1234567890",
            "receiver_bank_code": "TEST",
            "receiver_name": "Test User",
            "description": "Test payment",
            "amount": 1000.0,
            "currency": "KGS",
            "payment_reference": "REF123"
        }
        mock_get.return_value = mock_response
        
        # Тестируем
        payment_info = self.client.get_payment_info("test-token")
        
        self.assertEqual(payment_info.amount, 1000.0)
        self.assertEqual(payment_info.currency, "KGS")
    
    def tearDown(self):
        self.client.close()

if __name__ == '__main__':
    unittest.main()
```

## 📊 Мониторинг и логирование

### Логирование

```python
import logging

# Включить логирование SDK
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('qrpayhub_sdk')

# Клиент будет логировать запросы
client = QRPayHubClient(
    base_url="https://api.qrpayhub.com",
    access_token="your-access-token",
    hmac_secret="your-hmac-secret"
)
```

### Метрики

```python
import time

# Измерение времени выполнения
start_time = time.time()

try:
    payment_info = client.get_payment_info("token")
    duration = time.time() - start_time
    
    # Отправка метрик в вашу систему мониторинга
    send_metric("qrpayhub.get_payment_info.success", duration)
    send_metric("qrpayhub.get_payment_info.count", 1)
    
except Exception as e:
    duration = time.time() - start_time
    send_metric("qrpayhub.get_payment_info.error", duration)
    send_metric("qrpayhub.get_payment_info.error_count", 1)
```

## 🔄 Асинхронная обработка

### Threading

```python
import threading
import queue
import time

class WebhookProcessor:
    def __init__(self, client):
        self.client = client
        self.webhook_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_webhooks)
        self.worker_thread.daemon = True
        self.worker_thread.start()
    
    def send_webhook_async(self, webhook_data):
        """Добавить webhook в очередь для асинхронной отправки"""
        self.webhook_queue.put(webhook_data)
    
    def _process_webhooks(self):
        """Обработчик webhook в отдельном потоке"""
        while True:
            try:
                webhook_data = self.webhook_queue.get(timeout=1)
                
                # Отправляем webhook
                result = self.client.send_payment_status(**webhook_data)
                print(f"Webhook sent: {result['message']}")
                
                self.webhook_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Webhook error: {e}")
                # Можно добавить retry логику

# Использование
processor = WebhookProcessor(client)

# Асинхронная отправка
processor.send_webhook_async({
    'token': 'token',
    'status': PaymentStatus.SUCCESS,
    'transaction_id': 'TXN123',
    'amount': 1000.00,
    'payer_phone': '+996555123456'
})
```

## 🛠️ Разработка

### Установка для разработки

```bash
git clone https://github.com/qrpayhub/python-sdk.git
cd python-sdk
pip install -e .[dev]
```

### Запуск тестов

```bash
# Все тесты
pytest

# С покрытием
pytest --cov=qrpayhub_sdk

# Конкретный тест
pytest tests/test_client.py::TestQRPayHubClient::test_get_payment_info
```

### Форматирование кода

```bash
# Форматирование
black qrpayhub_sdk/
isort qrpayhub_sdk/

# Проверка стиля
flake8 qrpayhub_sdk/
mypy qrpayhub_sdk/
```

## 📄 Лицензия

MIT License. См. [LICENSE](LICENSE) для деталей.

## 🤝 Поддержка

- **Email**: integration@qrpayhub.com
- **Документация**: https://docs.qrpayhub.com
- **GitHub Issues**: https://github.com/qrpayhub/python-sdk/issues
- **Telegram**: @qrpayhub_support

## 📝 Changelog

### v1.0.0 (2024-01-01)
- ✨ Первый релиз SDK
- ✅ Поддержка payment-info API
- ✅ Поддержка payment-status webhook
- ✅ HMAC подпись запросов
- ✅ Обработка всех типов ошибок
- ✅ Context manager поддержка
- ✅ Retry логика
- ✅ Comprehensive тестирование
