# Payment Status Webhook API

## Описание

Эндпоинт для отправки уведомлений о статусе обработки платежа. Банки используют этот webhook для информирования QRPayHub о результате платежной операции.

## Endpoint

```
POST /api/v1/payment/payment-status
```

## Аутентификация

- **Bearer Token**: Обязательный заголовок `Authorization: Bearer {access_token}`
- **HMAC Signature**: Подпись запроса в заголовке `X-Signature`
- **Timestamp**: Временная метка в заголовке `X-Timestamp`
- **IP Whitelist**: Запрос должен идти с разрешенного IP-адреса

## Параметры запроса

### Headers

| Заголовок | Тип | Обязательный | Описание |
|-----------|-----|-------------|----------|
| `Authorization` | string | Да | `Bearer {access_token}` |
| `Content-Type` | string | Да | `application/json` |
| `X-Signature` | string | Да | HMAC-SHA256 подпись запроса |
| `X-Timestamp` | string | Да | Unix timestamp (секунды) |
| `User-Agent` | string | Да | Идентификатор системы банка |
| `X-Transaction-ID` | string | Нет | ID транзакции для идемпотентности |

### Body (JSON)

| Поле | Тип | Обязательный | Описание |
|------|-----|-------------|----------|
| `token` | string | Да | Токен из QR-кода |
| `status` | string | Да | Статус платежа: `success`, `failed`, `pending`, `cancelled` |
| `transaction_id` | string | Да | Уникальный ID транзакции в системе банка |
| `amount` | number | Да | Фактическая сумма платежа |
| `currency` | string | Да | Код валюты (ISO 4217) |
| `payer_phone` | string | Да | Номер телефона плательщика |
| `timestamp` | string | Да | Время обработки платежа (ISO 8601) |
| `error_code` | string | Нет | Код ошибки (если status = failed) |
| `error_message` | string | Нет | Описание ошибки (если status = failed) |
| `fee_amount` | number | Нет | Размер комиссии банка |
| `processing_time_ms` | number | Нет | Время обработки в миллисекундах |

## HMAC Подпись

### Создание подписи

```python
import hmac
import hashlib
import time
import json

def create_webhook_signature(secret: str, method: str, path: str, body: str, timestamp: str) -> str:
    """Создание HMAC подписи для webhook"""
    # Формируем строку для подписи
    message = f"{method}\n{path}\n{body}\n{timestamp}"
    
    # Вычисляем HMAC-SHA256
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return f"sha256={signature}"

# Пример использования
webhook_data = {
    "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "status": "success",
    "transaction_id": "TXN240101123456",
    "amount": 2500.00,
    "currency": "KGS",
    "payer_phone": "+996555123456",
    "timestamp": "2024-01-01T12:00:00Z"
}

body = json.dumps(webhook_data, separators=(',', ':'))
timestamp = str(int(time.time()))

signature = create_webhook_signature(
    secret="your-hmac-secret",
    method="POST", 
    path="/api/v1/payment/payment-status",
    body=body,
    timestamp=timestamp
)

headers = {
    "Authorization": "Bearer your-access-token",
    "Content-Type": "application/json",
    "X-Signature": signature,
    "X-Timestamp": timestamp,
    "User-Agent": "MyBank-Backend/1.0.0"
}
```

### Алгоритм проверки подписи

1. Извлечь timestamp из заголовка `X-Timestamp`
2. Проверить что timestamp не старше 5 минут
3. Сформировать строку: `{METHOD}\n{PATH}\n{BODY}\n{TIMESTAMP}`
4. Вычислить HMAC-SHA256 с секретным ключом
5. Сравнить с подписью из заголовка `X-Signature`

## Пример запроса

```bash
curl -X POST "https://api.qrpayhub.com/api/v1/payment/payment-status" \
  -H "Authorization: Bearer bank_access_token_12345" \
  -H "Content-Type: application/json" \
  -H "X-Signature: sha256=a8b7c9d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" \
  -H "X-Timestamp: 1640995200" \
  -H "User-Agent: MyBank-Backend/1.0.0" \
  -H "X-Transaction-ID: TXN240101123456" \
  -d '{
    "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "status": "success",
    "transaction_id": "TXN240101123456", 
    "amount": 2500.00,
    "currency": "KGS",
    "payer_phone": "+996555123456",
    "timestamp": "2024-01-01T12:00:00Z",
    "fee_amount": 25.00,
    "processing_time_ms": 1250
  }'
```

## Ответы

### Успешный ответ (200 OK)

```json
{
  "status": "success",
  "message": "Payment status updated successfully",
  "transaction_id": "TXN240101123456",
  "processed_at": "2024-01-01T12:00:01Z",
  "idempotency_key": "TXN240101123456_MYBANK"
}
```

### Ошибки

#### 400 Bad Request - Неверные данные

