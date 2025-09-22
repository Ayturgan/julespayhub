# Инструкция по тестированию QRPayHub в Postman

## Импорт коллекции

1. Скачайте файл `QRPayHub_Collection.json`
2. В Postman: Import → File → выберите скачанный файл
3. Коллекция появится в левой панели

## Подготовка

* Сервер QRPayHub уже запущен
* В коллекции заполните переменные если их нету:
  * `base_url` - https://your-domain.com
  * `bank_access_token` - bank_b2oHGfWsCgKEX9YNomubYjb4JDDGPZzTosrWeNdNb9c
  * `bank_hmac_secret` - rKmufKdcivvqQ0_ZkqDDniUqHVvATzUu4IPmtn_BmhePu1x2P7e2MVu4G5qPcMBsf7sg534lMd9YB4k3VpaGwg
  * `user_agent` - TBank-Test/1.0

## Выполнение

### 1. Регистрация продавца
**POST** `/api/v1/merchant/register`
*Создаём нового продавца в системе с данными компании*
```json
{
  "name": "Тестовая магазин",
  "legal_name": "ОсОО Тестовая магазин", 
  "inn": "2224567899",
  "kpp": "222456789",
  "email": "magazine@gmail.com",
  "phone": "+996777121314",
  "address": "г. Бишкек, ул. Тестовая, д. 1",
  "bank_account": "1234567890123456",
  "bank_name": "TEST BANKTT",
  "bank_bik": "TESTBKGXTT",
  "password": "admin"
}
```

### 2. Вход продавца
**POST** `/api/v1/merchant/login`
*Получаем токен доступа для работы с API*
```json
{
  "email": "magazine@gmail.com",
  "password": "admin"
}
```
*Токен сохранится автоматически*

### 3. Профиль продавца
**GET** `/api/v1/merchant/profile`
*Проверяем что профиль загружается и токен работает*
*Заголовок:* `Authorization: Bearer {{merchant_access_token}}`

### 4. Генерация QR
**POST** `/api/v1/qr/generate`
*Создаём QR-код для оплаты - это как "счёт" для клиента*
*Заголовки:* `Content-Type: application/json`, `Authorization: Bearer {{merchant_access_token}}`
```json
{
  "description": "Американо и пончик",
  "amount": 450.50,
  "currency": "KGS"
}
```

Он выдаст ссылку для оплаты и другие данные
*Payment token сохранится автоматически*

### 5. Банк получает информацию
**GET** `/api/v1/payment/payment-info?token={{payment_token}}`
*Эмулируем что клиент отсканировал QR и банк запрашивает детали платежа*
*Заголовки:* `Authorization: Bearer {{bank_access_token}}`, `User-Agent: {{user_agent}}`

### 6. Webhook об оплате иначе говоря Имитация оплаты и уведомление в сервис
**POST** `/api/v1/payment/payment-status`
*Банк сообщает что клиент оплатил - это как "квитанция" об оплате*
Банк отправляет уведомление об успешной оплате к сервису qrhub
*Все заголовки и подпись генерируются автоматически*

### 7. Проверка платежей
**GET** `/api/v1/merchant/payments`
*Смотрим список всех платежей - должен появиться новый платёж*
*Заголовок:* `Authorization: Bearer {{merchant_access_token}}`

### 8. Статистика
**GET** `/api/v1/merchant/stats`
*Проверяем обновлённую статистику по платежам*
*Заголовок:* `Authorization: Bearer {{merchant_access_token}}`

### 9. Настройки (чтение)
**GET** `/api/v1/merchant/settings`
*Читаем текущие настройки уведомлений и валюты*
*Заголовок:* `Authorization: Bearer {{merchant_access_token}}`

### 10. Список QR-кодов
**GET** `/api/v1/merchant/qr-codes?active_only=true`
*Смотрим все активные QR-коды продавца*
*Заголовок:* `Authorization: Bearer {{merchant_access_token}}`

