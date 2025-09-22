"""
QRPayHub Python Client
"""

import requests
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from .exceptions import (
    QRPayHubError,
    AuthenticationError,
    ValidationError,
    RateLimitError,
    PaymentNotFoundError,
    WebhookError
)
from .models import PaymentInfo, PaymentStatus, WebhookData


class QRPayHubClient:
    """
    Клиент для работы с QRPayHub API
    
    Example:
        client = QRPayHubClient(
            base_url="https://api.qrpayhub.com",
            access_token="your-access-token",
            hmac_secret="your-hmac-secret",
            user_agent="MyBank-Backend/1.0.0"
        )
        
        # Получение информации о платеже
        payment_info = client.get_payment_info("qr_token")
        
        # Отправка webhook о статусе
        client.send_payment_status(
            token="qr_token",
            status=PaymentStatus.SUCCESS,
            transaction_id="TXN123456",
            amount=1000.00,
            payer_phone="+996555123456"
        )
    """
    
    def __init__(
        self,
        base_url: str,
        access_token: str,
        hmac_secret: str,
        user_agent: str = "QRPayHub-Python-SDK/1.0.0",
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Инициализация клиента
        
        Args:
            base_url: Базовый URL API (например, https://api.qrpayhub.com)
            access_token: Токен доступа банка
            hmac_secret: Секретный ключ для HMAC подписи
            user_agent: User-Agent для запросов
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество повторов при ошибках
        """
        self.base_url = base_url.rstrip('/')
        self.access_token = access_token
        self.hmac_secret = hmac_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Настройка HTTP сессии
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.access_token}',
            'User-Agent': self.user_agent,
            'Content-Type': 'application/json'
        })
    
    def get_payment_info(
        self, 
        token: str,
        device_id: Optional[str] = None,
        app_version: Optional[str] = None
    ) -> PaymentInfo:
        """
        Получение информации о платеже по токену QR-кода
        
        Args:
            token: Токен из QR-кода
            device_id: ID устройства (опционально)
            app_version: Версия приложения (опционально)
            
        Returns:
            PaymentInfo: Информация о платеже
            
        Raises:
            PaymentNotFoundError: Платеж не найден
            AuthenticationError: Ошибка аутентификации
            ValidationError: Ошибка валидации
            RateLimitError: Превышен лимит запросов
            QRPayHubError: Другие ошибки API
        """
        headers = {}
        if device_id:
            headers['X-Device-ID'] = device_id
        if app_version:
            headers['X-App-Version'] = app_version
        
        url = urljoin(self.base_url, '/api/v1/payment/payment-info')
        params = {'token': token}
        
        response = self._make_request('GET', url, params=params, headers=headers)
        return PaymentInfo.from_dict(response)
    
    def send_payment_status(
        self,
        token: str,
        status: PaymentStatus,
        transaction_id: str,
        amount: float,
        payer_phone: str,
        currency: str = "KGS",
        timestamp: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        fee_amount: Optional[float] = None,
        processing_time_ms: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Отправка webhook о статусе платежа
        
        Args:
            token: Токен из QR-кода
            status: Статус платежа
            transaction_id: ID транзакции в системе банка
            amount: Сумма платежа
            payer_phone: Телефон плательщика
            currency: Валюта (по умолчанию KGS)
            timestamp: Время обработки (ISO 8601)
            error_code: Код ошибки (для неуспешных платежей)
            error_message: Описание ошибки (для неуспешных платежей)
            fee_amount: Размер комиссии
            processing_time_ms: Время обработки в мс
            
        Returns:
            Dict: Ответ сервера
            
        Raises:
            WebhookError: Ошибка обработки webhook
            AuthenticationError: Ошибка аутентификации
            ValidationError: Ошибка валидации
            QRPayHubError: Другие ошибки API
        """
        webhook_data = WebhookData(
            token=token,
            status=status,
            transaction_id=transaction_id,
            amount=amount,
            currency=currency,
            payer_phone=payer_phone,
            timestamp=timestamp or self._current_iso_timestamp(),
            error_code=error_code,
            error_message=error_message,
            fee_amount=fee_amount,
            processing_time_ms=processing_time_ms
        )
        
        return self.send_webhook(webhook_data)
    
    def send_webhook(self, webhook_data: WebhookData) -> Dict[str, Any]:
        """
        Отправка webhook с данными
        
        Args:
            webhook_data: Данные webhook
            
        Returns:
            Dict: Ответ сервера
        """
        url = urljoin(self.base_url, '/api/v1/payment/payment-status')
        path = '/api/v1/payment/payment-status'
        
        body = json.dumps(webhook_data.to_dict(), separators=(',', ':'))
        timestamp = str(int(time.time()))
        
        # Создаем HMAC подпись
        signature = self._create_hmac_signature('POST', path, body, timestamp)
        
        headers = {
            'X-Signature': signature,
            'X-Timestamp': timestamp,
            'X-Transaction-ID': webhook_data.transaction_id
        }
        
        response = self._make_request('POST', url, data=body, headers=headers)
        return response
    
    def _create_hmac_signature(self, method: str, path: str, body: str, timestamp: str) -> str:
        """Создание HMAC подписи для запроса"""
        message = f"{method}\n{path}\n{body}\n{timestamp}"
        signature = hmac.new(
            self.hmac_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    def _current_iso_timestamp(self) -> str:
        """Получение текущего времени в ISO формате"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'
    
    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[str] = None,
        headers: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Выполнение HTTP запроса с обработкой ошибок и retry логикой
        """
        request_headers = self.session.headers.copy()
        if headers:
            request_headers.update(headers)
        
        for attempt in range(self.max_retries + 1):
            try:
                if method == 'GET':
                    response = self.session.get(
                        url,
                        params=params,
                        headers=request_headers,
                        timeout=self.timeout
                    )
                elif method == 'POST':
                    response = self.session.post(
                        url,
                        data=data,
                        headers=request_headers,
                        timeout=self.timeout
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                # Обработка успешных ответов
                if response.status_code == 200:
                    return response.json()
                
                # Обработка ошибок
                self._handle_error_response(response)
                
            except requests.exceptions.Timeout:
                if attempt == self.max_retries:
                    raise QRPayHubError("Request timeout")
                time.sleep(2 ** attempt)  # Exponential backoff
                
            except requests.exceptions.ConnectionError:
                if attempt == self.max_retries:
                    raise QRPayHubError("Connection error")
                time.sleep(2 ** attempt)
                
            except requests.exceptions.RequestException as e:
                raise QRPayHubError(f"Request failed: {str(e)}")
    
    def _handle_error_response(self, response: requests.Response):
        """Обработка ошибочных ответов API"""
        try:
            error_data = response.json()
            error = error_data.get('error', {})
            
            error_code = error.get('code', 'UNKNOWN_ERROR')
            message = error.get('message', 'Unknown error')
            user_message = error.get('user_message', message)
            
        except (ValueError, KeyError):
            error_code = 'UNKNOWN_ERROR'
            message = f"HTTP {response.status_code}: {response.text}"
            user_message = message
        
        # Маппинг ошибок на исключения
        if response.status_code == 401:
            raise AuthenticationError(message, error_code, user_message)
        elif response.status_code == 400:
            if 'PAYMENT_NOT_FOUND' in error_code:
                raise PaymentNotFoundError(message, error_code, user_message)
            elif 'WEBHOOK' in error_code:
                raise WebhookError(message, error_code, user_message)
            else:
                raise ValidationError(message, error_code, user_message)
        elif response.status_code == 404:
            raise PaymentNotFoundError(message, error_code, user_message)
        elif response.status_code == 429:
            raise RateLimitError(message, error_code, user_message)
        elif 'WEBHOOK' in error_code:
            raise WebhookError(message, error_code, user_message)
        else:
            raise QRPayHubError(message, error_code, user_message)
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.session.close()
    
    def close(self):
        """Закрытие сессии"""
        self.session.close()