```json
{
  "error": {
    "code": "VAL_001_INVALID_INPUT",
    "message": "Invalid payment status value",
    "user_message": "Неверное значение статуса платежа",
    "details": {
      "field": "status",
      "value": "invalid_status",
      "allowed_values": ["success", "failed", "pending", "cancelled"]
    },
    "severity": "MEDIUM",
    "suggestions": [
      "Используйте один из разрешенных статусов",
      "Проверьте документацию API"
    ],
    "request_id": "req_12345684",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 401 Unauthorized - Неверная подпись

```json
{
  "error": {
    "code": "WH_002_WEBHOOK_SIGNATURE_INVALID",
    "message": "Invalid HMAC signature",
    "user_message": "Неверная подпись запроса",
    "details": {
      "signature_header": "X-Signature",
      "timestamp_header": "X-Timestamp",
      "signature_algorithm": "HMAC-SHA256"
    },
    "severity": "HIGH",
    "suggestions": [
      "Проверьте алгоритм создания подписи",
      "Убедитесь в правильности HMAC секрета",
      "Проверьте формат временной метки"
    ],
    "request_id": "req_12345685",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 400 Bad Request - Устаревшая временная метка

```json
{
  "error": {
    "code": "WH_003_WEBHOOK_TIMESTAMP_TOO_OLD", 
    "message": "Webhook timestamp is too old",
    "user_message": "Временная метка запроса устарела",
    "details": {
      "timestamp": "1640991600",
      "max_age_seconds": 300,
      "current_time": "1640995200"
    },
    "severity": "MEDIUM",
    "suggestions": [
      "Синхронизируйте время на серверах",
      "Отправляйте webhook сразу после обработки",
      "Проверьте сетевые задержки"
    ],
    "request_id": "req_12345686",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 409 Conflict - Транзакция уже обработана

```json
{
  "error": {
    "code": "BIZ_005_DUPLICATE_TRANSACTION",
    "message": "Transaction already processed",
    "user_message": "Транзакция уже была обработана",
    "details": {
      "transaction_id": "TXN240101123456",
      "previous_status": "success",
      "processed_at": "2024-01-01T11:30:00Z"
    },
    "severity": "LOW",
    "suggestions": [
      "Проверьте идемпотентность запросов",
      "Используйте уникальные transaction_id"
    ],
    "request_id": "req_12345687",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

## Статусы платежей

| Статус | Описание | Финальный |
|--------|----------|-----------|
| `success` | Платеж успешно выполнен | ✅ Да |
| `failed` | Платеж отклонен/неуспешен | ✅ Да |
| `pending` | Платеж в обработке | ❌ Нет |
| `cancelled` | Платеж отменен | ✅ Да |

### Обязательные поля для статусов

#### success
- Все основные поля обязательны
- `payer_phone` должен быть заполнен
- `amount` должен быть > 0

#### failed  
- `error_code` - рекомендуется
- `error_message` - рекомендуется
- `amount` может быть 0

#### pending
- Промежуточный статус
- Должен быть заменен на `success` или `failed`

#### cancelled
- `error_message` - причина отмены
- `amount` обычно 0

## Коды ошибок

| Код | HTTP Status | Описание |
|-----|-------------|----------|
| `AUTH_001_INVALID_TOKEN` | 401 | Неверный токен доступа |
| `AUTH_003_INVALID_SIGNATURE` | 401 | Неверная HMAC подпись |
| `AUTH_004_IP_NOT_ALLOWED` | 403 | IP-адрес не разрешен |
| `VAL_001_INVALID_INPUT` | 400 | Неверные входные данные |
| `VAL_002_MISSING_REQUIRED_FIELD` | 400 | Отсутствует обязательное поле |
| `BIZ_001_PAYMENT_NOT_FOUND` | 404 | Платеж не найден |
| `BIZ_005_DUPLICATE_TRANSACTION` | 409 | Дублирующая транзакция |
| `WH_001_INVALID_WEBHOOK_PAYLOAD` | 400 | Неверный payload webhook |
| `WH_002_WEBHOOK_SIGNATURE_INVALID` | 401 | Неверная подпись webhook |
| `WH_003_WEBHOOK_TIMESTAMP_TOO_OLD` | 400 | Устаревшая временная метка |
| `RATE_001_LIMIT_EXCEEDED` | 429 | Превышен лимит запросов |

## Примеры интеграции

### Python

```python
import requests
import hmac
import hashlib
import json
import time
from typing import Dict, Any

class QRPayHubWebhook:
    def __init__(self, base_url: str, access_token: str, hmac_secret: str):
        self.base_url = base_url
        self.access_token = access_token
        self.hmac_secret = hmac_secret
    
    def create_signature(self, method: str, path: str, body: str, timestamp: str) -> str:
        """Создание HMAC подписи"""
        message = f"{method}\n{path}\n{body}\n{timestamp}"
        signature = hmac.new(
            self.hmac_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    def send_payment_status(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Отправка статуса платежа"""
        path = "/api/v1/payment/payment-status"
        body = json.dumps(payment_data, separators=(',', ':'))
        timestamp = str(int(time.time()))
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'X-Signature': self.create_signature('POST', path, body, timestamp),
            'X-Timestamp': timestamp,
            'User-Agent': 'MyBank-Backend/1.0.0',
            'X-Transaction-ID': payment_data['transaction_id']
        }
        
        response = requests.post(
            f'{self.base_url}{path}',
            data=body,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            error_data = response.json()
            raise Exception(f"Webhook Error: {error_data['error']['message']}")

# Использование
webhook_client = QRPayHubWebhook(
    base_url='https://api.qrpayhub.com',
    access_token='your_access_token',
    hmac_secret='your_hmac_secret'
)

# Успешный платеж
success_data = {
    "token": "payment_token_from_qr",
    "status": "success",
    "transaction_id": "TXN240101123456",
    "amount": 2500.00,
    "currency": "KGS", 
    "payer_phone": "+996555123456",
    "timestamp": "2024-01-01T12:00:00Z",
    "fee_amount": 25.00,
    "processing_time_ms": 1250
}

try:
    result = webhook_client.send_payment_status(success_data)
    print(f"Webhook sent successfully: {result['message']}")
except Exception as e:
    print(f"Webhook failed: {e}")

# Неуспешный платеж
failed_data = {
    "token": "payment_token_from_qr",
    "status": "failed", 
    "transaction_id": "TXN240101123457",
    "amount": 0,
    "currency": "KGS",
    "payer_phone": "+996555123456",
    "timestamp": "2024-01-01T12:01:00Z",
    "error_code": "INSUFFICIENT_FUNDS",
    "error_message": "Недостаточно средств на счете"
}

try:
    result = webhook_client.send_payment_status(failed_data)
    print(f"Failed payment webhook sent: {result['message']}")
except Exception as e:
    print(f"Webhook failed: {e}")
```

### Java

```java
import okhttp3.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Map;

public class QRPayHubWebhook {
    private final String baseUrl;
    private final String accessToken;
    private final String hmacSecret;
    private final OkHttpClient client;
    private final ObjectMapper mapper;
    
    public QRPayHubWebhook(String baseUrl, String accessToken, String hmacSecret) {
        this.baseUrl = baseUrl;
        this.accessToken = accessToken;
        this.hmacSecret = hmacSecret;
        this.client = new OkHttpClient();
        this.mapper = new ObjectMapper();
    }
    
    private String createSignature(String method, String path, String body, String timestamp) 
            throws NoSuchAlgorithmException, InvalidKeyException {
        String message = method + "\n" + path + "\n" + body + "\n" + timestamp;
        
        Mac mac = Mac.getInstance("HmacSHA256");
        SecretKeySpec secretKeySpec = new SecretKeySpec(
            hmacSecret.getBytes(StandardCharsets.UTF_8), 
            "HmacSHA256"
        );
        mac.init(secretKeySpec);
        
        byte[] hash = mac.doFinal(message.getBytes(StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder();
        for (byte b : hash) {
            result.append(String.format("%02x", b));
        }
        
        return "sha256=" + result.toString();
    }
    
    public Map<String, Object> sendPaymentStatus(Map<String, Object> paymentData) 
            throws Exception {
        String path = "/api/v1/payment/payment-status";
        String body = mapper.writeValueAsString(paymentData);
        String timestamp = String.valueOf(Instant.now().getEpochSecond());
        
        RequestBody requestBody = RequestBody.create(
            body, 
            MediaType.parse("application/json")
        );
        
        Request request = new Request.Builder()
            .url(baseUrl + path)
            .post(requestBody)
            .addHeader("Authorization", "Bearer " + accessToken)
            .addHeader("Content-Type", "application/json")
            .addHeader("X-Signature", createSignature("POST", path, body, timestamp))
            .addHeader("X-Timestamp", timestamp)
            .addHeader("User-Agent", "MyBank-Backend/1.0.0")
            .addHeader("X-Transaction-ID", (String) paymentData.get("transaction_id"))
            .build();
            
        try (Response response = client.newCall(request).execute()) {
            String responseBody = response.body().string();
            
            if (response.isSuccessful()) {
                return mapper.readValue(responseBody, Map.class);
            } else {
                Map<String, Object> errorData = mapper.readValue(responseBody, Map.class);
                Map<String, Object> error = (Map<String, Object>) errorData.get("error");
                throw new RuntimeException("Webhook Error: " + error.get("message"));
            }
        }
    }
}
```

## Рекомендации

### Идемпотентность

1. **Используйте уникальные transaction_id** для каждой операции
2. **Повторяйте webhook при временных ошибках** (5xx, timeout)
3. **Не повторяйте при бизнес-ошибках** (4xx кроме 429)

### Безопасность

1. **Всегда используйте HMAC подпись** для webhook
2. **Проверяйте timestamp** на актуальность
3. **Используйте HTTPS** для всех запросов
4. **Не логируйте sensitive данные** (токены, подписи)

### Производительность

1. **Отправляйте webhook асинхронно** после обработки платежа
2. **Используйте таймауты** 30-60 секунд
3. **Реализуйте retry логику** с exponential backoff
4. **Мониторьте успешность доставки** webhook

### Мониторинг

1. **Логируйте все webhook запросы** с результатами
2. **Отслеживайте время доставки** webhook
3. **Настройте алерты** на неуспешные webhook
4. **Ведите статистику** по статусам платежей

---

**Поддержка**: integration@qrpayhub.com | **Документация**: https://docs.qrpayhub.com
