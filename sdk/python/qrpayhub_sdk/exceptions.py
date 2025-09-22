"""
QRPayHub SDK Exceptions
"""

from typing import Optional


class QRPayHubError(Exception):
    """Базовое исключение для всех ошибок QRPayHub SDK"""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None, 
        user_message: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.user_message = user_message or message
    
    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class AuthenticationError(QRPayHubError):
    """Ошибка аутентификации (401, 403)"""
    pass


class ValidationError(QRPayHubError):
    """Ошибка валидации данных (400)"""
    pass


class PaymentNotFoundError(QRPayHubError):
    """Платеж не найден (404)"""
    pass


class RateLimitError(QRPayHubError):
    """Превышен лимит запросов (429)"""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None, 
        user_message: Optional[str] = None,
        retry_after: Optional[int] = None
    ):
        super().__init__(message, error_code, user_message)
        self.retry_after = retry_after


class WebhookError(QRPayHubError):
    """Ошибка обработки webhook"""
    pass


class NetworkError(QRPayHubError):
    """Ошибка сети или соединения"""
    pass


class TimeoutError(QRPayHubError):
    """Таймаут запроса"""
    pass
