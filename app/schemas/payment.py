from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PaymentInfo(BaseModel):
    receiver_account: str
    receiver_bank_code: str
    receiver_name: str
    description: str
    amount: Optional[float]
    currency: str
    payment_reference: str
    sender_bank_code: Optional[str] = None
    sender_account: Optional[str] = None


class PaymentStatusWebhook(BaseModel):
    token: str
    status: str
    transaction_id: str
    bank_transaction_id: Optional[str] = None
    amount: float
    payer_phone: str
    timestamp: datetime


class PaymentStatusResponse(BaseModel):
    success: bool
    message: str

