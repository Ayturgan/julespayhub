from pydantic import BaseModel, EmailStr, validator, field_serializer
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from enum import Enum

class MerchantStatus(str, Enum):
    """Статусы продавца"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"

class PaymentStatus(str, Enum):
    """Статусы платежей"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# Схемы для регистрации и аутентификации
class MerchantRegister(BaseModel):
    """Схема для регистрации продавца"""
    name: str
    legal_name: str
    inn: str
    kpp: Optional[str] = None
    email: EmailStr
    phone: str
    address: str
    bank_account: str
    bank_name: str
    bank_bik: str
    password: str
    
    @validator('inn')
    def validate_inn(cls, v):
        if len(v) != 14:  # ИНН для Кыргызстана (14 цифр)
            raise ValueError('ИНН должен содержать 14 цифр')
        if not v.isdigit():
            raise ValueError('ИНН должен содержать только цифры')
        return v
    
    @validator('kpp')
    def validate_kpp(cls, v):
        if v and len(v) != 9:
            raise ValueError('КПП должен содержать 9 цифр')
        return v

class MerchantLogin(BaseModel):
    """Схема для входа продавца"""
    email: EmailStr
    password: str

class MerchantLoginResponse(BaseModel):
    """Ответ на логин продавца"""
    access_token: str
    token_type: str = "bearer"
    merchant: 'MerchantResponse'

class MerchantResponse(BaseModel):
    """Схема ответа с данными продавца"""
    id: int
    name: str
    legal_name: str
    inn: str
    kpp: Optional[str]
    email: str
    phone: str
    address: str
    bank_account: str
    bank_name: str
    bank_bik: str
    api_key: str
    is_active: bool
    is_verified: bool
    daily_limit: float
    monthly_limit: float
    created_at: datetime
    last_activity: Optional[datetime]
    qr_codes_count: Optional[int] = 0
    payments_count: Optional[int] = 0
    
    class Config:
        from_attributes = True

class MerchantDetailResponse(MerchantResponse):
    """Схема ответа с детальной информацией о продавце"""
    total_amount: Optional[float] = 0

# Схемы для QR-кодов
class QRCodeCreate(BaseModel):
    """Схема для создания QR-кода"""
    name: str
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "KGS"
    expires_at: Optional[datetime] = None
    expires_in_minutes: Optional[int] = None
    max_uses: Optional[int] = None
    outlet_id: Optional[int] = None

class QRCodeResponse(BaseModel):
    """Схема ответа с данными QR-кода"""
    id: int
    merchant_id: int
    name: str
    description: Optional[str]
    amount: Optional[float]
    currency: str
    qr_token: str
    qr_url: str
    qr_image_path: Optional[str]
    qr_image_base64: Optional[str]
    is_active: bool
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    current_uses: int
    created_at: datetime
    updated_at: datetime
    
    @field_serializer('created_at', 'updated_at', 'expires_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        # Конвертируем UTC время в локальное время пользователя (UTC+6 для Кыргызстана)
        local_dt = dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=6)))
        return local_dt.isoformat()
    
    class Config:
        from_attributes = True

# Схемы для платежей
class MerchantPaymentResponse(BaseModel):
    """Схема ответа с данными платежа продавца"""
    id: int
    merchant_id: int
    qr_code_id: Optional[int]
    outlet_id: Optional[int]
    amount: float
    currency: str
    status: PaymentStatus
    payer_phone: Optional[str]
    payer_bank_code: Optional[str]
    sender_account: Optional[str]  # Счет плательщика
    transaction_id: Optional[str]
    bank_transaction_id: Optional[str]
    created_at: datetime
    paid_at: Optional[datetime]
    error_message: Optional[str]
    
    class Config:
        from_attributes = True

# Схемы для обновления профиля
class MerchantProfileUpdate(BaseModel):
    """Схема для обновления профиля продавца"""
    name: Optional[str] = None
    legal_name: Optional[str] = None
    inn: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_bik: Optional[str] = None
    
    @validator('inn')
    def validate_inn(cls, v):
        if v and len(v) != 14:
            raise ValueError('ИНН должен содержать 14 цифр')
        if v and not v.isdigit():
            raise ValueError('ИНН должен содержать только цифры')
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        if v and not v.startswith('+996'):
            raise ValueError('Телефон должен начинаться с +996')
        if v and len(v) != 13:
            raise ValueError('Телефон должен содержать 13 символов (+996XXXXXXXXX)')
        return v
    
    @validator('bank_bik')
    def validate_bank_bik(cls, v):
        if v and len(v) != 9:
            raise ValueError('БИК должен содержать 9 цифр')
        return v
    
    @validator('bank_account')
    def validate_bank_account(cls, v):
        if v and len(v) != 16:
            raise ValueError('Номер счёта должен содержать 16 цифр')
        return v

# Схемы для настроек
class MerchantSettingsUpdate(BaseModel):
    """Схема для обновления настроек продавца"""
    email_notifications: Optional[bool] = None
    sms_notifications: Optional[bool] = None
    webhook_url: Optional[str] = None
    default_currency: Optional[str] = None
    qr_code_expiry_hours: Optional[int] = None
    auto_generate_qr_images: Optional[bool] = None
    daily_reports: Optional[bool] = None
    weekly_reports: Optional[bool] = None
    monthly_reports: Optional[bool] = None
    ip_whitelist: Optional[List[str]] = None
    require_webhook_signature: Optional[bool] = None

class MerchantSettingsResponse(BaseModel):
    """Схема ответа с настройками продавца"""
    id: int
    merchant_id: int
    email_notifications: bool
    sms_notifications: bool
    webhook_url: Optional[str]
    webhook_secret: Optional[str]
    default_currency: str
    qr_code_expiry_hours: int
    auto_generate_qr_images: bool
    daily_reports: bool
    weekly_reports: bool
    monthly_reports: bool
    ip_whitelist: Optional[List[str]]
    require_webhook_signature: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Схемы для отчетов
class MerchantStats(BaseModel):
    """Схема статистики продавца"""
    total_payments: int
    total_amount: float
    successful_payments: int
    failed_payments: int
    success_rate: float
    average_payment_amount: float
    active_qr_codes: int
    total_qr_codes: int
    active_outlets: int = 0
    total_outlets: int = 0
    today_amount: float = 0
    yesterday_amount: float = 0
    status_distribution: Optional[Dict[str, int]] = None

class PaymentSummary(BaseModel):
    """Схема сводки платежей"""
    date: str
    payments_count: int
    total_amount: float
    successful_count: int
    failed_count: int
