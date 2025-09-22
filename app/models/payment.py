from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Index, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum

class TransactionStatus(enum.Enum):
    """Статусы двухфазных транзакций"""
    PENDING = "pending"           # Исходное состояние
    PREPARING = "preparing"       # QRPayHub начал фазу подготовки
    PREPARED = "prepared"         # Оба банка подтвердили готовность, деньги зарезервированы
    COMMITTING = "committing"     # QRPayHub дал команду на выполнение
    COMPLETED = "completed"       # Транзакция успешно завершена
    ABORTING = "aborting"         # QRPayHub дал команду на отмену
    ABORTED = "aborted"           # Транзакция отменена, средства возвращены

class PaymentRequest(Base):
    """Модель для хранения платежных запросов"""
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, index=True, nullable=False)
    
    # Данные получателя
    receiver_account = Column(String(50), nullable=False)
    receiver_bank_code = Column(String(20), nullable=False)
    receiver_name = Column(String(255), nullable=False)
    
    # Связь с продавцом (опционально)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True)
    
    # Данные платежа
    description = Column(Text, nullable=False)
    amount = Column(Float, nullable=True)  # null для ручного ввода
    currency = Column(String(3), default="KGS")
    payment_reference = Column(String(100), unique=True, nullable=False)
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    
    # Статус платежа
    is_paid = Column(Boolean, default=False)
    transaction_id = Column(String(100), nullable=True)
    payer_phone = Column(String(20), nullable=True)
    paid_amount = Column(Float, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    
    # Двухфазная транзакция
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False, index=True)
    sender_bank_code = Column(String(20), nullable=True, index=True)  # Банк отправителя
    payer_bank_code = Column(String(20), nullable=True, index=True)  # Банк плательщика
    sender_account = Column(String(50), nullable=True)  # Счет плательщика
    
    # Временные метки для двухфазного протокола
    prepare_started_at = Column(DateTime(timezone=True), nullable=True)
    prepare_completed_at = Column(DateTime(timezone=True), nullable=True)
    commit_started_at = Column(DateTime(timezone=True), nullable=True)
    commit_completed_at = Column(DateTime(timezone=True), nullable=True)
    abort_started_at = Column(DateTime(timezone=True), nullable=True)
    abort_completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Результаты фазы подготовки от банков
    sender_prepare_result = Column(Text, nullable=True)     # JSON результат от банка-отправителя
    receiver_prepare_result = Column(Text, nullable=True)   # JSON результат от банка-получателя
    
    # Дополнительные метаданные для отладки
    two_phase_metadata = Column(Text, nullable=True)        # JSON с дополнительной информацией о процессе
    # Торговая точка (если создан через конкретный outlet)
    outlet_id = Column(Integer, ForeignKey("trading_points.id"), nullable=True)

class Bank(Base):
    """Модель для банков-партнеров с полной аутентификацией"""
    __tablename__ = "banks"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    bik = Column(String(9), nullable=True)  # БИК банка (9 цифр)
    
    # Аутентификация
    access_token = Column(String(500), nullable=False)  # Bearer token
    hmac_secret = Column(String(500), nullable=False)   # Секрет для HMAC подписи
    allowed_ips = Column(Text, nullable=True)           # JSON список разрешенных IP
    
    # Настройки
    is_active = Column(Boolean, default=True)
    webhook_url = Column(String(500), nullable=True)    # URL для обратных уведомлений
    
    # Валидация запросов
    allowed_user_agents = Column(Text, nullable=True)   # JSON список разрешенных User-Agent
    required_headers = Column(Text, nullable=True)      # JSON обязательных заголовков
    validation_rules = Column(Text, nullable=True)      # JSON правил валидации
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

class PaymentLog(Base):
    """Расширенные логи обращений к API"""
    __tablename__ = "payment_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Основная информация
    token = Column(String(255), index=True)
    bank_code = Column(String(20), index=True)
    request_type = Column(String(50), index=True)  # payment_info, webhook, create_payment
    
    # Сетевая информация
    ip_address = Column(String(45), index=True)
    user_agent = Column(Text)
    
    # HTTP информация
    http_method = Column(String(10))
    endpoint = Column(String(200))
    request_headers = Column(Text)  # JSON
    request_body = Column(Text)     # JSON для POST запросов
    
    # Ответ
    response_status = Column(Integer, index=True)
    response_body = Column(Text)    # JSON ответа
    response_headers = Column(Text) # JSON заголовков ответа
    
    # Время выполнения
    request_duration_ms = Column(Integer)  # Время выполнения в миллисекундах
    
    # Дополнительная информация
    error_message = Column(Text)    # Сообщение об ошибке если есть
    rate_limited = Column(Boolean, default=False)  # Был ли запрос ограничен
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Индексы для быстрого поиска
    __table_args__ = (
        Index('ix_payment_logs_token_created', 'token', 'created_at'),
        {'comment': 'Расширенные логи всех обращений к API'},
    )

