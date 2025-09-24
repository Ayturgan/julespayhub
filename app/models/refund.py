from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Index, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class RefundStatus(enum.Enum):
    """Статусы возвратов (аналогично двухфазным транзакциям)"""
    PENDING = "pending"           # Исходное состояние
    PROCESSING = "processing"     # Запросы созданы в банках, ожидание подтверждения
    PREPARING = "preparing"       # QRPayHub начал фазу подготовки возврата
    PREPARED = "prepared"         # Оба банка подтвердили готовность к возврату
    COMMITTING = "committing"     # QRPayHub дал команду на выполнение возврата
    COMPLETED = "completed"       # Возврат успешно завершен
    ABORTING = "aborting"         # QRPayHub дал команду на отмену возврата
    ABORTED = "aborted"           # Возврат отменен
    FAILED = "failed"             # Возврат завершился с ошибкой

class RefundType(enum.Enum):
    """Типы возвратов"""
    FULL = "FULL"                 # Полный возврат
    PARTIAL = "PARTIAL"           # Частичный возврат

class RefundRequest(Base):
    """Модель для запросов на возврат"""
    __tablename__ = "refund_requests"

    id = Column(Integer, primary_key=True, index=True)
    
    # Связи с существующими таблицами (унифицированные платежи)
    original_payment_id = Column(Integer, ForeignKey("unified_payments.id"), nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False, index=True)
    
    # Основная информация о возврате
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="KGS")
    reason = Column(Text, nullable=True)
    refund_type = Column(Enum(RefundType), default=RefundType.FULL, nullable=False)
    
    # Статус возврата
    status = Column(Enum(RefundStatus), default=RefundStatus.PENDING, nullable=False, index=True)
    
    # Токены и идентификаторы
    refund_token = Column(String(255), unique=True, index=True, nullable=False)
    transaction_id = Column(String(100), nullable=True)
    
    # Двухфазная транзакция (обратные роли)
    sender_bank_code = Column(String(20), nullable=True, index=True)  # Банк продавца (теперь плательщик)
    receiver_bank_code = Column(String(20), nullable=True, index=True) # Банк покупателя (теперь получатель)
    
    # Временные метки для двухфазного протокола
    prepare_started_at = Column(DateTime(timezone=True), nullable=True)
    prepare_completed_at = Column(DateTime(timezone=True), nullable=True)
    commit_started_at = Column(DateTime(timezone=True), nullable=True)
    commit_completed_at = Column(DateTime(timezone=True), nullable=True)
    abort_started_at = Column(DateTime(timezone=True), nullable=True)
    abort_completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Результаты фаз
    sender_prepare_result = Column(Text, nullable=True)     # JSON результат от банка-продавца
    receiver_prepare_result = Column(Text, nullable=True)   # JSON результат от банка-покупателя
    
    # Метаданные
    two_phase_metadata = Column(Text, nullable=True)        # JSON с дополнительной информацией
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Связи
    original_payment = relationship("UnifiedPayment", backref="refunds")
    merchant = relationship("Merchant", backref="refunds")
    
    __table_args__ = (
        Index('ix_refund_requests_merchant_status', 'merchant_id', 'status'),
        Index('ix_refund_requests_created_at', 'created_at'),
        {'comment': 'Запросы на возврат платежей'}
    )

class RefundOperation(Base):
    """Лог операций двухфазного возврата (аналогично TwoPhaseOperation)"""
    __tablename__ = "refund_operations"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связи
    refund_token = Column(String(255), ForeignKey("refund_requests.refund_token"), index=True, nullable=False)
    transaction_id = Column(String(100), nullable=True)
    
    # Операция
    phase = Column(String(20), index=True, nullable=False)  # prepare, commit, abort
    operation_type = Column(String(20), nullable=False)    # request, response, recovery
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
    
    # Связи
    refund_request = relationship("RefundRequest", backref="operations")
    
    # Индексы для поиска
    __table_args__ = (
        Index('ix_refund_ops_token_phase', 'refund_token', 'phase'),
        Index('ix_refund_ops_bank_status', 'bank_code', 'response_status'),
        Index('ix_refund_ops_started_at', 'started_at'),
        {'comment': 'Лог операций двухфазного возврата для отладки и мониторинга'}
    )
