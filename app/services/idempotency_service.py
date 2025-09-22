"""
Сервис для обеспечения идемпотентности запросов
Предотвращает дублирование операций при повторных запросах
"""

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
import json
import logging

from app.models.payment import IdempotencyKey
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity

logger = logging.getLogger(__name__)

class IdempotencyService:
    """Сервис для управления идемпотентностью"""
    
    def __init__(self):
        self.key_expiry_hours = 24  # Ключи истекают через 24 часа
        
    def check_idempotency_key(
        self, 
        db: Session, 
        idempotency_key: str,
        payment_token: Optional[str] = None,
        bank_code: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Проверяет существование ключа идемпотентности
        
        Args:
            db: Сессия базы данных
            idempotency_key: Ключ идемпотентности
            payment_token: Токен платежа (опционально)
            bank_code: Код банка (опционально)
            
        Returns:
            None если ключ не найден, иначе данные предыдущего запроса
        """
        
        # Очищаем истекшие ключи
        self._cleanup_expired_keys(db)
        
        # Ищем существующий ключ
        existing_key = db.query(IdempotencyKey).filter(
            IdempotencyKey.idempotency_key == idempotency_key
        ).first()
        
        if existing_key:
            logger.info(f"🔄 Найден существующий ключ идемпотентности: {idempotency_key[:20]}...")
            
            # Возвращаем данные предыдущего запроса
            if existing_key.response_data:
                try:
                    response_data = json.loads(existing_key.response_data)
                    return {
                        "response_data": response_data,
                        "response_status": existing_key.response_status,
                        "success": existing_key.success,
                        "created_at": existing_key.created_at
                    }
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Неверный JSON в ответе идемпотентности: {idempotency_key}")
            
            return {
                "response_data": None,
                "response_status": existing_key.response_status,
                "success": existing_key.success,
                "created_at": existing_key.created_at
            }
        
        return None
    
    def create_idempotency_key(
        self,
        db: Session,
        idempotency_key: str,
        payment_token: Optional[str] = None,
        transaction_id: Optional[str] = None,
        bank_code: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> IdempotencyKey:
        """
        Создает новый ключ идемпотентности
        
        Args:
            db: Сессия базы данных
            idempotency_key: Ключ идемпотентности
            payment_token: Токен платежа
            transaction_id: ID транзакции
            bank_code: Код банка
            ip_address: IP адрес
            user_agent: User-Agent
            
        Returns:
            Созданный объект IdempotencyKey
        """
        
        expires_at = datetime.now() + timedelta(hours=self.key_expiry_hours)
        
        idempotency_record = IdempotencyKey(
            idempotency_key=idempotency_key,
            payment_token=payment_token,
            transaction_id=transaction_id,
            bank_code=bank_code,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        
        db.add(idempotency_record)
        db.commit()
        db.refresh(idempotency_record)
        
        logger.info(f"✅ Создан ключ идемпотентности: {idempotency_key[:20]}...")
        
        return idempotency_record
    
    def update_idempotency_result(
        self,
        db: Session,
        idempotency_key: str,
        response_data: Dict[str, Any],
        response_status: int,
        success: bool
    ) -> None:
        """
        Обновляет результат обработки для ключа идемпотентности
        
        Args:
            db: Сессия базы данных
            idempotency_key: Ключ идемпотентности
            response_data: Данные ответа
            response_status: HTTP статус ответа
            success: Успешность операции
        """
        
        idempotency_record = db.query(IdempotencyKey).filter(
            IdempotencyKey.idempotency_key == idempotency_key
        ).first()
        
        if idempotency_record:
            idempotency_record.response_data = json.dumps(response_data)
            idempotency_record.response_status = response_status
            idempotency_record.success = success
            
            db.commit()
            
            logger.info(f"✅ Обновлен результат идемпотентности: {idempotency_key[:20]}...")
        else:
            logger.warning(f"⚠️ Ключ идемпотентности не найден для обновления: {idempotency_key}")
    
    def _cleanup_expired_keys(self, db: Session) -> None:
        """Очищает истекшие ключи идемпотентности"""
        
        try:
            expired_count = db.query(IdempotencyKey).filter(
                IdempotencyKey.expires_at < datetime.now()
            ).delete()
            
            if expired_count > 0:
                db.commit()
                logger.info(f"🧹 Очищено {expired_count} истекших ключей идемпотентности")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при очистке истекших ключей: {e}")
            db.rollback()
    
    def validate_idempotency_key(self, idempotency_key: str) -> bool:
        """
        Валидирует формат ключа идемпотентности
        
        Args:
            idempotency_key: Ключ для валидации
            
        Returns:
            True если ключ валиден
        """
        
        if not idempotency_key:
            return False
        
        if len(idempotency_key) < 10 or len(idempotency_key) > 255:
            return False
        
        # Проверяем, что ключ содержит только безопасные символы
        import re
        safe_pattern = re.compile(r'^[a-zA-Z0-9_-]+$')
        
        return bool(safe_pattern.match(idempotency_key))

# Глобальный экземпляр сервиса
idempotency_service = IdempotencyService()
