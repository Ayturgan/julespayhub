from fastapi import Depends, Request, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.auth_service import BankAuthService
from app.services.rate_limit_service import RateLimitService
from app.services.webhook_security_service import WebhookSecurityService
from app.services.admin_auth_service import AdminAuthService
from app.models.payment import Bank
from app.models.admin import Admin
from typing import Optional

async def get_authenticated_bank(
    request: Request,
    db: Session = Depends(get_db),
    require_hmac: bool = True
) -> Bank:
    """
    Dependency для аутентификации банков в эндпоинтах
    
    Usage:
        @app.get("/secure-endpoint")
        async def secure_endpoint(bank: Bank = Depends(get_authenticated_bank)):
            return {"bank": bank.name}
    """
    return BankAuthService.authenticate_bank_request(db, request, require_hmac)

async def get_authenticated_bank_no_hmac(
    request: Request,
    db: Session = Depends(get_db)
) -> Bank:
    """
    Dependency для аутентификации банков без HMAC (для менее критичных операций)
    """
    return BankAuthService.authenticate_bank_request(db, request, require_hmac=False)

def check_rate_limit(endpoint: str):
    """
    Фабрика для создания dependency проверки rate limit
    
    Usage:
        @app.get("/some-endpoint")
        async def endpoint(
            request: Request,
            _: None = Depends(check_rate_limit("some-endpoint")),
            db: Session = Depends(get_db)
        ):
            return {"message": "success"}
    """
    def rate_limit_dependency(
        request: Request,
        db: Session = Depends(get_db)
    ):
        # Проверяем rate limit
        allowed, info = RateLimitService.check_rate_limit(
            db=db,
            ip_address=request.client.host,
            endpoint=endpoint,
            user_agent=request.headers.get("user-agent")
        )
        
        if not allowed:
            # Добавляем заголовки для клиента
            headers = {}
            if "retry_after" in info:
                headers["Retry-After"] = str(info["retry_after"])
            if "blocked_until" in info:
                headers["X-RateLimit-BlockedUntil"] = info["blocked_until"]
            
            raise HTTPException(
                status_code=429,
                detail=info.get("error", "Rate limit exceeded"),
                headers=headers
            )
        
        # Добавляем информационные заголовки
        request.state.rate_limit_info = info
        return None
    
    return rate_limit_dependency

def check_bank_rate_limit(endpoint: str):
    """
    Фабрика для проверки rate limit с учетом банка
    Используется после аутентификации банка
    """
    def bank_rate_limit_dependency(
        request: Request,
        bank: Bank,  # Должен быть передан из аутентификации
        db: Session = Depends(get_db)
    ):
        # Проверяем rate limit с учетом банка
        allowed, info = RateLimitService.check_rate_limit(
            db=db,
            ip_address=request.client.host,
            endpoint=endpoint,
            bank_code=bank.code,
            user_agent=request.headers.get("user-agent")
        )
        
        if not allowed:
            headers = {}
            if "retry_after" in info:
                headers["Retry-After"] = str(info["retry_after"])
            if "blocked_until" in info:
                headers["X-RateLimit-BlockedUntil"] = info["blocked_until"]
            
            raise HTTPException(
                status_code=429,
                detail=info.get("error", "Rate limit exceeded"),
                headers=headers
            )
        
        request.state.rate_limit_info = info
        return None
    
    return bank_rate_limit_dependency

async def get_authenticated_bank_with_rate_limit(
    endpoint: str,
    require_hmac: bool = True
):
    """
    Комбинированная аутентификация банка с проверкой rate limit
    """
    async def combined_dependency(
        request: Request,
        db: Session = Depends(get_db)
    ) -> Bank:
        # Сначала проверяем rate limit по IP
        allowed, info = RateLimitService.check_rate_limit(
            db=db,
            ip_address=request.client.host,
            endpoint=endpoint,
            user_agent=request.headers.get("user-agent")
        )
        
        if not allowed:
            headers = {}
            if "retry_after" in info:
                headers["Retry-After"] = str(info["retry_after"])
            if "blocked_until" in info:
                headers["X-RateLimit-BlockedUntil"] = info["blocked_until"]
            
            raise HTTPException(
                status_code=429,
                detail=info.get("error", "Rate limit exceeded"),
                headers=headers
            )
        
        # Затем аутентифицируем банк
        bank = BankAuthService.authenticate_bank_request(db, request, require_hmac)
        
        # Дополнительная проверка rate limit с учетом банка
        allowed_bank, info_bank = RateLimitService.check_rate_limit(
            db=db,
            ip_address=request.client.host,
            endpoint=endpoint,
            bank_code=bank.code,
            user_agent=request.headers.get("user-agent")
        )
        
        if not allowed_bank:
            headers = {}
            if "retry_after" in info_bank:
                headers["Retry-After"] = str(info_bank["retry_after"])
            if "blocked_until" in info_bank:
                headers["X-RateLimit-BlockedUntil"] = info_bank["blocked_until"]
            
            raise HTTPException(
                status_code=429,
                detail=f"Bank rate limit exceeded: {info_bank.get('error', 'Rate limit exceeded')}",
                headers=headers
            )
        
        # Сохраняем информацию о rate limit
        request.state.rate_limit_info = info_bank
        
        return bank
    
    return combined_dependency

