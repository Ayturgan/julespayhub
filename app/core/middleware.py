import time
import json
import logging
from datetime import datetime
from typing import Dict
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, RedirectResponse
from app.services.hybrid_logging_service import hybrid_logging_service
from app.services.realtime_monitoring_service import realtime_monitoring_service, MonitoringEventType
from app.database import SessionLocal
from app.services.admin_auth_service import AdminAuthService

class BodyCacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware для кеширования body запроса для HMAC подписи
    """
    
    async def dispatch(self, request: Request, call_next):
        # Логируем начало выполнения middleware
        import logging
        logger = logging.getLogger(__name__)
        
        # Читаем и кешируем body только для POST запросов
        if request.method == "POST":
            try:
                # Читаем тело запроса и сохраняем его
                body = await request.body()
                body_str = body.decode('utf-8') if body else ""
                
                # Сохраняем body в state для использования в dependency
                request.state.body = body_str
                
            except Exception as e:
                # В случае ошибки логируем и устанавливаем пустое тело
                logger.error(f"BodyCacheMiddleware error: {e}")
                request.state.body = ""
        else:
            request.state.body = ""
        
        response = await call_next(request)
        return response

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для автоматического логирования всех API запросов
    """
    
    async def dispatch(self, request: Request, call_next):
        # Записываем время начала запроса
        start_time = time.time()
        request.state.start_time = start_time
        
        # Пропускаем логирование для статических файлов и health check
        if self._should_skip_logging(request.url.path):
            return await call_next(request)
        
        response = None
        error_message = None
        rate_limited = False
        
        try:
            response = await call_next(request)
            
            # Проверяем, был ли запрос ограничен rate limiting
            if response.status_code == 429:
                rate_limited = True
            
        except Exception as e:
            error_message = str(e)
            # Создаем ответ с ошибкой
            response = Response(
                content=json.dumps({"error": "Internal server error"}),
                status_code=500,
                media_type="application/json"
            )
            # Аудит серверной ошибки
            try:
                from app.database import SessionLocal as _SL
                with _SL() as _db:
                    hybrid_logging_service.log_event(
                        hybrid_logging_service.LogEvent(
                            timestamp=datetime.utcnow(),
                            level=hybrid_logging_service.LogLevel.CRITICAL,
                            destination=hybrid_logging_service.LogDestination.BOTH,
                            event_type="server_error",
                            event_source=request.url.path,
                            actor_type="system",
                            ip_address=request.client.host if request.client else None,
                            status="failure",
                            error_message=str(e),
                            details={"exception": str(e)}
                        ),
                        _db
                    )
            except Exception:
                pass
        
        # Перехватываем тело ответа для логирования (превью)
        response_body_preview = None
        try:
            if hasattr(response, 'body_iterator') and response.body_iterator is not None:
                body_chunks = []
                async for chunk in response.body_iterator:
                    body_chunks.append(chunk)
                full_body = b"".join(body_chunks)
                response_body_preview = full_body[:2000].decode('utf-8', errors='replace') if full_body else ""
                # Пересобираем Response, чтобы отдать тело клиенту
                response = Response(
                    content=full_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                    background=response.background
                )
        except Exception:
            # Не мешаем ответу даже если превью не удалось получить
            response_body_preview = None

        # Структурированное логирование запроса/ответа
        try:
            api_logger = logging.getLogger("api_requests")
            duration_ms = int((time.time() - start_time) * 1000)
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            request_id = getattr(request.state, 'request_id', 'unknown')
            query_params = dict(request.query_params) if request.query_params else {}

            def _sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
                # Список чувствительных заголовков
                SENSITIVE_HEADERS = {
                    'authorization', 'cookie', 'x-api-key', 'x-auth-token',
                    'x-secret', 'x-password', 'x-private-key'
                }
                sanitized = {}
                for k, v in dict(headers).items():
                    kl = k.lower()
                    if kl in SENSITIVE_HEADERS or (kl.startswith('x-') and 'secret' in kl):
                        sanitized[k] = "[REDACTED]"
                    else:
                        vs = v if isinstance(v, str) else str(v)
                        sanitized[k] = vs[:500] if len(vs) > 500 else vs
                return sanitized

            request_headers = _sanitize_headers(request.headers)
            response_headers = _sanitize_headers(response.headers)
            request_body_preview = getattr(request.state, 'body', '')
            request_body_preview = request_body_preview[:2000] if request_body_preview else ""

            bank_code = getattr(request.state, 'bank_code', None)
            if hasattr(request.state, 'authenticated_bank'):
                bank_code = request.state.authenticated_bank.code

            api_logger.info(
                f"{request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "client_ip": client_ip,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "bank_code": bank_code,
                    "rate_limited": rate_limited,
                    "user_agent": user_agent,
                    "query_params": query_params,
                    "request_headers": request_headers,
                    "response_headers": response_headers,
                    "request_body_preview": request_body_preview,
                    "response_body_preview": response_body_preview,
                    "error_message": error_message,
                }
            )
        except Exception as e:
            # Не прерываем выполнение запроса из-за ошибки логирования
            print(f"Logging error (structured): {e}")

        # Логируем запрос в фоновом режиме
        try:
            self._log_request_async(
                request, response, start_time, error_message, rate_limited
            )
        except Exception as e:
            # Не прерываем выполнение запроса из-за ошибки логирования
            print(f"Logging error: {e}")

        # Аудит API запроса (только для админских действий)
        try:
            if request.url.path.startswith('/admin') and hasattr(request.state, 'current_admin') and request.state.current_admin:
                from app.database import SessionLocal as _SL
                with _SL() as _db:
                    hybrid_logging_service.log_event(
                        hybrid_logging_service.LogEvent(
                            timestamp=datetime.utcnow(),
                            level=hybrid_logging_service.LogLevel.INFO,
                            destination=hybrid_logging_service.LogDestination.BOTH,
                            event_type="admin_api_request",
                            event_source=request.url.path,
                            actor_type="admin",
                            actor_id=request.state.current_admin.get('username'),
                            ip_address=request.client.host if request.client else None,
                            status="success" if response.status_code < 400 else "failure",
                            details={
                                "method": request.method,
                                "status_code": response.status_code,
                                "rate_limited": rate_limited,
                            }
                        ),
                        _db
                    )
        except Exception:
            pass
        
        return response
    
    def _should_skip_logging(self, path: str) -> bool:
        """Определяет, нужно ли пропустить логирование для данного пути"""
        skip_paths = [
            '/favicon.ico',
            '/health',
            '/docs',
            '/openapi.json',
            '/redoc',
            '/static',
            '/admin/static'
        ]
        
        return any(path.startswith(skip_path) for skip_path in skip_paths)
    
    def _log_request_async(
        self, 
        request: Request, 
        response: Response, 
        start_time: float,
        error_message: str = None,
        rate_limited: bool = False
    ):
        """Асинхронное логирование запроса"""
        
        # Получаем информацию из state если есть
        token = getattr(request.state, 'token', None)
        bank_code = getattr(request.state, 'bank_code', None)
        
        # Определяем банк из аутентификации если есть
        if hasattr(request.state, 'authenticated_bank'):
            bank_code = request.state.authenticated_bank.code
        
        # Вычисляем длительность запроса
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Определяем уровень логирования
        level = hybrid_logging_service.LogLevel.ERROR if response.status_code >= 400 else hybrid_logging_service.LogLevel.INFO
        
        # Создаем событие для логирования
        event = hybrid_logging_service.LogEvent(
            timestamp=datetime.utcnow(),
            level=level,
            destination=hybrid_logging_service.LogDestination.FILE,  # Только в файлы для API запросов
            event_type="api_request",
            event_source="api",
            actor_type="bank" if bank_code else "system",
            actor_id=bank_code,
            ip_address=request.client.host if request.client else None,
            status="success" if response.status_code < 400 else "error",
            duration_ms=duration_ms,
            payment_token=token,
            bank_code=bank_code,
            error_message=error_message,
            details={
                "endpoint": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "user_agent": request.headers.get("user-agent"),
                "rate_limited": rate_limited
            }
        )
        
        # Логируем событие (только в файлы, без БД)
        hybrid_logging_service.log_event(event)
        
        # Записываем событие в мониторинг в реальном времени
        self._record_monitoring_event(
            request, response, start_time, bank_code, error_message, rate_limited
        )
    
    def _record_monitoring_event(
        self,
        request: Request,
        response: Response,
        start_time: float,
        bank_code: str = None,
        error_message: str = None,
        rate_limited: bool = False
    ):
        """Записывает событие в систему мониторинга"""
        try:
            response_time_ms = (time.time() - start_time) * 1000
            client_ip = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent")
            endpoint = request.url.path
            
            # Определяем тип события и успешность
            success = response.status_code < 400 and not error_message and not rate_limited
            
            if rate_limited:
                realtime_monitoring_service.record_rate_limit_hit(
                    bank_code=bank_code or "unknown",
                    ip_address=client_ip,
                    endpoint=endpoint,
                    user_agent=user_agent
                )
            elif endpoint == "/api/v1/payment-status":
                realtime_monitoring_service.record_webhook_event(
                    bank_code=bank_code or "unknown",
                    success=success,
                    error_message=error_message,
                    response_time_ms=response_time_ms
                )
            elif endpoint.startswith("/api/v1/") and bank_code:
                realtime_monitoring_service.record_payment_request(
                    bank_code=bank_code,
                    endpoint=endpoint,
                    ip_address=client_ip,
                    response_time_ms=response_time_ms,
                    success=success,
                    error_message=error_message,
                    user_agent=user_agent
                )
            
        except Exception as e:
            # Не прерываем выполнение из-за ошибки мониторинга
            print(f"Monitoring error: {e}")


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware для защиты админ панели
    Проверяет JWT токен для доступа к /admin маршрутам
    """
    
    async def dispatch(self, request: Request, call_next):
        # Проверяем, является ли запрос к админ панели
        if request.url.path.startswith("/admin") and request.url.path != "/admin/login":
            print(f"AdminAuthMiddleware: Проверяем доступ к {request.url.path}")
            
            # Получаем токен из заголовка Authorization или cookies
            auth_header = request.headers.get("Authorization")
            token = None
            
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
                print(f"AdminAuthMiddleware: Токен из заголовка: {token[:20]}...")
            else:
                # Проверяем cookies
                token = request.cookies.get("admin_token")
                print(f"AdminAuthMiddleware: Токен из cookies: {token[:20] if token else 'None'}...")
            
            # Проверяем токен
            if not token:
                print("AdminAuthMiddleware: Токен не найден, перенаправляем на /admin/login")
                return RedirectResponse(url="/admin/login", status_code=302)
            
            try:
                # Верифицируем токен
                payload = AdminAuthService.verify_token(token)
                if not payload:
                    print("AdminAuthMiddleware: Токен недействителен, перенаправляем на /admin/login")
                    return RedirectResponse(url="/admin/login", status_code=302)
                
                print(f"AdminAuthMiddleware: Токен валиден для админа {payload.get('sub', 'unknown')}")
                # Добавляем информацию об админе в state
                request.state.current_admin = payload
                
            except Exception as e:
                print(f"AdminAuthMiddleware: Ошибка верификации токена: {e}")
                # При любой ошибке перенаправляем на страницу входа
                return RedirectResponse(url="/admin/login", status_code=302)
        
        # Продолжаем обработку запроса
        response = await call_next(request)
        return response
