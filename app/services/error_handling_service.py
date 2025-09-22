from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List, Union
from enum import Enum
import traceback
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ErrorCode(Enum):
    """Стандартные коды ошибок системы"""
    
    # Аутентификация и авторизация (4xx)
    INVALID_TOKEN = "AUTH_001"
    EXPIRED_TOKEN = "AUTH_002"
    MISSING_AUTHORIZATION = "AUTH_003"
    INVALID_SIGNATURE = "AUTH_004"
    IP_NOT_ALLOWED = "AUTH_005"
    BANK_NOT_FOUND = "AUTH_006"
    BANK_INACTIVE = "AUTH_007"
    INVALID_CREDENTIALS = "AUTH_008"
    
    # Валидация данных (4xx)
    VALIDATION_ERROR = "VAL_001"
    MISSING_REQUIRED_FIELD = "VAL_002"
    INVALID_FORMAT = "VAL_003"
    INVALID_AMOUNT = "VAL_004"
    INVALID_CURRENCY = "VAL_005"
    INVALID_BANK_CODE = "VAL_006"
    INVALID_ACCOUNT = "VAL_007"
    INVALID_PHONE = "VAL_008"
    
    # Бизнес-логика (4xx)
    PAYMENT_NOT_FOUND = "BIZ_001"
    PAYMENT_EXPIRED = "BIZ_002"
    PAYMENT_ALREADY_PROCESSED = "BIZ_003"
    INSUFFICIENT_FUNDS = "BIZ_004"
    TRANSACTION_LIMIT_EXCEEDED = "BIZ_005"
    DUPLICATE_TRANSACTION = "BIZ_006"
    INVALID_PAYMENT_STATE = "BIZ_007"
    
    # Rate Limiting (4xx)
    RATE_LIMIT_EXCEEDED = "RATE_001"
    TOO_MANY_REQUESTS = "RATE_002"
    IP_BLOCKED = "RATE_003"
    SUSPICIOUS_ACTIVITY = "RATE_004"
    
    # QR и безопасность (4xx)
    INVALID_QR_CODE = "QR_001"
    QR_EXPIRED = "QR_002"
    QR_ALREADY_USED = "QR_003"
    QR_SECURITY_VIOLATION = "QR_004"
    SUSPICIOUS_QR_PATTERN = "QR_005"
    
    # Системные ошибки (5xx)
    INTERNAL_ERROR = "SYS_001"
    DATABASE_ERROR = "SYS_002"
    EXTERNAL_SERVICE_ERROR = "SYS_003"
    CONFIGURATION_ERROR = "SYS_004"
    NETWORK_ERROR = "SYS_005"
    TIMEOUT_ERROR = "SYS_006"
    
    # Webhook ошибки (4xx/5xx)
    WEBHOOK_INVALID_SIGNATURE = "WH_001"
    WEBHOOK_INVALID_PAYLOAD = "WH_002"
    WEBHOOK_PROCESSING_ERROR = "WH_003"
    WEBHOOK_TIMEOUT = "WH_004"

class ErrorSeverity(Enum):
    """Уровни серьезности ошибок"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class StandardError:
    """Стандартизированная ошибка системы"""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        user_message: Optional[str] = None,
        suggestions: Optional[List[str]] = None
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        self.severity = severity
        self.user_message = user_message or message
        self.suggestions = suggestions or []
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для JSON ответа"""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "user_message": self.user_message,
                "severity": self.severity.value,
                "timestamp": self.timestamp,
                "details": self.details,
                "suggestions": self.suggestions
            }
        }

