# Отчёт по рефакторингу QRPayHub (Unified модели)

## Обзор
Цель: упростить систему, объединив разрозненные модели QR-кодов и платежей в две унифицированные сущности — `UnifiedQRCode` и `UnifiedPayment`. Это устраняет дублирование и условные ветвления (merchant/admin/2PC/обычные платежи) и упрощает бизнес-логику, симулятор и API.

Итог: кодовая база переведена на Unified-модели; сервисы, эндпоинты и симулятор обновлены; БД пересоздана. Старые модели удалены или заменены алиасами там, где это необходимо для совместимости импортов на переходном этапе.

---

## Этап 1: Унифицированные модели и схема БД

### Сделано
- Созданы модели (`app/models/unified.py`):
  - `UnifiedQRCode` — единая модель QR-кода (для продавцов и администраторов):
    - Основные поля: `id`, `name`, `description`, `amount?`, `currency`, `qr_token`, `qr_url`
    - Состояние: `is_active`, `expires_at?`, `max_uses?`, `current_uses`
    - Связи: `merchant_id?`, `admin_id?`, `outlet_id?` (FK на `trading_points.id`), `payments`
  - `UnifiedPayment` — единая модель платежа (2PC и простые):
    - Основные поля: `id`, `amount`, `currency`, `status (TransactionStatus)`, `description?`
    - Получатель: `receiver_name`, `receiver_account`, `receiver_bank_code`
    - Плательщик: `payer_phone?`, `payer_bank_code?`, `sender_account?`, `sender_bank_code?`
    - 2PC/идемпотентность: `transaction_id?`, `is_paid`, `paid_amount?`, `paid_at?`, `prepare_*`, `commit_*`, `abort_*`, `sender_prepare_result?`, `receiver_prepare_result?`, `two_phase_metadata?`
    - Идентификаторы совместимости: `token?`, `payment_reference?`, `expires_at?`, `is_used`
    - Связи: `merchant_id?`, `admin_id?`, `qr_code_id?`, `outlet_id?`
- Вынесены статусы в `app/models/enums.py` (`TransactionStatus`).
- Удалены старые классы моделей (или заменены алиасами для совместимости импортов):
  - `PaymentRequest` → алиас на `UnifiedPayment` в `app/models/payment.py`
  - `QRCode` → алиас на `UnifiedQRCode` в `app/models/merchant.py`
  - `AdminQRCode` — заменён unified-моделью с `admin_id`
  - `MerchantPayment` — заменён алиасом на `UnifiedPayment` там, где это требуется по импортам
- Обновлён `init_db.py` для создания только unified-таблиц. Убраны старые сидеры, статистики — синхронизировано под Unified.
- FK в возвратах: `app/models/refund.py` — `original_payment_id -> unified_payments.id`.

