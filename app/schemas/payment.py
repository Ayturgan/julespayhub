from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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

