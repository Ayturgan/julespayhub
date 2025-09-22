from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp_utc = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    event_type = Column(String(50), index=True)      # api_request, security_alert, db_error, admin_action
    event_source = Column(String(100), index=True)   # payment_info_api, webhook_handler, admin_panel, route path

    actor_id = Column(String(100), index=True, nullable=True)
    actor_type = Column(String(30), index=True, nullable=True)  # bank, admin, system

    status = Column(String(20), index=True)          # success, failure, warning
    ip_address = Column(String(45), index=True, nullable=True)

    details_json = Column(Text, nullable=True)       # Полные детали (JSON)

    __table_args__ = (
        Index('ix_audit_logs_time_type', 'timestamp_utc', 'event_type'),
        Index('ix_audit_logs_actor', 'actor_type', 'actor_id'),
    )


