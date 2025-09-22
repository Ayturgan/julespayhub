from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class Merchant(Base):
    """Модель для продавцов (юридические лица/ИП)"""
    __tablename__ = "merchants"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Основная информация
    name = Column(String(255), nullable=False)
    legal_name = Column(String(500), nullable=False)  # Полное юридическое название
    inn = Column(String(14), unique=True, index=True, nullable=False)  # ИНН
    kpp = Column(String(9), nullable=True)  # КПП (для юр. лиц)
    
    # Контактная информация
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(Text, nullable=False)
    
    # Банковская информация
    bank_account = Column(String(20), nullable=False)
    bank_name = Column(String(255), nullable=False)
    bank_bik = Column(String(9), nullable=False)
    
    # Аутентификация
    api_key = Column(String(255), unique=True, index=True, nullable=False)
    api_secret = Column(String(500), nullable=False)  # HMAC секрет
    hashed_password = Column(String(255), nullable=True)
    
    # Статус и настройки
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # Верификация документов
    verification_date = Column(DateTime(timezone=True), nullable=True)
    
    # Лимиты и ограничения
    daily_limit = Column(Float, default=1000000.0)  # Дневной лимит в KGS
    monthly_limit = Column(Float, default=30000000.0)  # Месячный лимит в KGS
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_activity = Column(DateTime(timezone=True), nullable=True)
    
    # Связи
    qr_codes = relationship("QRCode", back_populates="merchant")
    payments = relationship("MerchantPayment", back_populates="merchant")
    settings = relationship("MerchantSettings", back_populates="merchant", uselist=False)
    # Связь с торговыми точками
    outlets = relationship("TradingPoint", back_populates="merchant")
    
    __table_args__ = (
        {'comment': 'Продавцы - юридические лица и ИП'}
    )

class QRCode(Base):
    """Модель для QR-кодов, созданных продавцами"""
    __tablename__ = "qr_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связь с продавцом
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    outlet_id = Column(Integer, ForeignKey("trading_points.id"), nullable=True)
    
    # Основная информация
    name = Column(String(255), nullable=False)  # Название QR-кода
    description = Column(Text, nullable=True)  # Описание
    
    # Платежная информация
    amount = Column(Float, nullable=True)  # Фиксированная сумма (null для ручного ввода)
    currency = Column(String(3), default="KGS")
    
    # QR-код данные
    qr_token = Column(String(255), unique=True, index=True, nullable=False)
    qr_url = Column(String(500), nullable=False)  # URL для сканирования
    qr_image_path = Column(String(500), nullable=True)  # Путь к изображению QR
    qr_image_base64 = Column(Text, nullable=True)  # Base64 изображение QR-кода
    
    # Статус и ограничения
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Срок действия
    max_uses = Column(Integer, nullable=True)  # Максимальное количество использований
    current_uses = Column(Integer, default=0)  # Текущее количество использований
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Связи
    merchant = relationship("Merchant", back_populates="qr_codes")
    payments = relationship("MerchantPayment", back_populates="qr_code")
    outlet = relationship("TradingPoint")
    
    __table_args__ = (
        {'comment': 'QR-коды, созданные продавцами'}
    )

class MerchantPayment(Base):
    """Модель для платежей конкретного продавца"""
    __tablename__ = "merchant_payments"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связи
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    qr_code_id = Column(Integer, ForeignKey("qr_codes.id"), nullable=True)
    outlet_id = Column(Integer, ForeignKey("trading_points.id"), nullable=True)
    
    # Платежная информация
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="KGS")
    status = Column(String(20), nullable=False)  # pending, completed, failed, cancelled
    
    # Информация о плательщике
    payer_phone = Column(String(20), nullable=True)
    payer_bank_code = Column(String(20), nullable=True)
    sender_account = Column(String(50), nullable=True)  # Счет плательщика
    
    # Транзакционная информация
    transaction_id = Column(String(100), unique=True, index=True, nullable=True)
    bank_transaction_id = Column(String(100), nullable=True)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Дополнительная информация
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Информация о возвратах
    refund_status = Column(String(20), default="NONE", index=True)  # NONE, PARTIAL, FULL
    total_refunded_amount = Column(Float, default=0.0)  # Общая сумма возвратов
    
    # Связи
    merchant = relationship("Merchant", back_populates="payments")
    qr_code = relationship("QRCode", back_populates="payments")
    outlet = relationship("TradingPoint")
    
    __table_args__ = (
        {'comment': 'Платежи продавцов'}
    )

class MerchantSettings(Base):
    """Настройки продавца"""
    __tablename__ = "merchant_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связь с продавцом
    merchant_id = Column(Integer, ForeignKey("merchants.id"), unique=True, nullable=False)
    
    # Уведомления
    email_notifications = Column(Boolean, default=True)
    sms_notifications = Column(Boolean, default=False)
    webhook_url = Column(String(500), nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    
    # Настройки QR-кодов
    default_currency = Column(String(3), default="KGS")
    qr_code_expiry_hours = Column(Integer, default=24)
    auto_generate_qr_images = Column(Boolean, default=True)
    
    # Настройки отчетов
    daily_reports = Column(Boolean, default=False)
    weekly_reports = Column(Boolean, default=True)
    monthly_reports = Column(Boolean, default=True)
    
    # Настройки безопасности
    ip_whitelist = Column(Text, nullable=True)  # JSON список разрешенных IP
    require_webhook_signature = Column(Boolean, default=True)
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Связи
    merchant = relationship("Merchant", back_populates="settings")
class TradingPoint(Base):
    """Торговая точка/филиал продавца"""
    __tablename__ = "trading_points"
    id = Column(Integer, primary_key=True, index=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="ACTIVE")  # ACTIVE, ARCHIVED
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant = relationship("Merchant", back_populates="outlets")
    
    __table_args__ = (
        {'comment': 'Торговые точки продавцов'}
    )
