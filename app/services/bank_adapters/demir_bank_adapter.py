"""
Адаптер для DemirBank с поддержкой возвратов
"""

from typing import Dict, Any
from app.services.bank_adapter_service import StandardBankAdapter, BankConfiguration, BankType
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

class DemirBankAdapter(StandardBankAdapter):
    """Адаптер для DemirBank с поддержкой возвратов"""
    
    def __init__(self, config: BankConfiguration):
        super().__init__(config)
        # DemirBank поддерживает возвраты
        self.config.supports_refunds = True
    
    def format_payment_info(self, payment_request) -> Dict[str, Any]:
        """Форматирование информации о платеже для DemirBank"""
        
        # DemirBank использует стандартный формат с дополнительными полями
        base_info = super().format_payment_info(payment_request)
        
        # Добавляем специфичные для DemirBank поля
        base_info.update({
            "bank_code": "DEMIR",
            "payment_type": "qr_transfer",
            "source": "qrpayhub",
            "demir_channel": "api"
        })
        
        return base_info
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация webhook от DemirBank"""
        
        result = super().validate_webhook_payload(payload)
        
        # DemirBank добавляет дополнительные поля
        if "demir_reference" in payload:
            # Логируем внутренний референс DemirBank
            self.logger.info(f"DemirBank reference: {payload['demir_reference']}")
        
        return result
    
    def process_webhook_data(self, payload: Dict[str, Any]):
        """Обработка webhook данных от DemirBank"""
        
        # DemirBank может использовать другие названия полей
        if "demir_reference" in payload and "transaction_id" not in payload:
            payload["transaction_id"] = payload["demir_reference"]
        
        if "demir_status" in payload and "status" not in payload:
            payload["status"] = payload["demir_status"]
        
        return super().process_webhook_data(payload)
    
    # Методы для двухфазного протокола возвратов
    
    def format_refund_prepare_request(self, request: RefundPrepareRequest) -> Dict[str, Any]:
        """Форматирование запроса prepare возврата для DemirBank"""
        
        # DemirBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_prepare_request(request)
        
        # Добавляем специфичные для DemirBank поля возврата
        base_request.update({
            "bank_code": "DEMIR",
            "operation_type": "refund_prepare",
            "source": "qrpayhub",
            "demir_channel": "api",
            "refund_reason": request.reason,
            "original_payment_id": request.original_payment_id
        })
        
        # DemirBank требует дополнительную информацию о возврате
        if request.bank_role == "sender":
            base_request.update({
                "sender_account": request.sender_account,
                "sender_phone": request.sender_phone,
                "sender_name": request.sender_name
            })
        else:
            base_request.update({
                "receiver_phone": request.receiver_phone,
                "receiver_name": request.receiver_name
            })
        
        return base_request
    
    def format_refund_commit_request(self, request: RefundCommitRequest) -> Dict[str, Any]:
        """Форматирование запроса commit возврата для DemirBank"""
        
        # DemirBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_commit_request(request)
        
        # Добавляем специфичные для DemirBank поля
        base_request.update({
            "bank_code": "DEMIR",
            "operation_type": "refund_commit",
            "source": "qrpayhub",
            "demir_channel": "api"
        })
        
        return base_request
    
    def format_refund_abort_request(self, request: RefundAbortRequest) -> Dict[str, Any]:
        """Форматирование запроса abort возврата для DemirBank"""
        
        # DemirBank использует стандартный формат с дополнительными полями
        base_request = super().format_refund_abort_request(request)
        
        # Добавляем специфичные для DemirBank поля
        base_request.update({
            "bank_code": "DEMIR",
            "operation_type": "refund_abort",
            "source": "qrpayhub",
            "demir_channel": "api",
            "abort_reason": request.abort_reason
        })
        
        return base_request
    
    def parse_refund_prepare_response(self, response_data: Dict[str, Any]) -> RefundPrepareResponse:
        """Парсинг ответа prepare возврата от DemirBank"""
        
        # DemirBank может возвращать дополнительные поля
        if "demir_reservation_id" in response_data:
            response_data["reservation_id"] = response_data["demir_reservation_id"]
        
        if "demir_reserved_amount" in response_data:
            response_data["reserved_amount"] = response_data["demir_reserved_amount"]
        
        if "demir_currency_rate" in response_data:
            response_data["currency_rate"] = response_data["demir_currency_rate"]
        
        return super().parse_refund_prepare_response(response_data)
    
    def parse_refund_commit_response(self, response_data: Dict[str, Any]) -> RefundCommitResponse:
        """Парсинг ответа commit возврата от DemirBank"""
        
        # DemirBank может возвращать дополнительные поля
        if "demir_reference" in response_data:
            response_data["bank_transaction_id"] = response_data["demir_reference"]
        
        if "demir_actual_amount" in response_data:
            response_data["actual_amount"] = response_data["demir_actual_amount"]
        
        if "demir_fee_amount" in response_data:
            response_data["fee_amount"] = response_data["demir_fee_amount"]
        
        return super().parse_refund_commit_response(response_data)
    
    def parse_refund_abort_response(self, response_data: Dict[str, Any]) -> RefundAbortResponse:
        """Парсинг ответа abort возврата от DemirBank"""
        
        # DemirBank может возвращать дополнительные поля
        if "demir_released_amount" in response_data:
            response_data["released_amount"] = response_data["demir_released_amount"]
        
        if "demir_abort_fee" in response_data:
            response_data["abort_fee"] = response_data["demir_abort_fee"]
        
        return super().parse_refund_abort_response(response_data)
    
    def get_refund_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для операций возврата DemirBank"""
        
        # DemirBank использует специальные эндпоинты для возвратов
        endpoint_mapping = {
            "prepare": "/api/v1/refunds/prepare",
            "commit": "/api/v1/refunds/commit",
            "abort": "/api/v1/refunds/abort"
        }
        
        endpoint = endpoint_mapping.get(operation, f"/api/v1/refunds/{operation}")
        return f"{base_url.rstrip('/')}{endpoint}"
    
    def get_two_phase_headers(self, bank, operation: str) -> Dict[str, str]:
        """Получение заголовков для DemirBank"""
        
        headers = super().get_two_phase_headers(bank, operation)
        
        # DemirBank требует дополнительные заголовки
        headers.update({
            "X-Bank-Code": "DEMIR",
            "X-Operation-Type": operation,
            "X-Source": "qrpayhub",
            "X-Channel": "api"
        })
        
        return headers

