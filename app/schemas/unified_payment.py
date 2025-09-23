from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

class PaymentStatus(str, Enum):
    """
    Статусы платежа в унифицированной модели
    - PENDING: Ожидает обработки (начальный статус)
    - PREPARING: Идет подготовка (фаза 1 2PC)
    - PREPARED: Готов к подтверждению (фаза 1 2PC пройдена)
    - COMMITTING: Идет подтверждение (фаза 2 2PC)
    - COMPLETED: Успешно завершен
    - FAILED: Неуспешно завершен
    - ABORTING: Идет отмена (фаза отмены 2PC)
    - CANCELLED: Отменен
    - REFUNDED: Возвращен
    """
    PENDING = "pending"
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTING = "aborting"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class PaymentSystem(str, Enum):
    """
    Платежная система, через которую проходит транзакция
    """
    ELKART = "elkart"
    MBANK = "mbank"
    OTHER = "other"

class UnifiedPaymentBase(BaseModel):
    """
    Базовая схема для унифицированного платежа
    """
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field("KGS", description="Валюта платежа (по умолчанию KGS)")
    description: str = Field(..., description="Описание/назначение платежа")

    # Информация о получателе (мерчант или физ. лицо)
    receiver_account: str = Field(..., description="Счет получателя")
    receiver_name: str = Field(..., description="Имя получателя")
    receiver_bank_code: str = Field(..., description="Банковский код получателя (БИК)")

    # Информация о плательщике
    sender_account: Optional[str] = Field(None, description="Счет плательщика")
    sender_bank_code: Optional[str] = Field(None, description="Банковский код плательщика (БИК)")
    sender_phone: Optional[str] = Field(None, description="Телефон плательщика")

    # Системная информация
    status: PaymentStatus = Field(PaymentStatus.PENDING, description="Статус платежа")
    payment_system: Optional[PaymentSystem] = Field(None, description="Платежная система")
    transaction_id: Optional[str] = Field(None, description="Уникальный ID транзакции в нашей системе")
    bank_transaction_id: Optional[str] = Field(None, description="ID транзакции в банковской системе")

    # Связи
    merchant_id: Optional[int] = Field(None, description="ID мерчанта, если применимо")
    qr_code_id: Optional[int] = Field(None, description="ID QR-кода, если платеж через QR")

    # Дополнительные данные
    metadata: Optional[Dict[str, Any]] = Field(None, description="Дополнительные метаданные")

    class Config:
        from_attributes = True
        use_enum_values = True


class UnifiedPaymentCreate(UnifiedPaymentBase):
    """
    Схема для создания новой записи о платеже в базе данных.
    Используется внутренними сервисами.
    """
    pass


class UnifiedPaymentResponse(UnifiedPaymentBase):
    """
    Схема для ответа API, содержащая полную информацию о платеже.
    """
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UnifiedPaymentUpdate(BaseModel):
    """
    Схема для обновления статуса и другой информации о платеже.
    """
    status: Optional[PaymentStatus] = None
    bank_transaction_id: Optional[str] = None
    sender_account: Optional[str] = None
    sender_bank_code: Optional[str] = None
    sender_phone: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