class TransactionRecord(Base):
    """Запись о транзакциях для обеспечения идемпотентности"""
    __tablename__ = "transaction_records"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String(100), unique=True, index=True, nullable=False)
    payment_token = Column(String(255), index=True, nullable=False)
    bank_code = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    payer_phone = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False)  # success, failed, pending
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Метаданные для отладки
    webhook_data = Column(Text, nullable=True)  # JSON данных webhook

class BillingRecord(Base):
    """Биллинговые записи для успешных платежей"""
    __tablename__ = "billing_records"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связи с основными сущностями
    payment_token = Column(String(255), index=True, nullable=False)
    transaction_id = Column(String(100), unique=True, index=True, nullable=False)
    
    # Финансовая информация
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="KGS")
    
    # Участники платежа
    payer_phone = Column(String(20), nullable=True)
    payer_bank_code = Column(String(20), index=True, nullable=False)
    receiver_account = Column(String(50), nullable=False)
    receiver_bank_code = Column(String(20), index=True, nullable=False)
    receiver_name = Column(String(255), nullable=False)
    
    # Описание и референс
    payment_description = Column(Text, nullable=False)
    payment_reference = Column(String(100), index=True, nullable=False)
    
    # Комиссии (для будущего использования)
    platform_fee = Column(Float, default=0.0)
    bank_fee = Column(Float, default=0.0)
    
    # Временные метки
    payment_date = Column(DateTime(timezone=True), nullable=False)  # Когда был совершен платеж
    processed_at = Column(DateTime(timezone=True), server_default=func.now())  # Когда обработан в биллинге
    
    # Статус биллинга
    billing_status = Column(String(20), default="processed")  # processed, disputed, refunded
    
    # Дополнительная информация
    ip_address = Column(String(45), nullable=True)  # IP плательщика
    user_agent = Column(Text, nullable=True)  # User-Agent при создании платежа
    
    # Поля для возвратов
    is_refund = Column(Boolean, default=False)  # Является ли записью возврата
    original_payment_id = Column(Integer, nullable=True)  # ID оригинального платежа для возврата
    
    # Метаданные для аналитики
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Индексы для отчетности
    __table_args__ = (
        {'comment': 'Биллинговые записи успешных платежей для отчетности'}
    )

class RateLimitRecord(Base):
    """Записи для отслеживания rate limiting"""
    __tablename__ = "rate_limit_records"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Идентификаторы
    ip_address = Column(String(45), index=True, nullable=False)
    bank_code = Column(String(20), index=True, nullable=True)
    endpoint = Column(String(100), index=True, nullable=False)  # /payment-info, /webhook, etc
    
    # Счетчики и время
    request_count = Column(Integer, default=1)
    window_start = Column(DateTime(timezone=True), server_default=func.now())
    last_request = Column(DateTime(timezone=True), server_default=func.now())
    
    # Блокировка
    is_blocked = Column(Boolean, default=False)
    blocked_until = Column(DateTime(timezone=True), nullable=True)
    
    # Метаданные
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TwoPhaseOperation(Base):
    """Лог операций двухфазного коммита"""
    __tablename__ = "two_phase_operations"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связь с платежом
    payment_token = Column(String(255), index=True, nullable=False)
    transaction_id = Column(String(100), nullable=True)
    
    # Операция
    phase = Column(String(20), index=True, nullable=False)  # prepare, commit, abort
    operation_type = Column(String(20), nullable=False)    # request, response
    bank_code = Column(String(20), index=True, nullable=False)
    bank_role = Column(String(20), nullable=False)         # sender, receiver
    
    # Данные запроса/ответа
    request_data = Column(Text, nullable=True)             # JSON данных запроса
    response_data = Column(Text, nullable=True)            # JSON данных ответа
    response_status = Column(String(20), nullable=True)    # prepared, committed, aborted, error
    
    # Временные метки
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Метаданные
    error_message = Column(Text, nullable=True)
    retry_attempt = Column(Integer, default=0)
    duration_ms = Column(Integer, nullable=True)
    
    # Индексы для поиска
    __table_args__ = (
        Index('ix_two_phase_ops_token_phase', 'payment_token', 'phase'),
        Index('ix_two_phase_ops_bank_status', 'bank_code', 'response_status'),
        {'comment': 'Лог операций двухфазного коммита для отладки и мониторинга'}
    )

class IdempotencyKey(Base):
    """Модель для обеспечения идемпотентности запросов"""
    __tablename__ = "idempotency_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Ключ идемпотентности
    idempotency_key = Column(String(255), unique=True, index=True, nullable=False)
    
    # Связанные данные
    payment_token = Column(String(255), index=True, nullable=True)
    transaction_id = Column(String(100), nullable=True)
    bank_code = Column(String(20), index=True, nullable=True)
    
    # Результат обработки
    response_data = Column(Text, nullable=True)  # JSON ответа
    response_status = Column(Integer, nullable=True)  # HTTP статус
    success = Column(Boolean, nullable=True)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Автоматическое удаление через 24 часа
    
    # Метаданные
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('ix_idempotency_expires', 'expires_at'),
        {'comment': 'Ключи идемпотентности для предотвращения дублирования запросов'}
    )


