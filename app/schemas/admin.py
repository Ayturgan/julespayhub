from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

class AdminRole(str, Enum):
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    MODERATOR = "moderator"
    VIEWER = "viewer"

class AdminLogin(BaseModel):
    """Схема для входа админа"""
    username: str
    password: str

class AdminCreate(BaseModel):
    """Схема для создания админа"""
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: AdminRole = AdminRole.ADMIN

class AdminResponse(BaseModel):
    """Схема ответа с данными админа"""
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

class AdminUpdate(BaseModel):
    """Схема для обновления админа"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[AdminRole] = None
    is_active: Optional[bool] = None

class AdminPasswordChange(BaseModel):
    """Схема для смены пароля"""
    current_password: str
    new_password: str

class AdminToken(BaseModel):
    """Схема для токена админа"""
    access_token: str
    token_type: str = "bearer"
    admin: AdminResponse

class AdminProfile(BaseModel):
    """Схема профиля админа с банковскими реквизитами"""
    phone: Optional[str] = None
    organization_name: Optional[str] = None
    inn: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_bik: Optional[str] = None
    bank_code: Optional[str] = None
    address: Optional[str] = None
    qr_settings: Optional[Dict[str, Any]] = None

class AdminProfileUpdate(BaseModel):
    """Схема для обновления профиля админа"""
    phone: Optional[str] = None
    organization_name: Optional[str] = None
    inn: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_bik: Optional[str] = None
    bank_code: Optional[str] = None
    address: Optional[str] = None
    qr_settings: Optional[Dict[str, Any]] = None

class AdminFullResponse(AdminResponse):
    """Расширенная схема ответа с профилем админа"""
    phone: Optional[str] = None
    organization_name: Optional[str] = None
    inn: Optional[str] = None
    bank_account: Optional[str] = None
    bank_name: Optional[str] = None
    bank_bik: Optional[str] = None
    bank_code: Optional[str] = None
    address: Optional[str] = None
    qr_settings: Optional[Dict[str, Any]] = None
    has_complete_profile: bool = False
