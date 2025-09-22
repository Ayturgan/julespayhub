from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.payment import RateLimitRecord
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class RateLimitService:
    """Сервис для rate limiting и throttling"""
    
    # Конфигурация лимитов для разных эндпоинтов
    ENDPOINT_LIMITS = {
        "payment-info": settings.RATE_LIMIT_PAYMENT_INFO_PER_MINUTE,
        "webhook": settings.RATE_LIMIT_WEBHOOK_PER_MINUTE,
        "create-payment": settings.RATE_LIMIT_QR_CREATION_PER_MINUTE,
        "default": settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    }
    
    @staticmethod
    def check_rate_limit(
        db: Session,
        ip_address: str,
        endpoint: str,
        bank_code: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[bool, Dict]:
        """
        Проверка rate limit для запроса
        
        Args:
            db: Сессия базы данных
            ip_address: IP адрес клиента
            endpoint: Название эндпоинта
            bank_code: Код банка (если известен)
            user_agent: User-Agent клиента
            
        Returns:
            Tuple[bool, dict]: (allowed, info)
                allowed: True если запрос разрешен
                info: Информация о лимитах и статусе
        """
        
        now = datetime.now()
        window_start = now - timedelta(minutes=1)
        
        # Получаем лимит для эндпоинта
        limit = RateLimitService.ENDPOINT_LIMITS.get(
            endpoint, 
            RateLimitService.ENDPOINT_LIMITS["default"]
        )
        
        # Ищем существующую запись для IP + endpoint
        rate_record = db.query(RateLimitRecord).filter(
            and_(
                RateLimitRecord.ip_address == ip_address,
                RateLimitRecord.endpoint == endpoint,
                or_(
                    RateLimitRecord.bank_code == bank_code,
                    RateLimitRecord.bank_code.is_(None)
                )
            )
        ).first()
        
        # Проверяем блокировку
        if rate_record and rate_record.is_blocked:
            if rate_record.blocked_until and now < rate_record.blocked_until:
                return False, {
                    "error": "IP blocked due to rate limit violation",
                    "blocked_until": rate_record.blocked_until.isoformat(),
                    "retry_after": int((rate_record.blocked_until - now).total_seconds())
                }
            else:
                # Снимаем блокировку
                rate_record.is_blocked = False
                rate_record.blocked_until = None
                db.commit()
        
        # Если записи нет или окно истекло - создаем новую
        if not rate_record or rate_record.window_start < window_start:
            if rate_record:
                # Обновляем существующую запись
                rate_record.request_count = 1
                rate_record.window_start = now
                rate_record.last_request = now
                rate_record.user_agent = user_agent
                if bank_code:
                    rate_record.bank_code = bank_code
            else:
                # Создаем новую запись
                rate_record = RateLimitRecord(
                    ip_address=ip_address,
                    bank_code=bank_code,
                    endpoint=endpoint,
                    request_count=1,
                    window_start=now,
                    last_request=now,
                    user_agent=user_agent
                )
                db.add(rate_record)
            
            db.commit()
            
            return True, {
                "allowed": True,
                "limit": limit,
                "remaining": limit - 1,
                "reset_time": (now + timedelta(minutes=1)).isoformat()
            }
        
        # Увеличиваем счетчик
        rate_record.request_count += 1
        rate_record.last_request = now
        rate_record.user_agent = user_agent
        
        # Проверяем превышение лимита
        if rate_record.request_count > limit:
            # Блокируем IP
            rate_record.is_blocked = True
            rate_record.blocked_until = now + timedelta(
                minutes=settings.RATE_LIMIT_BLOCK_DURATION_MINUTES
            )
            
            db.commit()
            
            logger.warning(
                f"Rate limit exceeded for IP {ip_address} on endpoint {endpoint}. "
                f"Blocked until {rate_record.blocked_until}"
            )
            
            return False, {
                "error": "Rate limit exceeded",
                "limit": limit,
                "requests_made": rate_record.request_count,
                "blocked_until": rate_record.blocked_until.isoformat(),
                "retry_after": settings.RATE_LIMIT_BLOCK_DURATION_MINUTES * 60
            }
        
        db.commit()
        
        return True, {
            "allowed": True,
            "limit": limit,
            "remaining": limit - rate_record.request_count,
            "reset_time": (rate_record.window_start + timedelta(minutes=1)).isoformat(),
            "requests_made": rate_record.request_count
        }
    
    @staticmethod
    def get_rate_limit_stats(
        db: Session,
        ip_address: Optional[str] = None,
        endpoint: Optional[str] = None,
        bank_code: Optional[str] = None,
        hours: int = 24
    ) -> list:
        """
        Получение статистики rate limiting
        
        Args:
            db: Сессия базы данных
            ip_address: Фильтр по IP
            endpoint: Фильтр по эндпоинту
            bank_code: Фильтр по банку
            hours: За сколько часов показать статистику
            
        Returns:
            list: Список записей rate limiting
        """
        
        since = datetime.now() - timedelta(hours=hours)
        
        query = db.query(RateLimitRecord).filter(
            RateLimitRecord.created_at >= since
        )
        
        if ip_address:
            query = query.filter(RateLimitRecord.ip_address == ip_address)
        
        if endpoint:
            query = query.filter(RateLimitRecord.endpoint == endpoint)
        
        if bank_code:
            query = query.filter(RateLimitRecord.bank_code == bank_code)
        
        return query.order_by(RateLimitRecord.created_at.desc()).limit(1000).all()
    
    @staticmethod
    def cleanup_old_records(db: Session, days: int = 7):
        """
        Очистка старых записей rate limiting
        
        Args:
            db: Сессия базы данных
            days: Удалить записи старше N дней
        """
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        deleted_count = db.query(RateLimitRecord).filter(
            and_(
                RateLimitRecord.created_at < cutoff_date,
                RateLimitRecord.is_blocked == False
            )
        ).delete()
        
        db.commit()
        
        logger.info(f"Cleaned up {deleted_count} old rate limit records")
        return deleted_count
    
    @staticmethod
    def unblock_ip(db: Session, ip_address: str, endpoint: Optional[str] = None) -> int:
        """
        Разблокировка IP адреса
        
        Args:
            db: Сессия базы данных
            ip_address: IP для разблокировки
            endpoint: Конкретный эндпоинт (опционально)
            
        Returns:
            int: Количество разблокированных записей
        """
        
        query = db.query(RateLimitRecord).filter(
            and_(
                RateLimitRecord.ip_address == ip_address,
                RateLimitRecord.is_blocked == True
            )
        )
        
        if endpoint:
            query = query.filter(RateLimitRecord.endpoint == endpoint)
        
        records = query.all()
        
        for record in records:
            record.is_blocked = False
            record.blocked_until = None
        
        db.commit()
        
        logger.info(f"Unblocked {len(records)} records for IP {ip_address}")
        return len(records)
