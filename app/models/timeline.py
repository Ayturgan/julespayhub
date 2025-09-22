from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    # Связи-идентификаторы (одного из них достаточно для выборки)
    transaction_id = Column(String(100), index=True, nullable=True)
    payment_token = Column(String(255), index=True, nullable=True)
    refund_token = Column(String(255), index=True, nullable=True)  # Токен возврата

    # Семантика события
    event_type = Column(String(50), index=True)  # qr_created, info_requested, webhook_received, webhook_success, webhook_failed, transaction_recorded, billing_recorded, pending_timeout
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    actor = Column(String(50), nullable=True)   # system, bank, merchant, payer
    source = Column(String(50), nullable=True)  # api, webhook, service
    status = Column(String(30), nullable=True)  # success, failed, pending, info
    metadata_json = Column(Text, nullable=True) # произвольные данные

    # Время
    timestamp_utc = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_timeline_events_token_time', 'payment_token', 'timestamp_utc'),
        Index('ix_timeline_events_tx_time', 'transaction_id', 'timestamp_utc'),
        Index('ix_timeline_events_refund_time', 'refund_token', 'timestamp_utc'),
    )


