# Payment Info API

## Описание

Эндпоинт для получения информации о платеже по токену QR-кода. Используется банками для отображения деталей платежа пользователю.

## Endpoint

```
GET /api/v1/payment/payment-info
```

## Аутентификация

- **Bearer Token**: Обязательный заголовок `Authorization: Bearer {access_token}`
- **IP Whitelist**: Запрос должен идти с разрешенного IP-адреса
- **User-Agent**: Должен соответствовать настроенному паттерну

## Параметры запроса

### Query Parameters

| Параметр | Тип | Обязательный | Описание |
|----------|-----|-------------|----------|
| `token` | string | Да | Токен из QR-кода |

### Headers

| Заголовок | Тип | Обязательный | Описание |
|-----------|-----|-------------|----------|
| `Authorization` | string | Да | `Bearer {access_token}` |
| `User-Agent` | string | Да | Идентификатор приложения банка |
| `X-Device-ID` | string | Нет | Уникальный ID устройства |
| `X-App-Version` | string | Нет | Версия приложения (формат: x.y.z) |

## Пример запроса

```bash
curl -X GET "https://api.qrpayhub.com/api/v1/payment/payment-info?token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..." \
  -H "Authorization: Bearer bank_access_token_12345" \
  -H "User-Agent: MyBank-Mobile/2.1.0" \
  -H "X-Device-ID: device-uuid-12345" \
  -H "X-App-Version: 2.1.0"
```

## Ответы

### Успешный ответ (200 OK)

```json
{
  "receiver_account": "1234567890123456",
  "receiver_bank_code": "CBKG", 
  "receiver_name": "ИП Иванов Иван Иванович",
  "description": "Оплата за товар в магазине 'Электроника'",
  "amount": 2500.00,
  "currency": "KGS",
  "payment_reference": "QRPAY240101001234"
}
```

#### Поля ответа

| Поле | Тип | Описание |
|------|-----|----------|
| `receiver_account` | string | Номер счета получателя |
| `receiver_bank_code` | string | Код банка получателя |
| `receiver_name` | string | ФИО/Название получателя |
| `description` | string | Описание платежа |
| `amount` | number | Сумма платежа |
| `currency` | string | Код валюты (ISO 4217) |
| `payment_reference` | string | Уникальный номер платежа |

### Ошибки

#### 400 Bad Request - Неверный токен

