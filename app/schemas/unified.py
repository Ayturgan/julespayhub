from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UnifiedQRCodeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "KGS"
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    merchant_id: Optional[int] = None
    admin_id: Optional[int] = None


class UnifiedQRCodeRead(BaseModel):
    id: int
    merchant_id: Optional[int]
    admin_id: Optional[int]
    name: str
    description: Optional[str]
    amount: Optional[float]
    currency: str
    qr_token: str
    qr_url: str
    is_active: bool
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    current_uses: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UnifiedPaymentCreate(BaseModel):
    amount: float
    currency: str = "KGS"
    description: Optional[str] = None
    merchant_id: Optional[int] = None
    admin_id: Optional[int] = None
    qr_code_id: Optional[int] = None

    # receiver
    receiver_name: str
    receiver_account: str
    receiver_bank_code: str

    # payer
    payer_phone: Optional[str] = None
    payer_bank_code: Optional[str] = None
    sender_account: Optional[str] = None
    sender_bank_code: Optional[str] = None

    # two-phase
    transaction_id: Optional[str] = None


class UnifiedPaymentRead(BaseModel):
    id: int
    merchant_id: Optional[int]
    admin_id: Optional[int]
    qr_code_id: Optional[int]

    amount: float
    currency: str
    status: str
    description: Optional[str]

    receiver_name: str
    receiver_account: str
    receiver_bank_code: str

    payer_phone: Optional[str]
    payer_bank_code: Optional[str]
    sender_account: Optional[str]
    sender_bank_code: Optional[str]

    transaction_id: Optional[str]
    is_paid: bool
    paid_amount: Optional[float]
    paid_at: Optional[datetime]

    prepare_started_at: Optional[datetime]
    prepare_completed_at: Optional[datetime]
    commit_started_at: Optional[datetime]
    commit_completed_at: Optional[datetime]
    abort_started_at: Optional[datetime]
    abort_completed_at: Optional[datetime]

    error_code: Optional[str]
    error_message: Optional[str]

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