# Готовые dependency для основных эндпоинтов
async def get_bank_for_payment_info(
    request: Request,
    db: Session = Depends(get_db)
) -> Bank:
    """Аутентификация банка для payment-info с rate limiting"""
    # Проверяем rate limit по IP
    allowed, info = RateLimitService.check_rate_limit(
        db=db,
        ip_address=request.client.host,
        endpoint="payment-info",
        user_agent=request.headers.get("user-agent")
    )
    
    if not allowed:
        headers = {}
        if "retry_after" in info:
            headers["Retry-After"] = str(info["retry_after"])
        if "blocked_until" in info:
            headers["X-RateLimit-BlockedUntil"] = info["blocked_until"]
        
        raise HTTPException(
            status_code=429,
            detail=info.get("error", "Rate limit exceeded"),
            headers=headers
        )
    
    # Аутентифицируем банк
    bank = BankAuthService.authenticate_bank_request(db, request, require_hmac=False)
    
    # Сохраняем информацию о rate limit
    request.state.rate_limit_info = info
    
    return bank

async def get_bank_for_webhook(
    request: Request,
    db: Session = Depends(get_db)
) -> Bank:
    """Аутентификация банка для webhook с расширенной безопасностью"""
    # Проверяем rate limit по IP
    allowed, info = RateLimitService.check_rate_limit(
        db=db,
        ip_address=request.client.host,
        endpoint="webhook",
        user_agent=request.headers.get("user-agent")
    )
    
    if not allowed:
        headers = {}
        if "retry_after" in info:
            headers["Retry-After"] = str(info["retry_after"])
        if "blocked_until" in info:
            headers["X-RateLimit-BlockedUntil"] = info["blocked_until"]
        
        raise HTTPException(
            status_code=429,
            detail=info.get("error", "Rate limit exceeded"),
            headers=headers
        )
    
    # Аутентифицируем банк (включает базовую проверку HMAC)
    bank = BankAuthService.authenticate_bank_request(db, request, require_hmac=True)
    
    # Дополнительная расширенная проверка webhook безопасности
    body = getattr(request.state, 'body', '')
    webhook_security_result = WebhookSecurityService.verify_webhook_signature(
        request, bank, body, require_timestamp=True
    )
    
    if not webhook_security_result["valid"]:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Webhook security validation failed",
                "details": webhook_security_result["errors"],
                "diagnostics": webhook_security_result.get("details", {})
            }
        )
    
    # Сохраняем информацию для логирования
    request.state.rate_limit_info = info
    request.state.webhook_security_result = webhook_security_result
    
    return bank


async def get_current_admin_user(
    request: Request,
    db: Session = Depends(get_db)
) -> dict:
    """
    Dependency для получения текущего админа из JWT токена
    
    Usage:
        @app.get("/admin/endpoint")
        async def admin_endpoint(current_admin: dict = Depends(get_current_admin_user)):
            return {"admin": current_admin}
    """
    # Получаем токен из заголовка Authorization или cookies
    auth_header = request.headers.get("Authorization")
    token = None
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        # Проверяем cookies
        token = request.cookies.get("admin_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        # Верифицируем токен
        payload = AdminAuthService.verify_token(token)
        
        # Получаем админа из БД
        admin = db.query(Admin).filter(Admin.id == payload.get("admin_id")).first()
        if not admin:
            raise HTTPException(status_code=401, detail="Admin not found")
        
        if not admin.is_active:
            raise HTTPException(status_code=401, detail="Admin account is deactivated")
        
        # Возвращаем информацию об админе
        return {
            "id": admin.id,
            "username": admin.username,
            "email": admin.email,
            "role": admin.role,
            "organization_name": admin.organization_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")
