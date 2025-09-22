# QRPayHub - Bank Integration SDK

🏦 **Межбанковская платформа для приёма платежей через QR-коды без комиссий**

## 📋 Оглавление

- [Быстрый старт](#быстрый-старт)
- [Архитектура системы](#архитектура-системы)
- [API Документация](#api-документация)
- [SDK и примеры](#sdk-и-примеры)
- [Безопасность](#безопасность)
- [Тестирование](#тестирование)
- [Поддержка](#поддержка)

## 🚀 Быстрый старт

### 1. Регистрация банка

```bash
# Создание банка в системе
curl -X POST "https://api.qrpayhub.com/api/v1/admin/banks" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "MYBANK",
    "name": "My Bank Ltd",
    "access_token": "your-secure-access-token",
    "hmac_secret": "your-hmac-secret-key",
    "allowed_ips": ["192.168.1.0/24", "10.0.0.0/8"],
    "webhook_url": "https://mybank.com/qrpayhub/webhook"
  }'
```

### 2. Получение информации о платеже

```bash
# Запрос информации о QR-платеже
curl -X GET "https://api.qrpayhub.com/api/v1/payment/payment-info?token=SECURE_TOKEN" \
  -H "Authorization: Bearer your-access-token" \
  -H "User-Agent: MyBank-Mobile/1.0.0" \
  -H "X-Device-ID: device-12345"
```

### 3. Отправка webhook о статусе платежа

```bash
# Уведомление о статусе платежа
curl -X POST "https://api.qrpayhub.com/api/v1/payment/payment-status" \
  -H "Authorization: Bearer your-access-token" \
  -H "Content-Type: application/json" \
  -H "X-Signature: sha256=calculated-hmac-signature" \
  -H "X-Timestamp: 1640995200" \
  -d '{
    "token": "SECURE_TOKEN",
    "status": "success",
    "transaction_id": "TXN123456789",
    "amount": 1000.00,
    "currency": "KGS",
    "payer_phone": "+996555123456",
    "timestamp": "2024-01-01T12:00:00Z"
  }'
```

## 🏗️ Архитектура системы

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   QR Scanner    │────│    QRPayHub      │────│   Your Bank     │
│  (Payer App)    │    │   (Platform)     │    │   (Backend)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │ 1. Scan QR            │                       │
         │ ─────────────────────▶│                       │
         │                       │ 2. Get Payment Info   │
         │                       │ ─────────────────────▶│
         │                       │ 3. Payment Details    │
         │                       │ ◀─────────────────────│
         │ 4. Payment Form       │                       │
         │ ◀─────────────────────│                       │
         │ 5. Confirm Payment    │                       │
         │ ─────────────────────▶│ 6. Payment Webhook    │
         │                       │ ─────────────────────▶│
         │                       │ 7. Status Response    │
         │                       │ ◀─────────────────────│
         │ 8. Payment Result     │                       │
         │ ◀─────────────────────│                       │
```

## 📚 API Документация

### Endpoints

#### 1. Payment Information
- **URL**: `GET /api/v1/payment/payment-info`
- **Описание**: Получение информации о платеже по токену QR-кода
- **Аутентификация**: Bearer Token + IP Whitelist
- **Документация**: [payment-info.md](./api/payment-info.md)

#### 2. Payment Status Webhook  
- **URL**: `POST /api/v1/payment/payment-status`
- **Описание**: Уведомление о статусе обработки платежа
- **Аутентификация**: Bearer Token + HMAC Signature
- **Документация**: [payment-status.md](./api/payment-status.md)

### Схемы данных

#### PaymentInfo Response
```json
{
  "receiver_account": "1234567890123456",
  "receiver_bank_code": "CBKG",
  "receiver_name": "ИП Иванов И.И.",
  "description": "Оплата за товар #12345",
  "amount": 1500.00,
  "currency": "KGS",
  "payment_reference": "QRPAY240101001234"
}
```

#### Payment Status Webhook
```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "status": "success",
  "transaction_id": "TXN240101123456",
  "amount": 1500.00,
  "currency": "KGS",
  "payer_phone": "+996555123456",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## 🛠️ SDK и примеры

### Python SDK
```python
from qrpayhub_sdk import QRPayHubClient

client = QRPayHubClient(
    base_url="https://api.qrpayhub.com",
    access_token="your-access-token",
    hmac_secret="your-hmac-secret"
)

# Получение информации о платеже
payment_info = client.get_payment_info("SECURE_TOKEN")
print(f"Amount: {payment_info.amount} {payment_info.currency}")

# Отправка webhook о статусе
client.send_payment_status(
    token="SECURE_TOKEN",
    status="success",
    transaction_id="TXN123456",
    amount=1500.00,
    payer_phone="+996555123456"
)
```

### Java SDK
```java
QRPayHubClient client = new QRPayHubClient.Builder()
    .baseUrl("https://api.qrpayhub.com")
    .accessToken("your-access-token")
    .hmacSecret("your-hmac-secret")
    .build();

// Получение информации о платеже
PaymentInfo paymentInfo = client.getPaymentInfo("SECURE_TOKEN");
System.out.println("Amount: " + paymentInfo.getAmount());

// Отправка webhook
PaymentStatusRequest request = PaymentStatusRequest.builder()
    .token("SECURE_TOKEN")
    .status(PaymentStatus.SUCCESS)
    .transactionId("TXN123456")
    .amount(new BigDecimal("1500.00"))
    .payerPhone("+996555123456")
    .build();
    
client.sendPaymentStatus(request);
```

### C# SDK
```csharp
var client = new QRPayHubClient(new QRPayHubOptions 
{
    BaseUrl = "https://api.qrpayhub.com",
    AccessToken = "your-access-token",
    HmacSecret = "your-hmac-secret"
});

// Получение информации о платеже
var paymentInfo = await client.GetPaymentInfoAsync("SECURE_TOKEN");
Console.WriteLine($"Amount: {paymentInfo.Amount} {paymentInfo.Currency}");

// Отправка webhook
await client.SendPaymentStatusAsync(new PaymentStatusRequest
{
    Token = "SECURE_TOKEN",
    Status = PaymentStatus.Success,
    TransactionId = "TXN123456",
    Amount = 1500.00m,
    PayerPhone = "+996555123456"
});
```

### PHP SDK
```php
$client = new QRPayHubClient([
    'base_url' => 'https://api.qrpayhub.com',
    'access_token' => 'your-access-token',
    'hmac_secret' => 'your-hmac-secret'
]);

// Получение информации о платеже
$paymentInfo = $client->getPaymentInfo('SECURE_TOKEN');
echo "Amount: {$paymentInfo['amount']} {$paymentInfo['currency']}\n";

// Отправка webhook
$client->sendPaymentStatus([
    'token' => 'SECURE_TOKEN',
    'status' => 'success',
    'transaction_id' => 'TXN123456',
    'amount' => 1500.00,
    'payer_phone' => '+996555123456'
]);
```

## 🔐 Безопасность

### Аутентификация

1. **Bearer Token**: Уникальный токен доступа для каждого банка
2. **IP Whitelist**: Ограничение доступа по IP-адресам
3. **HMAC Signature**: Подпись запросов для webhook

### HMAC Подпись

```python
import hmac
import hashlib
import time

def create_hmac_signature(secret, method, path, body, timestamp):
    """Создание HMAC подписи для запроса"""
    message = f"{method}\n{path}\n{body}\n{timestamp}"
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"

# Пример использования
timestamp = str(int(time.time()))
signature = create_hmac_signature(
    secret="your-hmac-secret",
    method="POST",
    path="/api/v1/payment/payment-status",
    body='{"token":"...","status":"success"}',
    timestamp=timestamp
)

headers = {
    "X-Signature": signature,
    "X-Timestamp": timestamp
}
```

### Валидация запросов

QRPayHub проверяет:
- ✅ User-Agent соответствует настроенному паттерну
- ✅ Обязательные заголовки присутствуют
- ✅ IP-адрес в whitelist
- ✅ HMAC подпись корректна
- ✅ Временная метка не старше 5 минут

## 🧪 Тестирование

### Sandbox Environment

```
Base URL: https://sandbox.qrpayhub.com
Test Access Token: test_bank_token_12345
Test HMAC Secret: test_hmac_secret_67890
```

### Тестовые данные

```json
{
  "test_payment_tokens": [
    "test_token_success_1000",
    "test_token_failed_invalid",
    "test_token_expired_old"
  ],
  "test_accounts": [
    "1234567890123456",
    "9876543210987654"
  ],
  "test_phones": [
    "+996555000001",
    "+996555000002"
  ]
}
```

### Postman Collection

Импортируйте [QRPayHub.postman_collection.json](./postman/QRPayHub.postman_collection.json) для тестирования API.

## 📞 Поддержка

### Контакты
- **Email**: integration@qrpayhub.com
- **Telegram**: @qrpayhub_support
- **Документация**: https://docs.qrpayhub.com
- **Status Page**: https://status.qrpayhub.com

### Мониторинг интеграции

QRPayHub предоставляет:
- 📊 **Real-time мониторинг** статуса интеграции
- 🚨 **Автоматические алерты** при проблемах
- 📈 **Аналитика** успешности транзакций
- 📋 **Детальные логи** всех запросов

### SLA

- **Uptime**: 99.9%
- **Response Time**: < 500ms (95th percentile)
- **Support Response**: < 2 часа (рабочие дни)

---

## 📄 Лицензия

Copyright © 2024 QRPayHub. All rights reserved.

Данная документация предназначена для банков-партнеров QRPayHub и содержит конфиденциальную информацию.
