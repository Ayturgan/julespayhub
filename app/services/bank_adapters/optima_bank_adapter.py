"""
Адаптер для OptimaBank с поддержкой возвратов
"""

from typing import Dict, Any
from app.services.bank_adapter_service import StandardBankAdapter, BankConfiguration, BankType
from app.models.unified import UnifiedPayment
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

class OptimaBankAdapter(StandardBankAdapter):
    """Адаптер для OptimaBank с поддержкой возвратов"""
    
    def __init__(self, config: BankConfiguration):
        super().__init__(config)
        # OptimaBank поддерживает возвраты
        self.config.supports_refunds = True
    
    def format_payment_info(self, payment_request: UnifiedPayment) -> Dict[str, Any]:
        """Форматирование информации о платеже для OptimaBank"""
        
        # OptimaBank использует стандартный формат с дополнительными полями
        base_info = super().format_payment_info(payment_request)
        
        # Добавляем специфичные для OptimaBank поля
        base_info.update({
            "bank_code": "OPTIMA",
            "payment_type": "qr_payment",
            "source": "qrpayhub"
        })
        
        return base_info
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация webhook от OptimaBank"""
        
        result = super().validate_webhook_payload(payload)
        
        # OptimaBank добавляет дополнительные поля
        if "optima_transaction_id" in payload:
            # Логируем внутренний ID транзакции OptimaBank
            self.logger.info(f"OptimaBank transaction ID: {payload['optima_transaction_id']}")
        
        return result
    
    def process_webhook_data(self, payload: Dict[str, Any]):
        """Обработка webhook данных от OptimaBank"""
        
        # OptimaBank может использовать другие названия полей
        if "optima_transaction_id" in payload and "transaction_id" not in payload:
            payload["transaction_id"] = payload["optima_transaction_id"]
        
        return super().process_webhook_data(payload)
    
    # Методы для двухфазного протокола возвратов
    
    def format_refund_prepare_request(self, request: RefundPrepareRequest) -> Dict[str, Any]:
        """Форматирование запроса prepare возврата для OptimaBank"""
        
        # OptimaBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_prepare_request(request)
        
        # Добавляем специфичные для OptimaBank поля возврата
        base_request.update({
            "bank_code": "OPTIMA",
            "operation_type": "refund_prepare",
            "source": "qrpayhub",
            "refund_reason": request.reason,
            "original_payment_id": request.original_payment_id
        })
        
        # OptimaBank требует дополнительную информацию о возврате
        if request.bank_role == "sender":
            base_request.update({
                "sender_account": request.sender_account,
                "sender_phone": request.sender_phone
            })
        else:
            base_request.update({
                "receiver_phone": request.receiver_phone
            })
        
        return base_request
    
    def format_refund_commit_request(self, request: RefundCommitRequest) -> Dict[str, Any]:
        """Форматирование запроса commit возврата для OptimaBank"""
        
        # OptimaBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_commit_request(request)
        
        # Добавляем специфичные для OptimaBank поля
        base_request.update({
            "bank_code": "OPTIMA",
            "operation_type": "refund_commit",
            "source": "qrpayhub"
        })
        
        return base_request
    
    def format_refund_abort_request(self, request: RefundAbortRequest) -> Dict[str, Any]:
        """Форматирование запроса abort возврата для OptimaBank"""
        
        # OptimaBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_abort_request(request)
        
        # Добавляем специфичные для OptimaBank поля
        base_request.update({
            "bank_code": "OPTIMA",
            "operation_type": "refund_abort",
            "source": "qrpayhub",
            "abort_reason": request.abort_reason
        })
        
        return base_request
    
    def parse_refund_prepare_response(self, response_data: Dict[str, Any]) -> RefundPrepareResponse:
        """Парсинг ответа prepare возврата от OptimaBank"""
        
        # OptimaBank может возвращать дополнительные поля
        if "optima_reservation_id" in response_data:
            response_data["reservation_id"] = response_data["optima_reservation_id"]
        
        if "optima_reserved_amount" in response_data:
            response_data["reserved_amount"] = response_data["optima_reserved_amount"]
        
        return super().parse_refund_prepare_response(response_data)
    
    def parse_refund_commit_response(self, response_data: Dict[str, Any]) -> RefundCommitResponse:
        """Парсинг ответа commit возврата от OptimaBank"""
        
        # OptimaBank может возвращать дополнительные поля
        if "optima_transaction_id" in response_data:
            response_data["bank_transaction_id"] = response_data["optima_transaction_id"]
        
        if "optima_actual_amount" in response_data:
            response_data["actual_amount"] = response_data["optima_actual_amount"]
        
        return super().parse_refund_commit_response(response_data)
    
    def parse_refund_abort_response(self, response_data: Dict[str, Any]) -> RefundAbortResponse:
        """Парсинг ответа abort возврата от OptimaBank"""
        
        # OptimaBank может возвращать дополнительные поля
        if "optima_released_amount" in response_data:
            response_data["released_amount"] = response_data["optima_released_amount"]
        
        return super().parse_refund_abort_response(response_data)
    
    def get_refund_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для операций возврата OptimaBank"""
        
        # OptimaBank использует специальные эндпоинты для возвратов
        endpoint_mapping = {
            "prepare": "/api/v2/refunds/prepare",
            "commit": "/api/v2/refunds/commit",
            "abort": "/api/v2/refunds/abort"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v2/refunds/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def get_two_phase_headers(self, bank, operation: str) -> Dict[str, str]:
        """Получение заголовков для OptimaBank"""
        
        headers = super().get_two_phase_headers(bank, operation)
        
        # OptimaBank требует дополнительные заголовки
        headers.update({
            "X-Bank-Code": "OPTIMA",
            "X-Operation-Type": operation,
            "X-Source": "qrpayhub"
        })
        
        return headers

# Конфигурация по умолчанию для OptimaBank
def create_optima_bank_configuration() -> BankConfiguration:
    """Создание конфигурации по умолчанию для OptimaBank"""
    
    return BankConfiguration(
        bank_code="OPTIMA",
        bank_type=BankType.STANDARD,
        name="OptimaBank",
        api_version="2.0",
        timeout_seconds=45,
        max_retries=3,
        amount_format="decimal",
        phone_format="international",
        date_format="iso",
        required_fields=["receiver_account", "amount", "currency"],
        optional_fields=["description", "payment_reference"],
        webhook_format="standard",
        webhook_auth_method="hmac",
        webhook_retry_attempts=5,
        custom_headers={
            "X-Bank-Code": "OPTIMA",
            "X-Source": "qrpayhub"
        },
        custom_parameters={
            "supports_refunds": True,
            "refund_timeout_seconds": 60,
            "max_refund_amount": 100000.0
        },
        max_amount=1000000.0,
        min_amount=1.0,
        supported_currencies=["KGS", "USD", "EUR"],
        supports_partial_payments=True,
        supports_refunds=True,
        supports_installments=False,
        requires_customer_verification=False,
        health_check_url="/api/v2/health",
        status_check_interval=300
    )
