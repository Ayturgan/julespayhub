import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database (SQLite для MVP)
    DATABASE_URL: str = "sqlite:///./qrpayhub.db"
    
    # Security
    SECRET_KEY: str = "mvp-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    
    # QR Code Settings
    QR_TOKEN_EXPIRE_MINUTES: int = 10
    BASE_URL: str = "https://qrpayhub.i7.kg"
    # BASE_URL: str = "https://s4rwokahc.localto.net"
    
    # Monitoring/Alerts
    MONITORING_ALERTS_COOLDOWN_SECONDS: int = 600
    MONITORING_ENABLE_SYSTEM_ALERTS: bool = True
    
    # Rate Limiting Settings
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100  # Общий лимит на IP
    RATE_LIMIT_PAYMENT_INFO_PER_MINUTE: int = 30  # Лимит для payment-info
    RATE_LIMIT_WEBHOOK_PER_MINUTE: int = 60  # Лимит для webhook
    RATE_LIMIT_QR_CREATION_PER_MINUTE: int = 10  # Лимит создания QR
    
    # Блокировка при превышении лимитов
    RATE_LIMIT_BLOCK_DURATION_MINUTES: int = 15
    
    class Config:
        env_file = ".env"

settings = Settings()

def get_base_url() -> str:
    """Централизованная функция для получения базового URL"""
    return settings.BASE_URL

def get_payment_url(token: str) -> str:
    """Генерация URL для оплаты"""
    base = get_base_url()
    return f"{base}/pay?token={token}" if base else f"/pay?token={token}"

def get_simulation_url(path: str = "") -> str:
    """Генерация URL для симуляции"""
    base = get_base_url()
    return f"{base}/simulation/{path}".rstrip("/") if base else f"/simulation/{path}".rstrip("/")

def get_bank_api_url() -> str:
    """Генерация URL для банковского API"""
    base = get_base_url()
    return f"{base}/simulation/bank-api" if base else "/simulation/bank-api"