class ErrorHandlingService:
    """Сервис для централизованной обработки ошибок"""
    
    # Маппинг кодов ошибок на HTTP статус коды
    ERROR_CODE_TO_HTTP_STATUS = {
        # Аутентификация - 401 Unauthorized
        ErrorCode.INVALID_TOKEN: 401,
        ErrorCode.EXPIRED_TOKEN: 401,
        ErrorCode.MISSING_AUTHORIZATION: 401,
        ErrorCode.INVALID_SIGNATURE: 401,
        ErrorCode.INVALID_CREDENTIALS: 401,
        
        # Авторизация - 403 Forbidden
        ErrorCode.IP_NOT_ALLOWED: 403,
        ErrorCode.BANK_INACTIVE: 403,
        
        # Не найдено - 404 Not Found
        ErrorCode.BANK_NOT_FOUND: 404,
        ErrorCode.PAYMENT_NOT_FOUND: 404,
        
        # Валидация - 400 Bad Request
        ErrorCode.VALIDATION_ERROR: 400,
        ErrorCode.MISSING_REQUIRED_FIELD: 400,
        ErrorCode.INVALID_FORMAT: 400,
        ErrorCode.INVALID_AMOUNT: 400,
        ErrorCode.INVALID_CURRENCY: 400,
        ErrorCode.INVALID_BANK_CODE: 400,
        ErrorCode.INVALID_ACCOUNT: 400,
        ErrorCode.INVALID_PHONE: 400,
        ErrorCode.INVALID_QR_CODE: 400,
        ErrorCode.WEBHOOK_INVALID_PAYLOAD: 400,
        
        # Бизнес-логика - 422 Unprocessable Entity
        ErrorCode.PAYMENT_EXPIRED: 422,
        ErrorCode.PAYMENT_ALREADY_PROCESSED: 422,
        ErrorCode.INSUFFICIENT_FUNDS: 422,
        ErrorCode.TRANSACTION_LIMIT_EXCEEDED: 422,
        ErrorCode.DUPLICATE_TRANSACTION: 422,
        ErrorCode.INVALID_PAYMENT_STATE: 422,
        ErrorCode.QR_EXPIRED: 422,
        ErrorCode.QR_ALREADY_USED: 422,
        
        # Rate Limiting - 429 Too Many Requests
        ErrorCode.RATE_LIMIT_EXCEEDED: 429,
        ErrorCode.TOO_MANY_REQUESTS: 429,
        ErrorCode.IP_BLOCKED: 429,
        ErrorCode.SUSPICIOUS_ACTIVITY: 429,
        ErrorCode.QR_SECURITY_VIOLATION: 429,
        ErrorCode.SUSPICIOUS_QR_PATTERN: 429,
        
        # Системные ошибки - 500 Internal Server Error
        ErrorCode.INTERNAL_ERROR: 500,
        ErrorCode.DATABASE_ERROR: 500,
        ErrorCode.CONFIGURATION_ERROR: 500,
        
        # Внешние сервисы - 502 Bad Gateway
        ErrorCode.EXTERNAL_SERVICE_ERROR: 502,
        ErrorCode.WEBHOOK_PROCESSING_ERROR: 502,
        
        # Сеть - 503 Service Unavailable
        ErrorCode.NETWORK_ERROR: 503,
        
        # Таймауты - 504 Gateway Timeout
        ErrorCode.TIMEOUT_ERROR: 504,
        ErrorCode.WEBHOOK_TIMEOUT: 504,
        
        # Webhook подпись - 401 Unauthorized
        ErrorCode.WEBHOOK_INVALID_SIGNATURE: 401,
    }
    
    @staticmethod
    def create_error_response(
        error: StandardError,
        request: Optional[Request] = None
    ) -> JSONResponse:
        """
        Создание стандартизированного ответа об ошибке
        
        Args:
            error: Стандартизированная ошибка
            request: FastAPI Request для дополнительного контекста
            
        Returns:
            JSONResponse с деталями ошибки
        """
        
        # Определяем HTTP статус код
        http_status = ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(
            error.code, 500
        )
        
        # Логируем ошибку
        ErrorHandlingService._log_error(error, http_status, request)
        
        # Создаем ответ
        response_data = error.to_dict()
        
        # Добавляем дополнительную информацию для отладки (только в dev)
        if ErrorHandlingService._is_debug_mode():
            if request:
                response_data["debug"] = {
                    "request_id": getattr(request.state, 'request_id', 'unknown'),
                    "endpoint": f"{request.method} {request.url.path}",
                    "client_ip": request.client.host,
                    "user_agent": request.headers.get("user-agent", "unknown")
                }
        
        return JSONResponse(
            status_code=http_status,
            content=response_data
        )
    
    @staticmethod
    def create_validation_error(
        field: str,
        value: Any,
        message: str,
        suggestions: Optional[List[str]] = None
    ) -> StandardError:
        """Создание ошибки валидации"""
        
        return StandardError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Validation failed for field '{field}': {message}",
            details={
                "field": field,
                "value": str(value) if value is not None else None,
                "validation_message": message
            },
            severity=ErrorSeverity.LOW,
            user_message=f"Неверное значение поля '{field}': {message}",
            suggestions=suggestions or [
                f"Проверьте правильность значения поля '{field}'",
                "Обратитесь к документации API для корректного формата"
            ]
        )
    
    @staticmethod
    def create_authentication_error(
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ) -> StandardError:
        """Создание ошибки аутентификации"""
        
        return StandardError(
            code=ErrorCode.INVALID_TOKEN,
            message=f"Authentication failed: {reason}",
            details=details or {},
            severity=ErrorSeverity.MEDIUM,
            user_message="Ошибка аутентификации",
            suggestions=[
                "Проверьте правильность токена доступа",
                "Убедитесь что токен не истек",
                "Проверьте подпись HMAC запроса"
            ]
        )
    
    @staticmethod
    def create_rate_limit_error(
        limit_type: str,
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> StandardError:
        """Создание ошибки превышения лимитов"""
        
        suggestions = [
            f"Превышен лимит запросов типа '{limit_type}'",
            "Уменьшите частоту запросов",
        ]
        
        if retry_after:
            suggestions.append(f"Повторите запрос через {retry_after} секунд")
        
        return StandardError(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=f"Rate limit exceeded for {limit_type}",
            details=dict(details or {}, **{
                "limit_type": limit_type,
                "retry_after": retry_after
            }),
            severity=ErrorSeverity.MEDIUM,
            user_message=f"Превышен лимит запросов: {limit_type}",
            suggestions=suggestions
        )
    
    @staticmethod
    def create_business_logic_error(
        operation: str,
        reason: str,
        error_code: ErrorCode = ErrorCode.INVALID_PAYMENT_STATE,
        suggestions: Optional[List[str]] = None
    ) -> StandardError:
        """Создание ошибки бизнес-логики"""
        
        return StandardError(
            code=error_code,
            message=f"Business logic error in {operation}: {reason}",
            details={
                "operation": operation,
                "reason": reason
            },
            severity=ErrorSeverity.MEDIUM,
            user_message=f"Ошибка при выполнении операции '{operation}': {reason}",
            suggestions=suggestions or [
                "Проверьте корректность входных данных",
                "Убедитесь что операция допустима в текущем состоянии"
            ]
        )
    
    @staticmethod
    def create_system_error(
        component: str,
        error_details: str,
        original_exception: Optional[Exception] = None
    ) -> StandardError:
        """Создание системной ошибки"""
        
        details = {
            "component": component,
            "error_details": error_details
        }
        
        if original_exception:
            details["exception_type"] = type(original_exception).__name__
            details["exception_message"] = str(original_exception)
        
        return StandardError(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"System error in {component}: {error_details}",
            details=details,
            severity=ErrorSeverity.HIGH,
            user_message="Внутренняя ошибка системы",
            suggestions=[
                "Повторите запрос позже",
                "Если ошибка повторяется, обратитесь в техническую поддержку"
            ]
        )
    
    @staticmethod
    def handle_unexpected_error(
        request: Request,
        exception: Exception
    ) -> JSONResponse:
        """
        Обработка неожиданных исключений
        
        Args:
            request: FastAPI Request
            exception: Исключение для обработки
            
        Returns:
            JSONResponse с информацией об ошибке
        """
        
        # Создаем системную ошибку
        error = ErrorHandlingService.create_system_error(
            component="request_handler",
            error_details="Unexpected exception occurred",
            original_exception=exception
        )
        
        # Логируем полный traceback для системных ошибок со структурированным контекстом
        logger.error(
            f"Unexpected error in {request.method} {request.url.path}",
            exc_info=True,
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request and request.client else None,
                "user_agent": request.headers.get("user-agent", "unknown") if request else None,
                "request_id": getattr(request.state, 'request_id', 'unknown') if request else None,
                "error_code": error.code.value,
                "http_status": ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
                "severity": error.severity.value,
            }
        )
        
        return ErrorHandlingService.create_error_response(error, request)
    
    @staticmethod
    def _log_error(
        error: StandardError,
        http_status: int,
        request: Optional[Request] = None
    ):
        """Логирование ошибки с соответствующим уровнем"""
        
        log_data = {
            "error_code": error.code.value,
            "http_status": http_status,
            "error_message": error.message,  # Переименовано из 'message'
            "severity": error.severity.value,
            "timestamp": error.timestamp
        }
        
        if request:
            log_data.update({
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host,
                "user_agent": request.headers.get("user-agent", "unknown")
            })
        
        # Выбираем уровень логирования в зависимости от серьезности (структурированные логи)
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(
                f"Critical error: {error.message}",
                extra=dict(log_data, **{
                    "error_code": error.code.value,
                    "http_status": http_status,
                    "severity": error.severity.value,
                })
            )
        elif error.severity == ErrorSeverity.HIGH:
            logger.error(
                f"High severity error: {error.message}",
                extra=dict(log_data, **{
                    "error_code": error.code.value,
                    "http_status": http_status,
                    "severity": error.severity.value,
                })
            )
        elif error.severity == ErrorSeverity.MEDIUM:
            logger.warning(
                f"Medium severity error: {error.message}",
                extra=dict(log_data, **{
                    "error_code": error.code.value,
                    "http_status": http_status,
                    "severity": error.severity.value,
                })
            )
        else:
            logger.info(
                f"Low severity error: {error.message}",
                extra=dict(log_data, **{
                    "error_code": error.code.value,
                    "http_status": http_status,
                    "severity": error.severity.value,
                })
            )
    
    @staticmethod
    def _is_debug_mode() -> bool:
        """Проверка режима отладки"""
        import os
        return os.getenv("DEBUG", "false").lower() == "true"
    
    @staticmethod
    def create_error_summary(errors: List[StandardError]) -> Dict[str, Any]:
        """
        Создание сводки по ошибкам
        
        Args:
            errors: Список ошибок для анализа
            
        Returns:
            Dict со сводкой по ошибкам
        """
        
        if not errors:
            return {
                "total_errors": 0,
                "by_severity": {},
                "by_code": {},
                "most_common": []
            }
        
        # Группировка по серьезности
        by_severity = {}
        for error in errors:
            severity = error.severity.value
            by_severity[severity] = by_severity.get(severity, 0) + 1
        
        # Группировка по кодам ошибок
        by_code = {}
        for error in errors:
            code = error.code.value
            by_code[code] = by_code.get(code, 0) + 1
        
        # Наиболее частые ошибки
        most_common = sorted(
            by_code.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            "total_errors": len(errors),
            "by_severity": by_severity,
            "by_code": by_code,
            "most_common": [
                {"code": code, "count": count}
                for code, count in most_common
            ]
        }

# Декоратор для обработки ошибок в эндпоинтах
def handle_endpoint_errors(func):
    """Декоратор для автоматической обработки ошибок в эндпоинтах"""
    
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Пропускаем HTTPException без изменений
            raise
        except Exception as e:
            # Получаем request из аргументов
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            # Обрабатываем неожиданную ошибку
            return ErrorHandlingService.handle_unexpected_error(request, e)
    
    return wrapper
