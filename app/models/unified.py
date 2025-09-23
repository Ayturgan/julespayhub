from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey,
    Enum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.schemas.unified_payment import PaymentStatus


class UnifiedQRCode(Base):
    """Единая модель для QR-кодов, созданных как продавцами, так и администраторами."""
    __tablename__ = "unified_qrcodes"

    id = Column(Integer, primary_key=True, index=True)

    # Владелец QR-кода (либо продавец, либо админ)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)

    # Основная информация
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Платежная информация
    amount = Column(Float, nullable=True)  # null для динамических QR
    currency = Column(String(3), default="KGS")

    # Данные QR-кода
    qr_token = Column(String(255), unique=True, index=True, nullable=False)
    qr_url = Column(String(500), nullable=False)
    qr_image_base64 = Column(Text, nullable=True)

    # Статус и ограничения
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, default=0)

    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Связи
    merchant = relationship("Merchant")
    admin = relationship("Admin")
    payments = relationship("UnifiedPayment", back_populates="qr_code")

    __table_args__ = (
        {'comment': 'Единая таблица для всех QR-кодов в системе'}
    )


class UnifiedPayment(Base):
    """Единая модель для всех видов платежей и транзакций."""
    __tablename__ = "unified_payments"

    id = Column(Integer, primary_key=True, index=True)

    # Владелец платежа (либо продавец, либо админ)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True, index=True)

    # Связь с QR-кодом
    qr_code_id = Column(Integer, ForeignKey("unified_qrcodes.id"), nullable=True, index=True)

    # Основная информация о платеже
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="KGS")
    description = Column(Text, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True)

    # Информация о получателе
    receiver_name = Column(String(255), nullable=False)
    receiver_account = Column(String(50), nullable=False)
    receiver_bank_code = Column(String(20), nullable=False)

    # Информация о плательщике
    payer_phone = Column(String(20), nullable=True)
    payer_bank_code = Column(String(20), nullable=True, index=True)
    sender_account = Column(String(50), nullable=True)

    # Транзакционная информация
    transaction_id = Column(String(100), unique=True, index=True, nullable=True)
    payment_reference = Column(String(100), unique=True, nullable=False)

    # Статус оплаты
    is_paid = Column(Boolean, default=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Поля для двухфазных транзакций (из PaymentRequest)
    prepare_started_at = Column(DateTime(timezone=True), nullable=True)
    prepare_completed_at = Column(DateTime(timezone=True), nullable=True)
    commit_started_at = Column(DateTime(timezone=True), nullable=True)
    commit_completed_at = Column(DateTime(timezone=True), nullable=True)
    abort_started_at = Column(DateTime(timezone=True), nullable=True)
    abort_completed_at = Column(DateTime(timezone=True), nullable=True)

    sender_prepare_result = Column(Text, nullable=True)
    receiver_prepare_result = Column(Text, nullable=True)
    two_phase_metadata = Column(Text, nullable=True)

    # Дополнительная информация (из MerchantPayment)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # Информация о возвратах
    refund_status = Column(String(20), default="NONE", index=True)
    total_refunded_amount = Column(Float, default=0.0)

    # Связи
    merchant = relationship("Merchant")
    admin = relationship("Admin")
    qr_code = relationship("UnifiedQRCode", back_populates="payments")

    __table_args__ = (
        {'comment': 'Единая таблица для всех платежей и транзакций'}
    )
