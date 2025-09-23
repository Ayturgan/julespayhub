from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class UnifiedQRCodeBase(BaseModel):
    """
    Базовая схема для унифицированного QR-кода.
    """
    name: str = Field(..., description="Название QR-кода для идентификации")
    description: Optional[str] = Field(None, description="Краткое описание QR-кода")
    amount: Optional[float] = Field(None, gt=0, description="Сумма, зашитая в QR-код (если есть)")
    currency: str = Field("KGS", description="Валюта")

    merchant_id: Optional[int] = Field(None, description="ID мерчанта, к которому привязан QR-код")
    admin_id: Optional[int] = Field(None, description="ID администратора, создавшего QR-код")
    outlet_id: Optional[int] = Field(None, description="ID торговой точки мерчанта")

    class Config:
        from_attributes = True


class UnifiedQRCodeCreate(UnifiedQRCodeBase):
    """
    Схема для создания QR-кода.
    """
    expires_in_minutes: Optional[int] = Field(None, description="Через сколько минут QR-код станет недействительным")
    max_uses: Optional[int] = Field(None, description="Максимальное количество использований")


class UnifiedQRCodeResponse(UnifiedQRCodeBase):
    """
    Схема для ответа API с полной информацией о QR-коде.
    """
    id: int
    qr_token: str = Field(..., description="Уникальный токен, вшитый в QR-данные")
    qr_url: str = Field(..., description="URL для оплаты по QR-коду")
    qr_image_base64: Optional[str] = Field(None, description="QR-код в формате Base64")

    is_active: bool = Field(..., description="Активен ли QR-код")
    current_uses: int = Field(..., description="Текущее количество использований")
    max_uses: Optional[int] = Field(None, description="Максимальное количество использований")

    expires_at: Optional[datetime] = Field(None, description="Дата и время истечения срока действия")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QRCodeUpdateRequest(BaseModel):
    """
    Схема для обновления данных QR-кода.
    """
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