### Проверка/Запуск
1) Инициализация окружения (пример):
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```
2) Пересоздание БД:
```bash
python init_db.py --reset --no-seed
```
Ожидаемый результат: созданы таблицы `unified_qrcodes`, `unified_payments`; старых таблиц (`qr_codes`, `admin_qr_codes`, `merchant_payments`, `payment_requests`) нет.

---

## Этап 2: Адаптация бизнес-логики

### Pydantic-схемы
- Созданы unified-схемы (`app/schemas/unified.py`):
  - `UnifiedQRCodeCreate`, `UnifiedQRCodeRead`
  - `UnifiedPaymentCreate`, `UnifiedPaymentRead`
- Очищены/упрощены старые схемы. В `app/schemas/payment.py` восстановлен `PaymentInfo` для банковских эндпоинтов.

### Сервисный слой
- Двухфазные транзакции (`app/services/two_phase_commit_service.py`):
  - Работает с `PaymentRequest` (алиас Unified). Обновляет `transaction_id`, `prepare_*`, `commit_*`, `abort_*`, `is_paid`, `paid_at`, `paid_amount`.
- Webhook (`app/services/webhook_service.py`):
  - Идемпотентная обработка, запись `TransactionRecord`, перенос `outlet_id`, обновление Unified-платежа, биллинг, таймлайн.
- QR-сервис (`app/services/qr_service.py`):
  - Переведён на unified-схемы, возвращает unified-ответы.
- Платежи продавцов (`app/services/merchant_payment_service.py`):
  - Маппинг unified-статусов на агрегированные статусы UI (completed/failed/pending), корректные фильтры и статистика.
- Торговые точки (`app/services/merchant_outlet_service.py`):
  - Совместимо через `outlet_id` в unified-моделях, генерация QR и связка с `PaymentRequest`.

### Эндпоинты
- Merchant (`app/api/v1/endpoints/merchant.py`):
  - `POST/GET /qr-codes` и `GET /qr-codes/{id}` используют `UnifiedQRCodeCreate/Read`.
- Admin/Payments (`app/api/v1/endpoints/admin/payments.py`):
  - `POST /create-payment` принимает `UnifiedPaymentCreate`, создаёт `PaymentRequest` (Unified).
- Admin/QR Security (`app/api/v1/endpoints/admin/qr_security.py`):
  - Создание защищённого QR через `UnifiedPaymentCreate`.
- Admin/QR Codes (`app/api/v1/endpoints/admin/qr_codes.py`):
  - Создание и список — через unified `QRCode` c `admin_id`.
- Общая чистка импортов старых схем в `admin/admins.py`, `admin/alerts.py` и др.

### Симулятор
- `simulation/simulation_router.py`:
  - Полностью унифицирован: поиск `QRCode` по токену/UUID, валидации, создание `PaymentRequest` c `merchant_id`/`admin_id`. Источники логов и баланса — из Unified `PaymentRequest` c `COMPLETED`.

### БД/Проверка
- Повторный `python init_db.py --reset --no-seed` — таблицы создаются, ошибок нет.

---

## Ключевые файлы и изменения
- Модели: `app/models/unified.py`, `app/models/enums.py`, алиасы в `app/models/payment.py`, `app/models/merchant.py`, FK в `app/models/refund.py`.
- Схемы: `app/schemas/unified.py`, обновления в `app/schemas/payment.py`, правки в `app/schemas/merchant.py` (устаревшие помечены/согласованы).
- Сервисы: `qr_service.py`, `two_phase_commit_service.py`, `webhook_service.py`, `merchant_payment_service.py`, `merchant_outlet_service.py`.
- Эндпоинты: `merchant.py`, `admin/payments.py`, `admin/qr_security.py`, `admin/qr_codes.py`, `admin/admins.py`, `admin/alerts.py`, `payment.py` (совместим через алиасы).
- Симулятор: `simulation/simulation_router.py`.
- Инициализация БД: `init_db.py`.

---

## Инструкции по запуску
1) Зависимости и БД:
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python init_db.py --reset --no-seed
```
2) Запуск приложения:
```bash
uvicorn app.main:app --reload
```
3) Симулятор (опционально):
```bash
ENABLE_BANK_SIMULATOR=true uvicorn app.main:app --reload
# Либо
python run_with_simulator.py
```

- Приложение: http://localhost:8000/
- Симулятор: http://localhost:8000/simulation

---

## Совместимость и последующие шаги
- Документация/SDK/Postman: рекомендуется обновить описания и примеры под Unified‑схемы.
- Сервисные слои (проверка): `billing_service.py`, `refund_service.py`, `realtime_monitoring_service.py`, `bank_adapter_service.py`, `enhanced_validation_service.py` — согласованы по полям; при расширении использовать unified‑структуры.
- Миграция данных: в рамках MVP выполнено полное пересоздание БД без переноса исторических данных.

---

## Риски/примечания
- Старые импорты моделей подменены алиасами (`PaymentRequest`, `QRCode`) для совместимости; новая логика работает через Unified‑модели.
- Симулятор и 2PC ориентированы на обновлённые поля (`prepare_*`, `commit_*`, `abort_*` и т.д.) — это единый «источник правды».

---

## Краткий итог
- Введены `UnifiedPayment` и `UnifiedQRCode`.
- Обновлены сервисы, эндпоинты, симулятор и схема БД.
- Кодовая база упрощена, условные ветвления по типам QR/платежей убраны.
- Готово к дальнейшей разработке и расширению.
