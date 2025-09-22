from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.services.error_handling_service import (
    ErrorHandlingService, 
    StandardError, 
    ErrorCode, 
    ErrorSeverity
)
import logging

logger = logging.getLogger(__name__)

def setup_exception_handlers(app: FastAPI):
    """Настройка глобальных обработчиков исключений"""
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Обработка HTTPException"""
        
        # Если это уже стандартизированная ошибка, возвращаем как есть
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail
            )
        
        # Преобразуем в стандартную ошибку
        error = StandardError(
            code=_map_http_status_to_error_code(exc.status_code),
            message=str(exc.detail),
            severity=_determine_severity_from_status(exc.status_code),
            user_message=str(exc.detail)
        )
        
        return ErrorHandlingService.create_error_response(error, request)
    
    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Обработка Starlette HTTPException"""
        
        error = StandardError(
            code=_map_http_status_to_error_code(exc.status_code),
            message=str(exc.detail),
            severity=_determine_severity_from_status(exc.status_code),
            user_message=str(exc.detail)
        )
        
        return ErrorHandlingService.create_error_response(error, request)
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Обработка ошибок валидации Pydantic"""
        
        # Дополнительное логирование для отладки
        logger.error(f"❌ Ошибка валидации запроса: {exc.errors()}")
        try:
            body = await request.body()
            logger.error(f"❌ Тело запроса: {body.decode('utf-8')}")
        except Exception as e:
            logger.error(f"❌ Не удалось прочитать тело запроса: {e}")
        logger.error(f"❌ URL: {request.url}")
        logger.error(f"❌ Метод: {request.method}")
        
        # Собираем детали ошибок валидации
        validation_errors = []
        for error in exc.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            validation_errors.append({
                "field": field_path,
                "message": error["msg"],
                "type": error["type"],
                "input": error.get("input")
            })
        
        # Создаем стандартную ошибку валидации
        error = StandardError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            details={
                "validation_errors": validation_errors,
                "error_count": len(validation_errors)
            },
            severity=ErrorSeverity.LOW,
            user_message="Ошибка валидации входных данных",
            suggestions=[
                "Проверьте правильность всех обязательных полей",
                "Убедитесь что типы данных соответствуют требованиям API",
                "Обратитесь к документации API для корректных форматов"
            ]
        )
        
        return ErrorHandlingService.create_error_response(error, request)
    
    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        """Обработка ошибок базы данных"""
        
        # Определяем тип ошибки БД
        if isinstance(exc, IntegrityError):
            # Ошибка целостности (дубликаты, внешние ключи и т.д.)
            error = StandardError(
                code=ErrorCode.DUPLICATE_TRANSACTION,
                message="Database integrity constraint violation",
                details={
                    "database_error": str(exc.orig) if hasattr(exc, 'orig') else str(exc),
                    "statement": exc.statement if hasattr(exc, 'statement') else None
                },
                severity=ErrorSeverity.MEDIUM,
                user_message="Конфликт данных в базе данных",
                suggestions=[
                    "Проверьте уникальность идентификаторов",
                    "Убедитесь что все связанные объекты существуют"
                ]
            )
        else:
            # Общая ошибка БД
            error = StandardError(
                code=ErrorCode.DATABASE_ERROR,
                message="Database operation failed",
                details={
                    "database_error": str(exc),
                    "error_type": type(exc).__name__
                },
                severity=ErrorSeverity.HIGH,
                user_message="Ошибка базы данных",
                suggestions=[
                    "Повторите запрос позже",
                    "Если ошибка повторяется, обратитесь в техническую поддержку"
                ]
            )
        
        return ErrorHandlingService.create_error_response(error, request)
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Обработка всех остальных исключений"""
        
        return ErrorHandlingService.handle_unexpected_error(request, exc)

def _map_http_status_to_error_code(status_code: int) -> ErrorCode:
    """Маппинг HTTP статус кодов на коды ошибок системы"""
    
    status_to_code = {
        400: ErrorCode.VALIDATION_ERROR,
        401: ErrorCode.INVALID_TOKEN,
        403: ErrorCode.IP_NOT_ALLOWED,
        404: ErrorCode.PAYMENT_NOT_FOUND,
        422: ErrorCode.INVALID_PAYMENT_STATE,
        429: ErrorCode.RATE_LIMIT_EXCEEDED,
        500: ErrorCode.INTERNAL_ERROR,
        502: ErrorCode.EXTERNAL_SERVICE_ERROR,
        503: ErrorCode.NETWORK_ERROR,
        504: ErrorCode.TIMEOUT_ERROR
    }
    
    return status_to_code.get(status_code, ErrorCode.INTERNAL_ERROR)

def _determine_severity_from_status(status_code: int) -> ErrorSeverity:
    """Определение серьезности ошибки по HTTP статус коду"""
    
    if status_code >= 500:
        return ErrorSeverity.HIGH
    elif status_code >= 400:
        return ErrorSeverity.MEDIUM
    else:
        return ErrorSeverity.LOW

# Middleware для добавления request_id
class RequestIDMiddleware:
    """Middleware для добавления уникального ID к каждому запросу"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Генерируем уникальный ID запроса
            import uuid
            request_id = str(uuid.uuid4())[:8]
            
            # Добавляем в scope для доступа в обработчиках
            scope["state"] = getattr(scope, "state", {})
            scope["state"]["request_id"] = request_id
            
            # Добавляем заголовок в ответ
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    headers[b"x-request-id"] = request_id.encode()
                    message["headers"] = list(headers.items())
                await send(message)
            
            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