```json
{
  "error": {
    "code": "BIZ_003_EXPIRED_TOKEN",
    "message": "Token has expired",
    "user_message": "Токен истек",
    "details": {
      "expired_at": "2024-01-01T12:00:00Z",
      "current_time": "2024-01-01T12:15:00Z"
    },
    "severity": "MEDIUM",
    "suggestions": [
      "Получите новый QR-код",
      "Проверьте время создания платежа"
    ],
    "request_id": "req_12345678",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 401 Unauthorized - Ошибка аутентификации

```json
{
  "error": {
    "code": "AUTH_002_MISSING_TOKEN", 
    "message": "Missing or invalid Authorization header",
    "user_message": "Неверный токен авторизации",
    "severity": "HIGH",
    "suggestions": [
      "Проверьте правильность Bearer токена",
      "Убедитесь что токен не истек"
    ],
    "request_id": "req_12345679",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 403 Forbidden - IP не разрешен

```json
{
  "error": {
    "code": "AUTH_004_IP_NOT_ALLOWED",
    "message": "IP address not allowed",
    "user_message": "Доступ запрещен с данного IP",
    "details": {
      "client_ip": "192.168.1.100",
      "allowed_ranges": ["10.0.0.0/8", "192.168.0.0/16"]
    },
    "severity": "HIGH",
    "suggestions": [
      "Проверьте настройки IP whitelist",
      "Обратитесь к администратору"
    ],
    "request_id": "req_12345680",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 404 Not Found - Платеж не найден

```json
{
  "error": {
    "code": "BIZ_001_PAYMENT_NOT_FOUND",
    "message": "Payment request not found",
    "user_message": "Платежный запрос не найден", 
    "details": {
      "token_uuid": "12345678-1234-1234-1234-123456789012"
    },
    "severity": "MEDIUM",
    "suggestions": [
      "Проверьте правильность токена",
      "Убедитесь что платежный запрос не истек",
      "Обратитесь к получателю за новым QR-кодом"
    ],
    "request_id": "req_12345681",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 409 Conflict - Платеж уже обработан

```json
{
  "error": {
    "code": "BIZ_002_PAYMENT_ALREADY_PROCESSED",
    "message": "Payment has already been processed",
    "user_message": "Платеж уже был обработан",
    "details": {
      "processed_at": "2024-01-01T11:30:00Z",
      "transaction_id": "TXN240101123456"
    },
    "severity": "MEDIUM",
    "suggestions": [
      "Этот QR-код уже использован",
      "Получите новый QR-код для нового платежа"
    ],
    "request_id": "req_12345682", 
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

#### 429 Too Many Requests - Превышен лимит

```json
{
  "error": {
    "code": "RATE_001_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "user_message": "Превышен лимит запросов",
    "details": {
      "limit": 30,
      "window": "60s",
      "retry_after": 45
    },
    "severity": "LOW",
    "suggestions": [
      "Подождите перед следующим запросом",
      "Уменьшите частоту запросов"
    ],
    "request_id": "req_12345683",
    "timestamp": "2024-01-01T12:15:00Z"
  }
}
```

## Коды ошибок

| Код | HTTP Status | Описание |
|-----|-------------|----------|
| `AUTH_001_INVALID_TOKEN` | 401 | Неверный токен доступа |
| `AUTH_002_MISSING_TOKEN` | 401 | Отсутствует токен авторизации |
| `AUTH_004_IP_NOT_ALLOWED` | 403 | IP-адрес не разрешен |
| `AUTH_005_BANK_INACTIVE` | 403 | Банк неактивен |
| `VAL_006_INVALID_USER_AGENT` | 400 | Неверный User-Agent |
| `VAL_007_MISSING_REQUIRED_HEADER` | 400 | Отсутствует обязательный заголовок |
| `BIZ_001_PAYMENT_NOT_FOUND` | 404 | Платеж не найден |
| `BIZ_002_PAYMENT_ALREADY_PROCESSED` | 409 | Платеж уже обработан |
| `BIZ_003_EXPIRED_TOKEN` | 400 | Токен истек |
| `RATE_001_LIMIT_EXCEEDED` | 429 | Превышен лимит запросов |

## Примеры интеграции

### Python

```python
import requests
from typing import Dict, Any

class QRPayHubClient:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url
        self.access_token = access_token
    
    def get_payment_info(self, token: str) -> Dict[str, Any]:
        """Получение информации о платеже"""
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'User-Agent': 'MyBank-Mobile/2.1.0',
            'X-Device-ID': 'device-12345'
        }
        
        response = requests.get(
            f'{self.base_url}/api/v1/payment/payment-info',
            params={'token': token},
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            error_data = response.json()
            raise Exception(f"API Error: {error_data['error']['message']}")

# Использование
client = QRPayHubClient(
    base_url='https://api.qrpayhub.com',
    access_token='your_access_token'
)

try:
    payment_info = client.get_payment_info('qr_token_from_scan')
    print(f"Платеж на сумму: {payment_info['amount']} {payment_info['currency']}")
    print(f"Получатель: {payment_info['receiver_name']}")
    print(f"Описание: {payment_info['description']}")
except Exception as e:
    print(f"Ошибка: {e}")
```

### Java

```java
import okhttp3.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.Map;

public class QRPayHubClient {
    private final String baseUrl;
    private final String accessToken;
    private final OkHttpClient client;
    private final ObjectMapper mapper;
    
    public QRPayHubClient(String baseUrl, String accessToken) {
        this.baseUrl = baseUrl;
        this.accessToken = accessToken;
        this.client = new OkHttpClient();
        this.mapper = new ObjectMapper();
    }
    
    public Map<String, Object> getPaymentInfo(String token) throws IOException {
        HttpUrl url = HttpUrl.parse(baseUrl + "/api/v1/payment/payment-info")
            .newBuilder()
            .addQueryParameter("token", token)
            .build();
            
        Request request = new Request.Builder()
            .url(url)
            .addHeader("Authorization", "Bearer " + accessToken)
            .addHeader("User-Agent", "MyBank-Android/2.1.0")
            .addHeader("X-Device-ID", "android-device-12345")
            .build();
            
        try (Response response = client.newCall(request).execute()) {
            String responseBody = response.body().string();
            
            if (response.isSuccessful()) {
                return mapper.readValue(responseBody, Map.class);
            } else {
                Map<String, Object> errorData = mapper.readValue(responseBody, Map.class);
                Map<String, Object> error = (Map<String, Object>) errorData.get("error");
                throw new RuntimeException("API Error: " + error.get("message"));
            }
        }
    }
}

// Использование
QRPayHubClient client = new QRPayHubClient(
    "https://api.qrpayhub.com",
    "your_access_token"
);

try {
    Map<String, Object> paymentInfo = client.getPaymentInfo("qr_token_from_scan");
    System.out.println("Сумма: " + paymentInfo.get("amount") + " " + paymentInfo.get("currency"));
    System.out.println("Получатель: " + paymentInfo.get("receiver_name"));
} catch (Exception e) {
    System.err.println("Ошибка: " + e.getMessage());
}
```

## Рекомендации

### Обработка ошибок

1. **Всегда проверяйте HTTP статус** перед парсингом ответа
2. **Используйте retry логику** для временных ошибок (5xx, 429)
3. **Показывайте пользователю понятные сообщения** из поля `user_message`
4. **Логируйте request_id** для отладки

### Производительность

1. **Используйте connection pooling** для HTTP клиента
2. **Устанавливайте разумные таймауты** (10-30 секунд)
3. **Кешируйте результаты** если это безопасно
4. **Мониторьте response time** и успешность запросов

### Безопасность

1. **Никогда не логируйте токены** в открытом виде
2. **Используйте HTTPS** для всех запросов
3. **Валидируйте сертификаты** сервера
4. **Храните access_token безопасно** (encrypted storage)

---

**Поддержка**: integration@qrpayhub.com | **Документация**: https://docs.qrpayhub.com
