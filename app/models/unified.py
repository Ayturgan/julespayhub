from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Index, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import TransactionStatus


class UnifiedQRCode(Base):
    __tablename__ = "unified_qrcodes"

    id = Column(Integer, primary_key=True, index=True)

    # Владелец QR: либо merchant, либо admin
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    outlet_id = Column(Integer, ForeignKey("trading_points.id"), nullable=True)

    # Основная информация
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Платежная информация для статических/динамических QR
    amount = Column(Float, nullable=True)
    currency = Column(String(3), default="KGS")

    # Данные QR
    qr_token = Column(String(255), unique=True, index=True, nullable=False)
    qr_url = Column(String(500), nullable=False)

    # Состояние
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, default=0)

    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Связи
    merchant = relationship("Merchant", back_populates="qr_codes")
    admin = relationship("Admin", back_populates="qr_codes")
    payments = relationship("UnifiedPayment", back_populates="qr_code")

    __table_args__ = (
        Index("ix_unified_qrcodes_owner", "merchant_id", "admin_id"),
        {"comment": "Унифицированные QR-коды (для продавцов и админов)"},
    )


class UnifiedPayment(Base):
    __tablename__ = "unified_payments"

    id = Column(Integer, primary_key=True, index=True)

    # Владелец платежа: либо merchant, либо admin
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)

    # Связь с QR-кодом
    qr_code_id = Column(Integer, ForeignKey("unified_qrcodes.id"), nullable=True)
    outlet_id = Column(Integer, ForeignKey("trading_points.id"), nullable=True)

    # Основные поля
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="KGS")
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Совместимость/идентификаторы из старых моделей
    token = Column(String(255), index=True, nullable=True)
    payment_reference = Column(String(100), index=True, nullable=True)

    # Получатель
    receiver_name = Column(String(255), nullable=False)
    receiver_account = Column(String(50), nullable=False)
    receiver_bank_code = Column(String(20), nullable=False)

    # Плательщик
    payer_phone = Column(String(20), nullable=True)
    payer_bank_code = Column(String(20), nullable=True)
    sender_bank_code = Column(String(20), nullable=True)
    sender_account = Column(String(50), nullable=True)

    # Двухфазная транзакция / идемпотентность
    transaction_id = Column(String(100), unique=True, index=True, nullable=True)
    is_paid = Column(Boolean, default=False)
    paid_amount = Column(Float, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Тайминги 2PC
    prepare_started_at = Column(DateTime(timezone=True), nullable=True)
    prepare_completed_at = Column(DateTime(timezone=True), nullable=True)
    commit_started_at = Column(DateTime(timezone=True), nullable=True)
    commit_completed_at = Column(DateTime(timezone=True), nullable=True)
    abort_started_at = Column(DateTime(timezone=True), nullable=True)
    abort_completed_at = Column(DateTime(timezone=True), nullable=True)

    # Результаты/метаданные 2PC
    sender_prepare_result = Column(Text, nullable=True)
    receiver_prepare_result = Column(Text, nullable=True)
    two_phase_metadata = Column(Text, nullable=True)

    # Прочее из PaymentRequest
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_used = Column(Boolean, default=False)

    # Ошибки
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Связи
    merchant = relationship("Merchant", back_populates="payments")
    admin = relationship("Admin", back_populates="payments")
    qr_code = relationship("UnifiedQRCode", back_populates="payments")

    __table_args__ = (
        Index("ix_unified_payments_owner", "merchant_id", "admin_id"),
        Index("ix_unified_payments_qr", "qr_code_id"),
        {"comment": "Унифицированные платежи (2PC/простые)"},
    )

