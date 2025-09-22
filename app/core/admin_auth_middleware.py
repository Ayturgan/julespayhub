from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from app.services.admin_auth_service import AdminAuthService
from typing import Optional
import jwt

class AdminAuthMiddleware:
    """Middleware для проверки авторизации админов"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive)
        
        # Проверяем только админские маршруты
        if request.url.path.startswith("/admin") and request.url.path != "/admin/login":
            # Проверяем токен в заголовках или cookies
            token = self._get_token_from_request(request)
            
            if not token:
                # Перенаправляем на страницу входа
                response = RedirectResponse(url="/admin/login", status_code=302)
                await response(scope, receive, send)
                return
            
            try:
                # Проверяем токен
                payload = AdminAuthService.verify_token(token)
                # Добавляем информацию об админе в scope
                scope["admin"] = payload
            except Exception:
                # Токен недействителен, перенаправляем на вход
                response = RedirectResponse(url="/admin/login", status_code=302)
                await response(scope, receive, send)
                return
        
        await self.app(scope, receive, send)
    
    def _get_token_from_request(self, request: Request) -> Optional[str]:
        """Получение токена из запроса"""
        # Проверяем Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.replace("Bearer ", "")
        
        # Проверяем cookie
        token = request.cookies.get("admin_token")
        if token:
            return token
        
        return None
