from typing import Dict, Any, Optional, List, Type, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
import httpx
from datetime import datetime
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.payment import Bank
from app.schemas.payment import PaymentInfo, PaymentStatusWebhook
from app.schemas.bank import (
    TransactionPrepareRequest, TransactionPrepareResponse,
    TransactionCommitRequest, TransactionCommitResponse,
    TransactionAbortRequest, TransactionAbortResponse
)
from app.schemas.refund import (
    RefundPrepareRequest, RefundPrepareResponse,
    RefundCommitRequest, RefundCommitResponse,
    RefundAbortRequest, RefundAbortResponse
)
from app.services.error_handling_service import StandardError, ErrorCode, ErrorSeverity

logger = logging.getLogger(__name__)

class BankType(Enum):
    """Типы банков с различными требованиями к интеграции"""
    STANDARD = "standard"           # Стандартная интеграция
    LEGACY = "legacy"              # Устаревшие системы
    ENTERPRISE = "enterprise"      # Корпоративные банки
    MOBILE_FIRST = "mobile_first"  # Мобильные банки
    FINTECH = "fintech"           # Финтех компании
    CUSTOM = "custom"             # Кастомная интеграция

@dataclass
class BankConfiguration:
    """Конфигурация для конкретного банка"""
    
    # Основные настройки
    bank_code: str
    bank_type: BankType
    name: str
    base_url: str = ""  # Базовый URL для API банка (пустой для относительных путей)
    bank: Optional[Bank] = None  # Ссылка на объект Bank
    
    # API настройки
    api_version: str = "1.0"
    timeout_seconds: int = 30
    max_retries: int = 3
    
    # Форматирование данных
    amount_format: str = "decimal"  # decimal, integer_kopecks, string
    phone_format: str = "international"  # international, national, raw
    date_format: str = "iso"  # iso, timestamp, custom
    
    # Валидация
    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    custom_validators: Dict[str, Any] = field(default_factory=dict)
    
    # Webhook настройки
    webhook_format: str = "standard"  # standard, custom
    webhook_auth_method: str = "hmac"  # hmac, bearer, custom
    webhook_retry_attempts: int = 5
    
    # Специфичные для банка настройки
    custom_headers: Dict[str, str] = field(default_factory=dict)
    custom_parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Лимиты и ограничения
    max_amount: Optional[float] = None
    min_amount: Optional[float] = None
    supported_currencies: List[str] = field(default_factory=lambda: ["KGS"])
    
    # Особенности интеграции
    supports_partial_payments: bool = False
    supports_refunds: bool = False
    supports_installments: bool = False
    requires_customer_verification: bool = False
    
    # Мониторинг
    health_check_url: Optional[str] = None
    status_check_interval: int = 300  # секунд
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для JSON"""
        return {
            "bank_code": self.bank_code,
            "bank_type": self.bank_type.value,
            "name": self.name,
            "api_version": self.api_version,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "amount_format": self.amount_format,
            "phone_format": self.phone_format,
            "date_format": self.date_format,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "custom_validators": self.custom_validators,
            "webhook_format": self.webhook_format,
            "webhook_auth_method": self.webhook_auth_method,
            "webhook_retry_attempts": self.webhook_retry_attempts,
            "custom_headers": self.custom_headers,
            "custom_parameters": self.custom_parameters,
            "max_amount": self.max_amount,
            "min_amount": self.min_amount,
            "supported_currencies": self.supported_currencies,
            "supports_partial_payments": self.supports_partial_payments,
            "supports_refunds": self.supports_refunds,
            "supports_installments": self.supports_installments,
            "requires_customer_verification": self.requires_customer_verification,
            "health_check_url": self.health_check_url,
            "status_check_interval": self.status_check_interval
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BankConfiguration':
        """Создание из словаря"""
        bank_type = BankType(data.get("bank_type", "standard"))
        
        return cls(
            bank_code=data["bank_code"],
            bank_type=bank_type,
            name=data["name"],
            api_version=data.get("api_version", "1.0"),
            timeout_seconds=data.get("timeout_seconds", 30),
            max_retries=data.get("max_retries", 3),
            amount_format=data.get("amount_format", "decimal"),
            phone_format=data.get("phone_format", "international"),
            date_format=data.get("date_format", "iso"),
            required_fields=data.get("required_fields", []),
            optional_fields=data.get("optional_fields", []),
            custom_validators=data.get("custom_validators", {}),
            webhook_format=data.get("webhook_format", "standard"),
            webhook_auth_method=data.get("webhook_auth_method", "hmac"),
            webhook_retry_attempts=data.get("webhook_retry_attempts", 5),
            custom_headers=data.get("custom_headers", {}),
            custom_parameters=data.get("custom_parameters", {}),
            max_amount=data.get("max_amount"),
            min_amount=data.get("min_amount"),
            supported_currencies=data.get("supported_currencies", ["KGS"]),
            supports_partial_payments=data.get("supports_partial_payments", False),
            supports_refunds=data.get("supports_refunds", False),
            supports_installments=data.get("supports_installments", False),
            requires_customer_verification=data.get("requires_customer_verification", False),
            health_check_url=data.get("health_check_url"),
            status_check_interval=data.get("status_check_interval", 300)
        )

class BaseBankAdapter(ABC):
    """Базовый класс для адаптеров банков"""
    
    def __init__(self, config: BankConfiguration):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{config.bank_code}")
    
    @abstractmethod
    def format_payment_info(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Форматирование информации о платеже для конкретного банка"""
        pass
    
    @abstractmethod
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация webhook payload от банка"""
        pass
    
    @abstractmethod
    def process_webhook_data(self, payload: Dict[str, Any]) -> PaymentStatusWebhook:
        """Обработка webhook данных в стандартный формат"""
        pass
    
    # Методы для двухфазного протокола
    
    def format_prepare_request(self, request: TransactionPrepareRequest) -> Dict[str, Any]:
        """Форматирование запроса prepare для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def format_commit_request(self, request: TransactionCommitRequest) -> Dict[str, Any]:
        """Форматирование запроса commit для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def format_abort_request(self, request: TransactionAbortRequest) -> Dict[str, Any]:
        """Форматирование запроса abort для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def parse_prepare_response(self, response_data: Dict[str, Any]) -> TransactionPrepareResponse:
        """Парсинг ответа prepare от банка"""
        # Базовая реализация - предполагает стандартный формат
        return TransactionPrepareResponse(**response_data)
    
    def parse_commit_response(self, response_data: Dict[str, Any]) -> TransactionCommitResponse:
        """Парсинг ответа commit от банка"""
        # Базовая реализация - предполагает стандартный формат
        return TransactionCommitResponse(**response_data)
    
    def parse_abort_response(self, response_data: Dict[str, Any]) -> TransactionAbortResponse:
        """Парсинг ответа abort от банка"""
        # Базовая реализация - предполагает стандартный формат
        return TransactionAbortResponse(**response_data)
    
    # Методы для возвратов (двухфазный протокол)
    
    def format_refund_prepare_request(self, request: RefundPrepareRequest) -> Dict[str, Any]:
        """Форматирование запроса prepare возврата для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def format_refund_commit_request(self, request: RefundCommitRequest) -> Dict[str, Any]:
        """Форматирование запроса commit возврата для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def format_refund_abort_request(self, request: RefundAbortRequest) -> Dict[str, Any]:
        """Форматирование запроса abort возврата для конкретного банка"""
        # Базовая реализация - возвращает стандартный формат
        return request.dict()
    
    def parse_refund_prepare_response(self, response_data: Dict[str, Any]) -> RefundPrepareResponse:
        """Парсинг ответа prepare возврата от банка"""
        # Базовая реализация - предполагает стандартный формат
        return RefundPrepareResponse(**response_data)
    
    def parse_refund_commit_response(self, response_data: Dict[str, Any]) -> RefundCommitResponse:
        """Парсинг ответа commit возврата от банка"""
        # Базовая реализация - предполагает стандартный формат
        return RefundCommitResponse(**response_data)
    
    def parse_refund_abort_response(self, response_data: Dict[str, Any]) -> RefundAbortResponse:
        """Парсинг ответа abort возврата от банка"""
        # Базовая реализация - предполагает стандартный формат
        return RefundAbortResponse(**response_data)
    
    # Асинхронные методы для отправки запросов к банкам
    
    async def prepare_refund(self, request: RefundPrepareRequest) -> RefundPrepareResponse:
        """Отправка запроса prepare возврата к банку"""
        
        # Форматируем запрос для банка
        formatted_request = self.format_refund_prepare_request(request)
        
        # Получаем URL эндпоинта
        endpoint_url = self.get_refund_endpoint_url(self.config.base_url, "prepare")
        
        # Получаем заголовки
        headers = self.get_two_phase_headers(self.config.bank if hasattr(self.config, 'bank') else None, "prepare")
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    endpoint_url,
                    json=formatted_request,
                    headers=headers
                )
                
                response.raise_for_status()
                response_data = response.json()
                
                # Парсим ответ
                return self.parse_refund_prepare_response(response_data)
                
        except Exception as e:
            self.logger.error(f"Error sending refund prepare request: {e}")
            raise
    
    async def commit_refund(self, request: RefundCommitRequest) -> RefundCommitResponse:
        """Отправка запроса commit возврата к банку"""
        
        # Форматируем запрос для банка
        formatted_request = self.format_refund_commit_request(request)
        
        # Получаем URL эндпоинта
        endpoint_url = self.get_refund_endpoint_url(self.config.base_url, "commit")
        
        # Получаем заголовки
        headers = self.get_two_phase_headers(self.config.bank if hasattr(self.config, 'bank') else None, "commit")
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    endpoint_url,
                    json=formatted_request,
                    headers=headers
                )
                
                response.raise_for_status()
                response_data = response.json()
                
                # Парсим ответ
                return self.parse_refund_commit_response(response_data)
                
        except Exception as e:
            self.logger.error(f"Error sending refund commit request: {e}")
            raise
    
    async def abort_refund(self, request: RefundAbortRequest) -> RefundAbortResponse:
        """Отправка запроса abort возврата к банку"""
        
        # Форматируем запрос для банка
        formatted_request = self.format_refund_abort_request(request)
        
        # Получаем URL эндпоинта
        endpoint_url = self.get_refund_endpoint_url(self.config.base_url, "abort")
        
        # Получаем заголовки
        headers = self.get_two_phase_headers(self.config.bank if hasattr(self.config, 'bank') else None, "abort")
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    endpoint_url,
                    json=formatted_request,
                    headers=headers
                )
                
                response.raise_for_status()
                response_data = response.json()
                
                # Парсим ответ
                return self.parse_refund_abort_response(response_data)
                
        except Exception as e:
            self.logger.error(f"Error sending refund abort request: {e}")
            raise
    
    def get_refund_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для операций возврата"""
        # Специальная обработка для симулятора - всегда используем localhost
        if base_url and "simulation" in base_url:
            # Для симулятора, всегда используем localhost для избежания проблем с сетью
            base_url = "http://localhost:8000/simulation/bank-api"
            logger.info(f"🔄 Simulator refund: using internal URL {base_url}")
        
        # Для симулятора используем специальные эндпоинты
        if "simulation" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
            endpoint_mapping = {
                "prepare": "/api/v1/banks/refunds/prepare",
                "commit": "/api/v1/banks/refunds/commit", 
                "abort": "/api/v1/banks/refunds/abort"
            }
        else:
            endpoint_mapping = {
                "prepare": "/api/v1/banks/refunds/prepare",
                "commit": "/api/v1/banks/refunds/commit", 
                "abort": "/api/v1/banks/refunds/abort"
            }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/refunds/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def get_two_phase_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для двухфазных операций"""
        endpoint_mapping = {
            "prepare": "/api/v1/banks/transactions/prepare",
            "commit": "/api/v1/banks/transactions/commit", 
            "abort": "/api/v1/banks/transactions/abort"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/transactions/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def get_two_phase_headers(self, bank: Optional[Bank] = None, operation: str = "") -> Dict[str, str]:
        """Получение заголовков для двухфазных операций"""
        headers = { 
            "Content-Type": "application/json",
            "User-Agent": "QRPayHub/1.0 Two-Phase-Commit"
        }
        
        # Добавляем авторизацию, если есть токен
        if bank and hasattr(bank, 'access_token') and bank.access_token:
            headers["Authorization"] = f"Bearer {bank.access_token}"
        
        # Добавляем кастомные заголовки банка
        headers.update(self.get_custom_headers())
        
        return headers
    
    def get_custom_headers(self) -> Dict[str, str]:
        """Получение кастомных заголовков для банка"""
        return self.config.custom_headers
    
    def format_amount(self, amount: float) -> Union[float, int, str]:
        """Форматирование суммы согласно требованиям банка"""
        
        if self.config.amount_format == "integer_kopecks":
            return int(amount * 100)  # Копейки
        elif self.config.amount_format == "string":
            return f"{amount:.2f}"
        else:  # decimal
            return round(amount, 2)
    
    def format_phone(self, phone: Optional[str]) -> Optional[str]:
        """Форматирование номера телефона"""
        
        if not phone:
            return None
        
        # Убираем все нецифровые символы
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        if self.config.phone_format == "international":
            if clean_phone.startswith("996"):
                return f"+{clean_phone}"
            elif len(clean_phone) == 9:
                return f"+996{clean_phone}"
            else:
                return f"+{clean_phone}"
        elif self.config.phone_format == "national":
            if clean_phone.startswith("996"):
                return clean_phone[3:]
            else:
                return clean_phone
        else:  # raw
            return phone
    
    def format_datetime(self, dt: datetime) -> Union[str, int]:
        """Форматирование даты и времени"""
        
        if self.config.date_format == "timestamp":
            return int(dt.timestamp())
        elif self.config.date_format == "custom":
            # Кастомный формат из конфигурации
            custom_format = self.config.custom_parameters.get("date_format", "%Y-%m-%d %H:%M:%S")
            return dt.strftime(custom_format)
        else:  # iso
            return dt.isoformat()
    
    def validate_payment_limits(self, amount: float, currency: str = "KGS") -> List[str]:
        """Проверка лимитов платежа"""
        
        errors = []
        
        if currency not in self.config.supported_currencies:
            errors.append(f"Currency {currency} not supported by bank {self.config.bank_code}")
        
        if self.config.max_amount and amount > self.config.max_amount:
            errors.append(f"Amount {amount} exceeds maximum {self.config.max_amount}")
        
        if self.config.min_amount and amount < self.config.min_amount:
            errors.append(f"Amount {amount} below minimum {self.config.min_amount}")
        
        return errors
    
    def get_custom_headers(self) -> Dict[str, str]:
        """Получение кастомных заголовков для банка"""
        return self.config.custom_headers.copy()
    
    def log_bank_interaction(self, operation: str, data: Dict[str, Any], success: bool = True):
        """Логирование взаимодействия с банком"""
        
        log_data = {
            "bank_code": self.config.bank_code,
            "operation": operation,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        
        if success:
            self.logger.info(f"Bank interaction successful: {operation}", extra=log_data)
        else:
            self.logger.warning(f"Bank interaction failed: {operation}", extra=log_data)

class StandardBankAdapter(BaseBankAdapter):
    """Стандартный адаптер для большинства банков"""
    
    def format_payment_info(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Стандартное форматирование информации о платеже"""
        
        return {
            "receiver_account": payment_request.receiver_account,
            "receiver_bank_code": payment_request.receiver_bank_code,
            "receiver_name": payment_request.receiver_name,
            "description": payment_request.description,
            "amount": self.format_amount(payment_request.amount) if payment_request.amount else None,
            "currency": payment_request.currency,
            "payment_reference": payment_request.payment_reference
        }
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Стандартная валидация webhook"""
        
        result = {"valid": True, "errors": []}
        
        required_fields = ["token", "status", "transaction_id"]
        
        for field in required_fields:
            if field not in payload:
                result["valid"] = False
                result["errors"].append(f"Missing required field: {field}")
        
        return result
    
    def process_webhook_data(self, payload: Dict[str, Any]) -> PaymentStatusWebhook:
        """Стандартная обработка webhook данных"""
        
        return PaymentStatusWebhook(
            token=payload["token"],
            status=payload["status"],
            transaction_id=payload["transaction_id"],
            amount=payload.get("amount"),
            payer_phone=self.format_phone(payload.get("payer_phone")),
            timestamp=payload.get("timestamp", datetime.now().isoformat())
        )


class SimulationBankAdapter(BaseBankAdapter):
    """Адаптер для симулятора банков"""
    
    def __init__(self, config: BankConfiguration):
        super().__init__(config)
        # Для симулятора используем относительные пути
        self.config.base_url = ""
    
    def get_two_phase_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для двухфазных операций симулятора"""
        # Для симулятора используем специальные эндпоинты
        endpoint_mapping = {
            "prepare": "/api/v1/banks/transactions/prepare",
            "commit": "/api/v1/banks/transactions/commit", 
            "abort": "/api/v1/banks/transactions/abort"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/transactions/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def get_refund_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для операций возврата симулятора"""
        # Для симулятора используем специальные эндпоинты
        endpoint_mapping = {
            "prepare": "/api/v1/banks/refunds/prepare",
            "commit": "/api/v1/banks/refunds/commit", 
            "abort": "/api/v1/banks/refunds/abort"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/refunds/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def format_payment_info(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Форматирование информации о платеже для симулятора"""
        return {
            "receiver_account": payment_request.receiver_account,
            "receiver_bank_code": payment_request.receiver_bank_code,
            "receiver_name": payment_request.receiver_name,
            "description": payment_request.description,
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "payment_reference": payment_request.payment_reference
        }
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация webhook payload от симулятора"""
        return {"valid": True, "errors": []}
    
    def process_webhook_data(self, payload: Dict[str, Any]) -> PaymentStatusWebhook:
        """Обработка webhook данных от симулятора"""
        return PaymentStatusWebhook(**payload)

class LegacyBankAdapter(BaseBankAdapter):
    """Адаптер для устаревших банковских систем"""
    
    def format_payment_info(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Форматирование для устаревших систем"""
        
        # Устаревшие системы часто требуют другие названия полей
        return {
            "account_number": payment_request.receiver_account,
            "bank_id": payment_request.receiver_bank_code,
            "beneficiary_name": payment_request.receiver_name,
            "payment_purpose": payment_request.description,
            "sum": self.format_amount(payment_request.amount) if payment_request.amount else None,
            "currency_code": payment_request.currency,
            "reference_number": payment_request.payment_reference
        }
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация для устаревших систем"""
        
        result = {"valid": True, "errors": []}
        
        # Устаревшие системы могут использовать другие названия полей
        legacy_mapping = {
            "payment_token": "token",
            "payment_status": "status", 
            "transaction_number": "transaction_id"
        }
        
        for legacy_field, standard_field in legacy_mapping.items():
            if legacy_field in payload:
                payload[standard_field] = payload[legacy_field]
        
        return super().validate_webhook_payload(payload)
    
    def process_webhook_data(self, payload: Dict[str, Any]) -> PaymentStatusWebhook:
        """Обработка данных от устаревших систем"""
        
        # Преобразуем устаревшие поля в стандартные
        if "payment_token" in payload:
            payload["token"] = payload["payment_token"]
        if "payment_status" in payload:
            payload["status"] = payload["payment_status"]
        if "transaction_number" in payload:
            payload["transaction_id"] = payload["transaction_number"]
        
        return super().process_webhook_data(payload)
    
    # Переопределяем методы двухфазного протокола для устаревших систем
    
    def format_prepare_request(self, request: TransactionPrepareRequest) -> Dict[str, Any]:
        """Форматирование prepare запроса для устаревших систем"""
        
        # Устаревшие системы используют другие названия полей
        formatted = {
            "transaction_number": request.transaction_id,
            "payment_token": request.payment_token,
            "sum": self.format_amount(request.amount),
            "currency_code": request.currency,
            "account_number": request.receiver_account,
            "beneficiary_name": request.receiver_name,
            "payment_purpose": request.description,
            "reference_number": request.payment_reference,
            "operation_type": "reserve" if request.bank_role.value == "sender" else "check",
            "timeout_sec": request.timeout_seconds or 300
        }
        
        # Добавляем данные отправителя если есть
        if request.sender_account:
            formatted["sender_account"] = request.sender_account
        if request.sender_phone:
            formatted["payer_phone"] = self.format_phone(request.sender_phone)
        
        return formatted
    
    def format_commit_request(self, request: TransactionCommitRequest) -> Dict[str, Any]:
        """Форматирование commit запроса для устаревших систем"""
        
        return {
            "transaction_number": request.transaction_id,
            "payment_token": request.payment_token,
            "operation_type": "execute" if request.bank_role.value == "sender" else "receive",
            "amount": self.format_amount(request.prepared_amount),
            "reservation_ref": request.reservation_id
        }
    
    def format_abort_request(self, request: TransactionAbortRequest) -> Dict[str, Any]:
        """Форматирование abort запроса для устаревших систем"""
        
        return {
            "transaction_number": request.transaction_id,
            "payment_token": request.payment_token,
            "operation_type": "cancel",
            "cancel_reason": request.abort_reason or "Transaction aborted",
            "reservation_ref": request.reservation_id
        }
    
    def parse_prepare_response(self, response_data: Dict[str, Any]) -> TransactionPrepareResponse:
        """Парсинг prepare ответа от устаревших систем"""
        
        # Преобразуем устаревшие поля в стандартные
        status_mapping = {
            "reserved": "prepared",
            "confirmed": "prepared", 
            "rejected": "aborted",
            "failed": "error"
        }
        
        status = status_mapping.get(response_data.get("status", "error"), "error")
        
        return TransactionPrepareResponse(
            status=status,
            transaction_id=response_data.get("transaction_number", ""),
            message=response_data.get("message"),
            reserved_amount=response_data.get("reserved_sum"),
            reservation_id=response_data.get("reservation_ref"),
            error_code=response_data.get("error_code"),
            error_details=response_data.get("error_details")
        )
    
    def get_two_phase_endpoint_url(self, base_url: str, operation: str) -> str:
        """URL эндпоинтов для устаревших систем"""
        
        # Устаревшие системы используют другие пути
        endpoint_mapping = {
            "prepare": "/legacy/payment/reserve",
            "commit": "/legacy/payment/execute",
            "abort": "/legacy/payment/cancel"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/legacy/payment/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"

class MobileBankAdapter(BaseBankAdapter):
    """Адаптер для мобильных банков"""
    
    def format_payment_info(self, payment_request: PaymentRequest) -> Dict[str, Any]:
        """Форматирование для мобильных банков"""
        
        # Мобильные банки предпочитают краткие поля
        result = {
            "to_account": payment_request.receiver_account,
            "to_bank": payment_request.receiver_bank_code,
            "to_name": payment_request.receiver_name,
            "memo": payment_request.description,
            "amount": self.format_amount(payment_request.amount) if payment_request.amount else None,
            "currency": payment_request.currency,
            "ref": payment_request.payment_reference
        }
        
        # Добавляем мобильные-специфичные поля
        result.update({
            "mobile_optimized": True,
            "ui_hints": {
                "show_amount_input": payment_request.amount is None,
                "suggest_recent_amounts": True
            }
        })
        
        return result
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация для мобильных банков"""
        
        result = super().validate_webhook_payload(payload)
        
        # Мобильные банки часто добавляют дополнительную информацию
        if "device_info" in payload:
            # Логируем информацию об устройстве для аналитики
            device_info = payload["device_info"]
            self.logger.info(f"Mobile payment from {device_info.get('platform', 'unknown')}")
        
        return result
    
    def process_webhook_data(self, payload: Dict[str, Any]) -> PaymentStatusWebhook:
        """Обработка данных от мобильных банков"""
        
        webhook_data = super().process_webhook_data(payload)
        
        # Мобильные банки могут предоставить дополнительную информацию
        if hasattr(webhook_data, '__dict__'):
            if "device_info" in payload:
                webhook_data.__dict__["device_info"] = payload["device_info"]
            if "app_version" in payload:
                webhook_data.__dict__["app_version"] = payload["app_version"]
        
        return webhook_data

class BankAdapterService:
    """Сервис для управления адаптерами банков"""
    
    # Регистрация адаптеров
    ADAPTER_REGISTRY: Dict[BankType, Type[BaseBankAdapter]] = {
        BankType.STANDARD: StandardBankAdapter,
        BankType.LEGACY: LegacyBankAdapter,
        BankType.MOBILE_FIRST: MobileBankAdapter,
        BankType.ENTERPRISE: StandardBankAdapter,  # Пока используем стандартный
        BankType.FINTECH: MobileBankAdapter,       # Похож на мобильный
        BankType.CUSTOM: StandardBankAdapter       # Базовый для кастомных
    }
    
    def __init__(self):
        self._adapters: Dict[str, BaseBankAdapter] = {}
        self._configurations: Dict[str, BankConfiguration] = {}
    
    def register_bank_configuration(self, config: BankConfiguration):
        """Регистрация конфигурации банка"""
        
        self._configurations[config.bank_code] = config
        
        # Создаем адаптер для банка
        adapter_class = self.ADAPTER_REGISTRY.get(config.bank_type, StandardBankAdapter)
        self._adapters[config.bank_code] = adapter_class(config)
        
        logger.info(f"Registered adapter for bank {config.bank_code} (type: {config.bank_type.value})")
    
    def get_adapter(self, bank_code: str) -> Optional[BaseBankAdapter]:
        """Получение адаптера для банка"""
        # Для всех банков используем симулятор
        if bank_code not in self._adapters:
            # Создаем конфигурацию для симулятора
            config = BankConfiguration(
                bank_code=bank_code,
                bank_type=BankType.STANDARD,
                name=f"Simulation Bank {bank_code}",
                base_url=""
            )
            self._adapters[bank_code] = SimulationBankAdapter(config)
            logger.info(f"Created simulation adapter for bank {bank_code}")
        
        return self._adapters.get(bank_code)
    
    def get_configuration(self, bank_code: str) -> Optional[BankConfiguration]:
        """Получение конфигурации банка"""
        return self._configurations.get(bank_code)
    
    def format_payment_info_for_bank(
        self, 
        bank_code: str, 
        payment_request: PaymentRequest
    ) -> Dict[str, Any]:
        """Форматирование информации о платеже для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            # Если адаптер не найден, используем стандартный формат
            logger.warning(f"No adapter found for bank {bank_code}, using standard format")
            return {
                "receiver_account": payment_request.receiver_account,
                "receiver_bank_code": payment_request.receiver_bank_code,
                "receiver_name": payment_request.receiver_name,
                "description": payment_request.description,
                "amount": payment_request.amount,
                "currency": payment_request.currency,
                "payment_reference": payment_request.payment_reference
            }
        
        try:
            formatted_data = adapter.format_payment_info(payment_request)
            adapter.log_bank_interaction("format_payment_info", formatted_data, True)
            return formatted_data
        except Exception as e:
            logger.error(f"Error formatting payment info for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_payment_info", {"error": str(e)}, False)
            raise
    
    def process_webhook_for_bank(
        self, 
        bank_code: str, 
        payload: Dict[str, Any]
    ) -> PaymentStatusWebhook:
        """Обработка webhook от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard processing")
            # Стандартная обработка
            return PaymentStatusWebhook(**payload)
        
        try:
            # Валидация payload
            validation_result = adapter.validate_webhook_payload(payload)
            if not validation_result["valid"]:
                errors = validation_result["errors"]
                logger.error(f"Webhook validation failed for bank {bank_code}: {errors}")
                raise ValueError(f"Webhook validation failed: {'; '.join(errors)}")
            
            # Обработка данных
            webhook_data = adapter.process_webhook_data(payload)
            adapter.log_bank_interaction("process_webhook", payload, True)
            
            return webhook_data
            
        except Exception as e:
            logger.error(f"Error processing webhook for bank {bank_code}: {e}")
            adapter.log_bank_interaction("process_webhook", {"error": str(e)}, False)
            raise
    
    def validate_payment_for_bank(
        self, 
        bank_code: str, 
        amount: float, 
        currency: str = "KGS"
    ) -> List[str]:
        """Валидация платежа для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            return []  # Нет специфичных ограничений
        
        return adapter.validate_payment_limits(amount, currency)
    
    def get_bank_capabilities(self, bank_code: str) -> Dict[str, Any]:
        """Получение возможностей банка"""
        
        config = self.get_configuration(bank_code)
        if not config:
            return {"error": "Bank configuration not found"}
        
        return {
            "bank_code": bank_code,
            "bank_type": config.bank_type.value,
            "supported_currencies": config.supported_currencies,
            "amount_limits": {
                "min": config.min_amount,
                "max": config.max_amount
            },
            "features": {
                "partial_payments": config.supports_partial_payments,
                "refunds": config.supports_refunds,
                "installments": config.supports_installments,
                "customer_verification": config.requires_customer_verification
            },
            "api_info": {
                "version": config.api_version,
                "timeout": config.timeout_seconds,
                "max_retries": config.max_retries
            }
        }
    
    def get_all_registered_banks(self) -> List[Dict[str, Any]]:
        """Получение списка всех зарегистрированных банков"""
        
        result = []
        for bank_code, config in self._configurations.items():
            result.append({
                "bank_code": bank_code,
                "name": config.name,
                "type": config.bank_type.value,
                "api_version": config.api_version,
                "has_adapter": bank_code in self._adapters
            })
        
        return result
    
    def create_default_configurations(self) -> List[BankConfiguration]:
        """Создание конфигураций по умолчанию для тестирования"""
        
        default_configs = [
            BankConfiguration(
                bank_code="DEMO001",
                bank_type=BankType.STANDARD,
                name="Demo Standard Bank",
                required_fields=["receiver_account", "amount"],
                max_amount=1000000.0,
                min_amount=1.0
            ),
            BankConfiguration(
                bank_code="MOBILE001", 
                bank_type=BankType.MOBILE_FIRST,
                name="Demo Mobile Bank",
                phone_format="international",
                amount_format="decimal",
                custom_parameters={"ui_theme": "mobile"}
            ),
            BankConfiguration(
                bank_code="LEGACY001",
                bank_type=BankType.LEGACY,
                name="Demo Legacy Bank",
                api_version="0.9",
                amount_format="integer_kopecks",
                date_format="custom",
                custom_parameters={"date_format": "%d.%m.%Y %H:%M"}
            )
        ]
        
        # Регистрируем все конфигурации
        for config in default_configs:
            self.register_bank_configuration(config)
        
        return default_configs
    
    # Методы для двухфазного протокола
    
    def format_prepare_request_for_bank(
        self, 
        bank_code: str, 
        request: TransactionPrepareRequest
    ) -> Dict[str, Any]:
        """Форматирование prepare запроса для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for prepare request")
            return request.dict()
        
        try:
            formatted_data = adapter.format_prepare_request(request)
            adapter.log_bank_interaction("format_prepare_request", formatted_data, True)
            return formatted_data
        except Exception as e:
            logger.error(f"Error formatting prepare request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_prepare_request", {"error": str(e)}, False)
            raise
    
    def format_commit_request_for_bank(
        self, 
        bank_code: str, 
        request: TransactionCommitRequest
    ) -> Dict[str, Any]:
        """Форматирование commit запроса для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for commit request")
            return request.dict()
        
        try:
            formatted_data = adapter.format_commit_request(request)
            adapter.log_bank_interaction("format_commit_request", formatted_data, True)
            return formatted_data
        except Exception as e:
            logger.error(f"Error formatting commit request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_commit_request", {"error": str(e)}, False)
            raise
    
    def format_abort_request_for_bank(
        self, 
        bank_code: str, 
        request: TransactionAbortRequest
    ) -> Dict[str, Any]:
        """Форматирование abort запроса для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for abort request")
            return request.dict()
        
        try:
            formatted_data = adapter.format_abort_request(request)
            adapter.log_bank_interaction("format_abort_request", formatted_data, True)
            return formatted_data
        except Exception as e:
            logger.error(f"Error formatting abort request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_abort_request", {"error": str(e)}, False)
            raise
    
    def parse_prepare_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> TransactionPrepareResponse:
        """Парсинг prepare ответа от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for prepare response")
            return TransactionPrepareResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_prepare_response(response_data)
            adapter.log_bank_interaction("parse_prepare_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing prepare response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_prepare_response", {"error": str(e)}, False)
            raise
    
    def parse_commit_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> TransactionCommitResponse:
        """Парсинг commit ответа от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for commit response")
            return TransactionCommitResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_commit_response(response_data)
            adapter.log_bank_interaction("parse_commit_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing commit response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_commit_response", {"error": str(e)}, False)
            raise
    
    def parse_abort_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> TransactionAbortResponse:
        """Парсинг abort ответа от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for abort response")
            return TransactionAbortResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_abort_response(response_data)
            adapter.log_bank_interaction("parse_abort_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing abort response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_abort_response", {"error": str(e)}, False)
            raise
    
    def get_two_phase_endpoint_for_bank(
        self, 
        bank_code: str, 
        base_url: str, 
        operation: str
    ) -> str:
        """Получение URL эндпоинта двухфазной операции для конкретного банка"""
        
        # Специальная логика для симулятора
        if "simulation" in base_url or "localhost" in base_url:
            endpoint_mapping = {
                "prepare": "/api/v1/banks/transactions/prepare",
                "commit": "/api/v1/banks/transactions/commit",
                "abort": "/api/v1/banks/transactions/abort"
            }
            endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/transactions/{operation}")
            return f"{base_url.rstrip('/')}{endpoint}"
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            # Стандартные эндпоинты для реальных банков
            endpoint_mapping = {
                "prepare": "/api/v1/banks/transactions/prepare",
                "commit": "/api/v1/banks/transactions/commit",
                "abort": "/api/v1/banks/transactions/abort"
            }
            endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/transactions/{operation}")
            return f"{base_url.rstrip('/')}{endpoint}"
        
        return adapter.get_two_phase_endpoint_url(base_url, operation)
    
    def get_two_phase_headers_for_bank(
        self, 
        bank_code: str, 
        bank: Bank, 
        operation: str
    ) -> Dict[str, str]:
        """Получение заголовков для двухфазной операции конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            # Стандартные заголовки
            return {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bank.access_token}",
                "User-Agent": "QRPayHub/1.0 Two-Phase-Commit"
            }
        
        return adapter.get_two_phase_headers(bank, operation)
    
    # Методы для возвратов
    
    def format_refund_prepare_request_for_bank(
        self, 
        bank_code: str, 
        request: RefundPrepareRequest
    ) -> Dict[str, Any]:
        """Форматирование запроса prepare возврата для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund prepare request")
            return request.dict()
        
        try:
            formatted_request = adapter.format_refund_prepare_request(request)
            adapter.log_bank_interaction("format_refund_prepare_request", request.dict(), True)
            return formatted_request
        except Exception as e:
            logger.error(f"Error formatting refund prepare request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_refund_prepare_request", {"error": str(e)}, False)
            raise
    
    def format_refund_commit_request_for_bank(
        self, 
        bank_code: str, 
        request: RefundCommitRequest
    ) -> Dict[str, Any]:
        """Форматирование запроса commit возврата для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund commit request")
            return request.dict()
        
        try:
            formatted_request = adapter.format_refund_commit_request(request)
            adapter.log_bank_interaction("format_refund_commit_request", request.dict(), True)
            return formatted_request
        except Exception as e:
            logger.error(f"Error formatting refund commit request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_refund_commit_request", {"error": str(e)}, False)
            raise
    
    def format_refund_abort_request_for_bank(
        self, 
        bank_code: str, 
        request: RefundAbortRequest
    ) -> Dict[str, Any]:
        """Форматирование запроса abort возврата для конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund abort request")
            return request.dict()
        
        try:
            formatted_request = adapter.format_refund_abort_request(request)
            adapter.log_bank_interaction("format_refund_abort_request", request.dict(), True)
            return formatted_request
        except Exception as e:
            logger.error(f"Error formatting refund abort request for bank {bank_code}: {e}")
            adapter.log_bank_interaction("format_refund_abort_request", {"error": str(e)}, False)
            raise
    
    def parse_refund_prepare_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> RefundPrepareResponse:
        """Парсинг ответа prepare возврата от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund prepare response")
            return RefundPrepareResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_refund_prepare_response(response_data)
            adapter.log_bank_interaction("parse_refund_prepare_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing refund prepare response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_refund_prepare_response", {"error": str(e)}, False)
            raise
    
    def parse_refund_commit_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> RefundCommitResponse:
        """Парсинг ответа commit возврата от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund commit response")
            return RefundCommitResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_refund_commit_response(response_data)
            adapter.log_bank_interaction("parse_refund_commit_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing refund commit response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_refund_commit_response", {"error": str(e)}, False)
            raise
    
    def parse_refund_abort_response_from_bank(
        self, 
        bank_code: str, 
        response_data: Dict[str, Any]
    ) -> RefundAbortResponse:
        """Парсинг ответа abort возврата от конкретного банка"""
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            logger.warning(f"No adapter found for bank {bank_code}, using standard format for refund abort response")
            return RefundAbortResponse(**response_data)
        
        try:
            parsed_response = adapter.parse_refund_abort_response(response_data)
            adapter.log_bank_interaction("parse_refund_abort_response", response_data, True)
            return parsed_response
        except Exception as e:
            logger.error(f"Error parsing refund abort response from bank {bank_code}: {e}")
            adapter.log_bank_interaction("parse_refund_abort_response", {"error": str(e)}, False)
            raise
    
    def get_refund_endpoint_for_bank(
        self, 
        bank_code: str, 
        base_url: str, 
        operation: str
    ) -> str:
        """Получение URL эндпоинта операции возврата для конкретного банка"""
        
        # Специальная обработка для симулятора - всегда используем localhost
        if base_url and "simulation" in base_url:
            # Для симулятора, всегда используем localhost для избежания проблем с сетью
            base_url = "http://localhost:8000/simulation/bank-api"
            logger.info(f"🔄 Simulator refund endpoint: using internal URL {base_url}")
        
        adapter = self.get_adapter(bank_code)
        if not adapter:
            # Стандартные эндпоинты для возвратов
            endpoint_mapping = {
                "prepare": "/api/v1/banks/refunds/prepare",
                "commit": "/api/v1/banks/refunds/commit",
                "abort": "/api/v1/banks/refunds/abort"
            }
            endpoint = endpoint_mapping.get(operation, f"/api/v1/banks/refunds/{operation}")
            return f"{base_url.rstrip('/')}{endpoint}"
        
        return adapter.get_refund_endpoint_url(base_url, operation)

# Глобальный экземпляр сервиса адаптеров
bank_adapter_service = BankAdapterService()

# Экспорт основных классов
__all__ = [
    "BaseBankAdapter",
    "StandardBankAdapter", 
    "LegacyBankAdapter",
    "MobileBankAdapter",
    "BankAdapterService",
    "BankConfiguration",
    "BankType",
    "bank_adapter_service"
]
