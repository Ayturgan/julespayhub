from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from datetime import datetime, timezone
import bcrypt

class Admin(Base):
    """Модель администратора системы"""
    
    __tablename__ = "admins"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), default="admin")  # admin, super_admin
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Дополнительные поля для безопасности
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Профиль и банковские реквизиты для создания QR-кодов
    phone = Column(String(20), nullable=True)
    organization_name = Column(String(255), nullable=True)  # Название организации
    inn = Column(String(20), nullable=True)  # ИНН организации
    bank_account = Column(String(50), nullable=True)  # Банковский счет
    bank_name = Column(String(255), nullable=True)  # Название банка
    bank_bik = Column(String(20), nullable=True)  # БИК банка
    bank_code = Column(String(20), nullable=True)  # Код банка для QR
    address = Column(Text, nullable=True)  # Адрес организации
    
    # Настройки для QR-кодов
    qr_settings = Column(JSON, nullable=True)  # Настройки по умолчанию для QR
    
    def set_password(self, password: str):
        """Хеширование пароля с солью"""
        salt = bcrypt.gensalt()
        self.hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        self.password_changed_at = datetime.now(timezone.utc)
    
    def verify_password(self, password: str) -> bool:
        """Проверка пароля"""
        return bcrypt.checkpw(password.encode('utf-8'), self.hashed_password.encode('utf-8'))
    
    def is_locked(self) -> bool:
        """Проверка, заблокирован ли аккаунт"""
        if self.locked_until and self.locked_until > datetime.now(timezone.utc):
            return True
        return False
    
    def increment_failed_attempts(self):
        """Увеличение счетчика неудачных попыток входа"""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            # Блокируем на 30 минут после 5 неудачных попыток
            self.locked_until = datetime.now(timezone.utc).replace(
                tzinfo=timezone.utc
            ) + datetime.timedelta(minutes=30)
    
    def reset_failed_attempts(self):
        """Сброс счетчика неудачных попыток"""
        self.failed_login_attempts = 0
        self.locked_until = None
    
    def record_login(self):
        """Запись успешного входа"""
        self.last_login = datetime.now(timezone.utc)
        self.reset_failed_attempts()
    
    def has_complete_profile(self) -> bool:
        """Проверка, заполнен ли профиль полностью для создания QR"""
        required_fields = [
            self.organization_name,
            self.bank_account,
            self.bank_name,
            self.bank_code
        ]
        return all(field is not None and field.strip() != "" for field in required_fields)
    
    def get_qr_default_settings(self) -> dict:
        """Получение настроек по умолчанию для QR-кодов"""
        default_settings = {
            "default_currency": "KGS",
            "default_expires_hours": 24,
            "allow_variable_amount": True,
            "max_amount": 100000.0
        }
        
        if self.qr_settings:
            # Обновляем настройки по умолчанию сохраненными
            if isinstance(self.qr_settings, dict):
                default_settings.update(self.qr_settings)
        
        return default_settings


