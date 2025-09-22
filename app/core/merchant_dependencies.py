"""
Зависимости для аутентификации и авторизации продавцов
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.merchant import Merchant
from typing import Optional

# Настраиваем Bearer схему для токенов
security = HTTPBearer()


async def get_current_merchant(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Merchant:
    """
    Извлекает текущего аутентифицированного продавца по Bearer токену
    
    Args:
        credentials: Bearer токен из заголовка Authorization
        db: Сессия базы данных
        
    Returns:
        Merchant: Объект продавца
        
    Raises:
        HTTPException: Если токен недействителен или продавец не найден
    """
    token = credentials.credentials
    
    # Добавляем отладочную информацию
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Attempting authentication with token: {token[:20]}...")
    
    # Ищем продавца по API ключу (у продавцов токен = api_key)
    merchant = db.query(Merchant).filter(
        Merchant.api_key == token,
        Merchant.is_active == True
    ).first()
    
    if not merchant:
        logger.warning(f"Authentication failed for token: {token[:20]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"Authentication successful for merchant: {merchant.email}")
    
    # Обновляем время последней активности
    from datetime import datetime, timezone
    merchant.last_activity = datetime.now(timezone.utc)
    db.commit()
    
    return merchant


async def get_verified_merchant(
    current_merchant: Merchant = Depends(get_current_merchant)
) -> Merchant:
    """
    Проверяет, что продавец верифицирован
    
    Args:
        current_merchant: Текущий аутентифицированный продавец
        
    Returns:
        Merchant: Верифицированный продавец
        
    Raises:
        HTTPException: Если продавец не верифицирован
    """
    if not current_merchant.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Merchant account is not verified. Please contact support.",
        )
    
    return current_merchant


async def get_merchant_for_payments(
    current_merchant: Merchant = Depends(get_current_merchant)
) -> Merchant:
    """
    Зависимость для операций с платежами.
    Дополнительные проверки могут быть добавлены в будущем.
    """
    return current_merchant


async def get_merchant_for_reports(
    current_merchant: Merchant = Depends(get_current_merchant)
) -> Merchant:
    """
    Зависимость для генерации отчетов.
    Дополнительные проверки могут быть добавлены в будущем.
    """
    return current_merchant


async def get_merchant_for_settings(
    current_merchant: Merchant = Depends(get_current_merchant)
) -> Merchant:
    """
    Зависимость для изменения настроек.
    Дополнительные проверки могут быть добавлены в будущем.
    """
    return current_merchant