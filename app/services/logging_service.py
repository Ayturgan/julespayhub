import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import Request, Response
from sqlalchemy.orm import Session
from app.models.payment import PaymentLog
from app.models.audit import AuditLog
import logging

logger = logging.getLogger(__name__)

class EnhancedLoggingService:
    """Сервис для расширенного логирования API запросов"""
    
    # Заголовки, которые не нужно логировать (безопасность)
    SENSITIVE_HEADERS = {
        'authorization', 'x-signature', 'cookie', 'set-cookie'
    }
    
    @staticmethod
    def create_log_entry(
        db: Session,
        request: Request,
        response: Optional[Response] = None,
        token: Optional[str] = None,
        bank_code: Optional[str] = None,
        request_type: Optional[str] = None,
        error_message: Optional[str] = None,
        rate_limited: bool = False,
        start_time: Optional[float] = None
    ) -> PaymentLog:
        """
        Создание записи в логе
        
        Args:
            db: Сессия базы данных
            request: FastAPI Request объект
            response: FastAPI Response объект (опционально)
            token: Токен платежа
            bank_code: Код банка
            request_type: Тип запроса
            error_message: Сообщение об ошибке
            rate_limited: Был ли запрос ограничен
            start_time: Время начала запроса (для расчета длительности)
            
        Returns:
            PaymentLog: Созданная запись лога
        """
        
        # Вычисляем длительность запроса
        duration_ms = None
        if start_time:
            duration_ms = int((time.time() - start_time) * 1000)
        
        # Собираем заголовки запроса (исключая чувствительные)
        request_headers = EnhancedLoggingService._sanitize_headers(
            dict(request.headers)
        )
        
        # Получаем тело запроса если есть
        request_body = getattr(request.state, 'body', None)
        
        # Собираем заголовки ответа
        response_headers = {}
        response_body = None
        response_status = 500  # По умолчанию ошибка если response не передан
        
        if response:
            response_status = response.status_code
            response_headers = EnhancedLoggingService._sanitize_headers(
                dict(response.headers)
            )
            # response_body можно получить только в middleware
        
        # Определяем тип запроса автоматически если не передан
        if not request_type:
            request_type = EnhancedLoggingService._determine_request_type(
                request.url.path
            )
        
        # Создаем запись лога
        log_entry = PaymentLog(
            token=token,
            bank_code=bank_code,
            request_type=request_type,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent", ""),
            http_method=request.method,
            endpoint=str(request.url.path),
            request_headers=json.dumps(request_headers),
            request_body=request_body,
            response_status=response_status,
            response_body=response_body,
            response_headers=json.dumps(response_headers),
            request_duration_ms=duration_ms,
            error_message=error_message,
            rate_limited=rate_limited
        )
        
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        
        # Дополнительное логирование в файл для критических ошибок
        if error_message or response_status >= 400:
            logger.warning(
                f"API Error: {request.method} {request.url.path} - "
                f"Status: {response_status}, IP: {request.client.host}, "
                f"Bank: {bank_code}, Error: {error_message}"
            )
        
        return log_entry
    
    @staticmethod
    def _sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
        """
        Удаление чувствительных заголовков из логов
        
        Args:
            headers: Словарь заголовков
            
        Returns:
            Dict[str, str]: Очищенные заголовки
        """
        sanitized = {}
        
        for key, value in headers.items():
            key_lower = key.lower()
            
            if key_lower in EnhancedLoggingService.SENSITIVE_HEADERS:
                sanitized[key] = "[REDACTED]"
            elif key_lower.startswith('x-') and 'secret' in key_lower:
                sanitized[key] = "[REDACTED]"
            else:
                # Ограничиваем длину значений заголовков
                sanitized[key] = value[:500] if len(value) > 500 else value
        
        return sanitized
    
    @staticmethod
    def _determine_request_type(path: str) -> str:
        """
        Автоматическое определение типа запроса по пути
        
        Args:
            path: Путь запроса
            
        Returns:
            str: Тип запроса
        """
        if 'payment-info' in path:
            return 'payment_info'
        elif 'payment-status' in path:
            return 'webhook'
        elif 'create-payment' in path:
            return 'create_payment'
        elif 'banks' in path:
            return 'bank_management'
        elif 'admin' in path:
            return 'admin'
        else:
            return 'other'
    
    @staticmethod
    def get_logs_by_criteria(
        db: Session,
        ip_address: Optional[str] = None,
        bank_code: Optional[str] = None,
        request_type: Optional[str] = None,
        status_code: Optional[int] = None,
        has_error: Optional[bool] = None,
        rate_limited: Optional[bool] = None,
        hours: int = 24,
        limit: int = 1000
    ) -> List[PaymentLog]:
        """
        Получение логов по критериям
        
        Args:
            db: Сессия базы данных
            ip_address: Фильтр по IP
            bank_code: Фильтр по банку
            request_type: Фильтр по типу запроса
            status_code: Фильтр по коду ответа
            has_error: Только запросы с ошибками
            rate_limited: Только ограниченные запросы
            hours: За сколько часов
            limit: Максимум записей
            
        Returns:
            List[PaymentLog]: Список логов
        """
        from datetime import timedelta
        
        since = datetime.now() - timedelta(hours=hours)
        
        query = db.query(PaymentLog).filter(
            PaymentLog.created_at >= since
        )
        
        if ip_address:
            query = query.filter(PaymentLog.ip_address == ip_address)
        
        if bank_code:
            query = query.filter(PaymentLog.bank_code == bank_code)
        
        if request_type:
            query = query.filter(PaymentLog.request_type == request_type)
        
        if status_code:
            query = query.filter(PaymentLog.response_status == status_code)
        
        if has_error is not None:
            if has_error:
                query = query.filter(PaymentLog.error_message.isnot(None))
            else:
                query = query.filter(PaymentLog.error_message.is_(None))
        
        if rate_limited is not None:
            query = query.filter(PaymentLog.rate_limited == rate_limited)
        
        return query.order_by(PaymentLog.created_at.desc()).limit(limit).all()
    
    @staticmethod
    def get_error_summary(db: Session, hours: int = 24) -> Dict[str, Any]:
        """
        Получение сводки по ошибкам
        
        Args:
            db: Сессия базы данных
            hours: За сколько часов
            
        Returns:
            Dict[str, Any]: Сводка по ошибкам
        """
        from datetime import timedelta
        from sqlalchemy import func, and_
        
        since = datetime.now() - timedelta(hours=hours)
        
        # Общая статистика
        total_requests = db.query(PaymentLog).filter(
            PaymentLog.created_at >= since
        ).count()
        
        error_requests = db.query(PaymentLog).filter(
            and_(
                PaymentLog.created_at >= since,
                PaymentLog.response_status >= 400
            )
        ).count()
        
        rate_limited_requests = db.query(PaymentLog).filter(
            and_(
                PaymentLog.created_at >= since,
                PaymentLog.rate_limited == True
            )
        ).count()
        
        # Топ ошибок по статус кодам
        status_codes = db.query(
            PaymentLog.response_status,
            func.count(PaymentLog.id).label('count')
        ).filter(
            and_(
                PaymentLog.created_at >= since,
                PaymentLog.response_status >= 400
            )
        ).group_by(PaymentLog.response_status).all()
        
        # Топ IP с ошибками
        error_ips = db.query(
            PaymentLog.ip_address,
            func.count(PaymentLog.id).label('count')
        ).filter(
            and_(
                PaymentLog.created_at >= since,
                PaymentLog.response_status >= 400
            )
        ).group_by(PaymentLog.ip_address).order_by(
            func.count(PaymentLog.id).desc()
        ).limit(10).all()
        
        return {
            "period_hours": hours,
            "total_requests": total_requests,
            "error_requests": error_requests,
            "rate_limited_requests": rate_limited_requests,
            "error_rate": round(error_requests / max(total_requests, 1) * 100, 2),
            "status_code_distribution": [
                {"status_code": sc[0], "count": sc[1]} for sc in status_codes
            ],
            "top_error_ips": [
                {"ip_address": ip[0], "error_count": ip[1]} for ip in error_ips
            ]
        }
    
    @staticmethod
    def cleanup_old_logs(db: Session, days: int = 30) -> int:
        """
        Очистка старых логов
        
        Args:
            db: Сессия базы данных
            days: Удалить логи старше N дней
            
        Returns:
            int: Количество удаленных записей
        """
        from datetime import timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        deleted_count = db.query(PaymentLog).filter(
            PaymentLog.created_at < cutoff_date
        ).delete()
        
        db.commit()
        
        logger.info(f"Cleaned up {deleted_count} old log records")
        return deleted_count


class AuditLoggingService:
    """Единый сервис для записи событий аудита"""

    @staticmethod
    def log_event(
        db: Session,
        *,
        event_type: str,
        event_source: str,
        status: str,
        actor_type: str = None,
        actor_id: str = None,
        ip_address: str = None,
        details: dict | None = None,
    ) -> AuditLog:
        import json as _json
        entry = AuditLog(
            event_type=event_type,
            event_source=event_source,
            status=status,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            ip_address=ip_address,
            details_json=_json.dumps(details, ensure_ascii=False) if details else None,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
