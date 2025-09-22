from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class BankCreate(BaseModel):
    """Схема для создания банка"""
    code: str
    name: str
    allowed_ips: Optional[List[str]] = None
    webhook_url: Optional[str] = None

class BankResponse(BaseModel):
    """Схема ответа с данными банка"""
    id: int
    code: str
    name: str
    access_token: str
    hmac_secret: str
    allowed_ips: Optional[str] = None
    webhook_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BankUpdate(BaseModel):
    """Схема для обновления банка"""
    name: Optional[str] = None
    allowed_ips: Optional[List[str]] = None
    webhook_url: Optional[str] = None
    is_active: Optional[bool] = None

class BankList(BaseModel):
    """Схема для списка банков (без секретов)"""
    id: int
    code: str
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Схемы для двухфазного протокола

class TwoPhaseOperationStatus(str, Enum):
    """Статусы операций двухфазного коммита"""
    PREPARED = "prepared"
    COMMITTED = "committed"
    ABORTED = "aborted"
    ERROR = "error"

class BankRole(str, Enum):
    """Роли банков в транзакции"""
    SENDER = "sender"      # Банк отправителя (списывает средства)
    RECEIVER = "receiver"  # Банк получателя (зачисляет средства)

class TransactionPrepareRequest(BaseModel):
    """Запрос на подготовку транзакции (POST /api/v1/banks/transactions/prepare)"""
    transaction_id: str
    payment_token: str
    amount: float
    currency: str = "KGS"
    
    # Данные отправителя (для банка отправителя)
    sender_account: Optional[str] = None
    sender_phone: Optional[str] = None
    
    # Данные получателя (для банка получателя)
    receiver_account: str
    receiver_name: str
    
    # Описание платежа
    description: str
    payment_reference: str
    
    # Роль банка в этой транзакции
    bank_role: BankRole
    
    # Дополнительные параметры
    timeout_seconds: Optional[int] = 300  # Таймаут резервирования средств
    metadata: Optional[Dict[str, Any]] = None

class TransactionPrepareResponse(BaseModel):
    """Ответ банка на запрос подготовки"""
    status: TwoPhaseOperationStatus
    transaction_id: str
    message: Optional[str] = None
    
    # Дополнительная информация от банка
    reserved_amount: Optional[float] = None  # Фактически зарезервированная сумма
    reservation_id: Optional[str] = None     # ID резервирования в банке
    expires_at: Optional[datetime] = None    # Срок действия резервирования
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class TransactionCommitRequest(BaseModel):
    """Запрос на выполнение транзакции (POST /api/v1/banks/transactions/commit)"""
    transaction_id: str
    payment_token: str
    
    # Данные из фазы подготовки
    reservation_id: Optional[str] = None  # ID резервирования, если банк его предоставил
    prepared_amount: float  # Сумма, которая была зарезервирована
    
    # Роль банка
    bank_role: BankRole
    
    # Дополнительные параметры
    final_amount: Optional[float] = None  # Финальная сумма (может отличаться от зарезервированной)
    metadata: Optional[Dict[str, Any]] = None

class TransactionCommitResponse(BaseModel):
    """Ответ банка на команду выполнения"""
    status: TwoPhaseOperationStatus
    transaction_id: str
    message: Optional[str] = None
    
    # Результат выполнения
    actual_amount: Optional[float] = None     # Фактически списанная/зачисленная сумма
    bank_transaction_id: Optional[str] = None # ID транзакции в системе банка
    completed_at: Optional[datetime] = None   # Время выполнения
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class TransactionAbortRequest(BaseModel):
    """Запрос на отмену транзакции (POST /api/v1/banks/transactions/abort)"""
    transaction_id: str
    payment_token: str
    
    # Данные из фазы подготовки
    reservation_id: Optional[str] = None  # ID резервирования для отмены
    
    # Роль банка
    bank_role: BankRole
    
    # Причина отмены
    abort_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class TransactionAbortResponse(BaseModel):
    """Ответ банка на команду отмены"""
    status: TwoPhaseOperationStatus
    transaction_id: str
    message: Optional[str] = None
    
    # Результат отмены
    released_amount: Optional[float] = None   # Размороженная сумма
    released_at: Optional[datetime] = None    # Время отмены резервирования
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

# Дополнительные схемы для внутреннего использования

class TwoPhaseTransactionState(BaseModel):
    """Состояние двухфазной транзакции"""
    payment_token: str
    transaction_id: str
    current_status: str
    
    # Участники
    sender_bank_code: str
    receiver_bank_code: str
    
    # Результаты фаз
    sender_prepare_status: Optional[TwoPhaseOperationStatus] = None
    receiver_prepare_status: Optional[TwoPhaseOperationStatus] = None
    sender_commit_status: Optional[TwoPhaseOperationStatus] = None
    receiver_commit_status: Optional[TwoPhaseOperationStatus] = None
    
    # Временные метки
    started_at: datetime
    prepare_deadline: Optional[datetime] = None
    commit_deadline: Optional[datetime] = None
    
    # Метаданные
    retry_count: int = 0
    last_error: Optional[str] = None

class BankOperationResult(BaseModel):
    """Результат операции с банком"""
    bank_code: str
    bank_role: BankRole
    operation: str  # prepare, commit, abort
    success: bool
    
    # Данные ответа
    response_status: Optional[TwoPhaseOperationStatus] = None
    response_data: Optional[Dict[str, Any]] = None
    
    # Метаданные
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    retry_attempt: int = 0

# Схемы для API двухфазного платежа

class TwoPhasePaymentRequest(BaseModel):
    """Запрос на инициацию двухфазного платежа"""
    token: str = Field(..., min_length=10, max_length=255, description="Токен платежа")
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(default="KGS", min_length=3, max_length=3, description="Валюта платежа")
    payer_phone: Optional[str] = Field(None, min_length=10, max_length=20, description="Телефон плательщика")
    sender_account: Optional[str] = Field(None, min_length=10, max_length=50, description="Счет отправителя")
    payment_reference: str = Field(..., min_length=5, max_length=100, description="Ссылка на платеж")
    idempotency_key: str = Field(..., min_length=10, max_length=255, description="Ключ идемпотентности для предотвращения дублирования")
    
    class Config:
        json_schema_extra = {
            "example": {
                "token": "qr_abc123def456",
                "amount": 1000.00,
                "currency": "KGS",
                "payer_phone": "+996700123456",
                "sender_account": "1234567890",
                "payment_reference": "PAY-2024-001",
                "idempotency_key": "idemp_abc123def456_20240101_120000"
            }
        }

class TwoPhasePaymentResponse(BaseModel):
    """Ответ на запрос двухфазного платежа"""
    success: bool
    transaction_id: str
    status: str
    message: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    requires_manual_intervention: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "transaction_id": "2PC_qr_abc123def456_1704110400",
                "status": "completed",
                "message": "Two-phase transaction completed successfully",
                "amount": 1000.00,
                "currency": "KGS",
                "requires_manual_intervention": False
            }
        }