# Конфигурация по умолчанию для DemirBank
def create_demir_bank_configuration() -> BankConfiguration:
    """Создание конфигурации по умолчанию для DemirBank"""
    
    return BankConfiguration(
        bank_code="DEMIR",
        bank_type=BankType.STANDARD,
        name="DemirBank",
        api_version="1.0",
        timeout_seconds=60,
        max_retries=3,
        amount_format="decimal",
        phone_format="international",
        date_format="iso",
        required_fields=["receiver_account", "amount", "currency"],
        optional_fields=["description", "payment_reference", "sender_name"],
        webhook_format="standard",
        webhook_auth_method="hmac",
        webhook_retry_attempts=5,
        custom_headers={
            "X-Bank-Code": "DEMIR",
            "X-Source": "qrpayhub",
            "X-Channel": "api"
        },
        custom_parameters={
            "supports_refunds": True,
            "refund_timeout_seconds": 90,
            "max_refund_amount": 500000.0,
            "supports_partial_refunds": True
        },
        max_amount=2000000.0,
        min_amount=1.0,
        supported_currencies=["KGS", "USD", "EUR", "RUB"],
        supports_partial_payments=True,
        supports_refunds=True,
        supports_installments=False,
        requires_customer_verification=False,
        health_check_url="/api/v1/health",
        status_check_interval=300
    )
