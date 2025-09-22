from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class RefundType(str, Enum):
    """Типы возвратов"""
    FULL = "FULL"
    PARTIAL = "PARTIAL"

class RefundStatus(str, Enum):
    """Статусы возвратов"""
    PENDING = "pending"
    PROCESSING = "processing"  # Запросы созданы в банках, ожидание подтверждения
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMPLETED = "completed"
    ABORTING = "aborting"
    ABORTED = "aborted"
    FAILED = "failed"

class RefundCreate(BaseModel):
    """Схема для создания возврата"""
    original_payment_id: int = Field(..., description="ID оригинального платежа")
    amount: float = Field(..., gt=0, description="Сумма возврата")
    currency: str = Field(default="KGS", description="Валюта возврата")
    reason: str = Field(..., min_length=1, max_length=500, description="Причина возврата")
    refund_type: RefundType = Field(default=RefundType.FULL, description="Тип возврата")

class RefundResponse(BaseModel):
    """Схема ответа с данными возврата"""
    id: int
    original_payment_id: int
    merchant_id: int
    amount: float
    currency: str
    reason: Optional[str]
    refund_type: RefundType
    status: RefundStatus
    refund_token: str
    transaction_id: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class RefundListResponse(BaseModel):
    """Схема для списка возвратов"""
    refunds: List[RefundResponse]
    total: int
    page: int
    per_page: int
    total_pages: int

class RefundSummary(BaseModel):
    """Схема для сводки по возвратам"""
    total_refunds: int
    total_amount: float
    currency: str
    completed_refunds: int
    pending_refunds: int
    failed_refunds: int

# Схемы для двухфазного протокола возвратов

class RefundPrepareRequest(BaseModel):
    """Запрос на подготовку возврата"""
    transaction_id: str
    refund_token: str
    amount: float
    currency: str = "KGS"
    original_payment_id: int
    reason: str
    bank_role: str  # sender, receiver
    
    # Данные отправителя (продавца)
    sender_account: Optional[str] = None
    sender_phone: Optional[str] = None
    
    # Данные получателя (покупателя)
    receiver_account: Optional[str] = None
    receiver_phone: Optional[str] = None
    
    # Дополнительные параметры
    timeout_seconds: Optional[int] = 300
    metadata: Optional[Dict[str, Any]] = None

class RefundPrepareResponse(BaseModel):
    """Ответ банка на запрос подготовки возврата"""
    status: str  # prepared, aborted, error
    transaction_id: str
    message: Optional[str] = None
    
    # Дополнительная информация от банка
    reserved_amount: Optional[float] = None
    reservation_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class RefundCommitRequest(BaseModel):
    """Запрос на выполнение возврата"""
    transaction_id: str
    refund_token: str
    original_payment_id: int
    reservation_id: Optional[str] = None
    prepared_amount: float
    bank_role: str  # sender, receiver
    final_amount: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class RefundCommitResponse(BaseModel):
    """Ответ банка на команду выполнения возврата"""
    status: str  # committed, aborted, error
    transaction_id: str
    message: Optional[str] = None
    
    # Результат выполнения
    actual_amount: Optional[float] = None
    bank_transaction_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class RefundAbortRequest(BaseModel):
    """Запрос на отмену возврата"""
    transaction_id: str
    refund_token: str
    original_payment_id: int
    reservation_id: Optional[str] = None
    bank_role: str  # sender, receiver
    abort_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class RefundAbortResponse(BaseModel):
    """Ответ банка на команду отмены возврата"""
    status: str  # aborted, error
    transaction_id: str
    message: Optional[str] = None
    
    # Результат отмены
    released_amount: Optional[float] = None
    released_at: Optional[datetime] = None
    
    # В случае ошибки
    error_code: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

class RefundOperationResult(BaseModel):
    """Результат операции с банком для возврата"""
    bank_code: str
    bank_role: str  # sender, receiver
    operation: str  # prepare, commit, abort
    success: bool
    
    # Данные ответа
    response_status: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None
    
    # Время выполнения
    duration_ms: Optional[int] = None
    
    # В случае ошибки
    error_message: Optional[str] = None

class RefundValidationError(BaseModel):
    """Ошибка валидации возврата"""
    field: str
    message: str
    code: str

class RefundValidationResult(BaseModel):
    """Результат валидации возврата"""
    valid: bool
    errors: List[RefundValidationError] = []
    warnings: List[str] = []
    
    def add_error(self, field: str, message: str, code: str = "validation_error"):
        """Добавление ошибки валидации"""
        self.errors.append(RefundValidationError(field=field, message=message, code=code))
        self.valid = False
    
    def add_warning(self, message: str):
        """Добавление предупреждения"""
        self.warnings.append(message)
    
    def has_errors(self) -> bool:
        """Проверка наличия ошибок"""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Проверка наличия предупреждений"""
        return len(self.warnings) > 0
