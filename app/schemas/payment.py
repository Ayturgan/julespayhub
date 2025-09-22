from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class PaymentRequestCreate(BaseModel):
    """Схема для создания платежного запроса"""
    receiver_account: str
    receiver_bank_code: str
    receiver_name: str
    description: str
    amount: Optional[float] = None
    currency: str = "KGS"
    sender_bank_code: Optional[str] = None
    sender_account: Optional[str] = None

class PaymentInfo(BaseModel):
    """Схема ответа для банков - информация о платеже"""
    receiver_account: str
    receiver_bank_code: str
    receiver_name: str
    description: str
    amount: Optional[float]
    currency: str
    payment_reference: str
    sender_bank_code: Optional[str] = None
    sender_account: Optional[str] = None

class QRResponse(BaseModel):
    """Схема ответа при создании QR-кода"""
    qr_url: str
    token: str
    expires_in: int

class PaymentStatusWebhook(BaseModel):
    """Схема webhook от банка о статусе платежа"""
    token: str
    status: str
    transaction_id: str
    bank_transaction_id: Optional[str] = None  # ID транзакции в системе банка
    amount: float
    payer_phone: str
    timestamp: datetime

class PaymentStatusResponse(BaseModel):
    """Ответ на webhook"""
    success: bool
    message: str



class QRCodeGenerateRequest(BaseModel):
    """Схема запроса для генерации QR-кода"""
    description: str
    amount: Optional[float] = None
    currency: Optional[str] = "KGS"
    outlet_id: Optional[int] = None

class QRCodeGenerateResponse(BaseModel):
    """Схема ответа при генерации QR-кода"""
    qr_url: str
    qr_image_base64: str
    token: str
    payment_reference: str
    expires_at: datetime
    amount: Optional[float]
    currency: str
    description: str

