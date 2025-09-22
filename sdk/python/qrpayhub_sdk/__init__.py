"""
QRPayHub Python SDK

Официальный Python SDK для интеграции с QRPayHub API.
"""

__version__ = "1.0.0"
__author__ = "QRPayHub Team"
__email__ = "integration@qrpayhub.com"

from .client import QRPayHubClient
from .exceptions import (
    QRPayHubError,
    AuthenticationError,
    ValidationError,
    RateLimitError,
    PaymentNotFoundError,
    WebhookError
)
from .models import PaymentInfo, PaymentStatus, WebhookData

__all__ = [
    'QRPayHubClient',
    'QRPayHubError',
    'AuthenticationError', 
    'ValidationError',
    'RateLimitError',
    'PaymentNotFoundError',
    'WebhookError',
    'PaymentInfo',
    'PaymentStatus', 
    'WebhookData'
]
