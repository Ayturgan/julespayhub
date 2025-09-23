"""
Адаптер для мобильного банка (без поддержки возвратов)
"""

from typing import Dict, Any
from app.services.bank_adapter_service import MobileBankAdapter, BankConfiguration, BankType
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

class MobileBankRefundAdapter(MobileBankAdapter):
    """Адаптер для мобильного банка с ограниченной поддержкой возвратов"""
    
    def __init__(self, config: BankConfiguration):
        super().__init__(config)
        # Мобильный банк НЕ поддерживает возвраты
        self.config.supports_refunds = False
    
    def format_payment_info(self, payment_request: UnifiedPayment) -> Dict[str, Any]:
        """Форматирование информации о платеже для мобильного банка"""
        
        # Мобильный банк использует упрощенный формат
        base_info = super().format_payment_info(payment_request)
        
        # Добавляем специфичные для мобильного банка поля
        base_info.update({
            "bank_code": "MOBILE",
            "payment_type": "mobile_transfer",
            "source": "qrpayhub",
            "mobile_app_version": "2.1.0"
        })
        
        return base_info
    
    def validate_webhook_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация webhook от мобильного банка"""
        
        result = super().validate_webhook_payload(payload)
        
        # Мобильный банк добавляет дополнительные поля
        if "mobile_session_id" in payload:
            # Логируем ID сессии мобильного банка
            self.logger.info(f"Mobile bank session ID: {payload['mobile_session_id']}")
        
        return result
    
    def process_webhook_data(self, payload: Dict[str, Any]):
        """Обработка webhook данных от мобильного банка"""
        
        # Мобильный банк может использовать другие названия полей
        if "mobile_session_id" in payload and "transaction_id" not in payload:
            payload["transaction_id"] = payload["mobile_session_id"]
        
        if "mobile_status" in payload and "status" not in payload:
            payload["status"] = payload["mobile_status"]
        
        return super().process_webhook_data(payload)
    
    # Методы для двухфазного протокола возвратов (НЕ ПОДДЕРЖИВАЮТСЯ)
    
    def format_refund_prepare_request(self, request: RefundPrepareRequest) -> Dict[str, Any]:
        """Форматирование запроса prepare возврата для мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def format_refund_commit_request(self, request: RefundCommitRequest) -> Dict[str, Any]:
        """Форматирование запроса commit возврата для мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def format_refund_abort_request(self, request: RefundAbortRequest) -> Dict[str, Any]:
        """Форматирование запроса abort возврата для мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def parse_refund_prepare_response(self, response_data: Dict[str, Any]) -> RefundPrepareResponse:
        """Парсинг ответа prepare возврата от мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def parse_refund_commit_response(self, response_data: Dict[str, Any]) -> RefundCommitResponse:
        """Парсинг ответа commit возврата от мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def parse_refund_abort_response(self, response_data: Dict[str, Any]) -> RefundAbortResponse:
        """Парсинг ответа abort возврата от мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def get_refund_endpoint_url(self, base_url: str, operation: str) -> str:
        """Получение URL эндпоинта для операций возврата мобильного банка (НЕ ПОДДЕРЖИВАЕТСЯ)"""
        
        # Мобильный банк не поддерживает возвраты
        raise NotImplementedError(
            "Мобильный банк не поддерживает двухфазные возвраты. "
            "Используйте альтернативные методы возврата."
        )
    
    def get_two_phase_headers(self, bank, operation: str) -> Dict[str, str]:
        """Получение заголовков для мобильного банка"""
        
        headers = super().get_two_phase_headers(bank, operation)
        
        # Мобильный банк требует дополнительные заголовки
        headers.update({
            "X-Bank-Code": "MOBILE",
            "X-Operation-Type": operation,
            "X-Source": "qrpayhub",
            "X-App-Version": "2.1.0"
        })
        
        return headers
    
    def supports_refund_operations(self) -> bool:
        """Проверка поддержки операций возврата"""
        return False
    
    def get_refund_alternatives(self) -> Dict[str, str]:
        """Получение альтернативных методов возврата"""
        return {
            "manual_refund": "Ручной возврат через банк",
            "customer_service": "Обращение в службу поддержки",
            "dispute_process": "Процесс оспаривания транзакции"
        }

# Конфигурация по умолчанию для мобильного банка
def create_mobile_bank_configuration() -> BankConfiguration:
    """Создание конфигурации по умолчанию для мобильного банка"""
    
    return BankConfiguration(
        bank_code="MOBILE",
        bank_type=BankType.MOBILE_FIRST,
        name="MobileBank",
        api_version="1.0",
        timeout_seconds=30,
        max_retries=2,
        amount_format="decimal",
        phone_format="international",
        date_format="iso",
        required_fields=["receiver_phone", "amount"],
        optional_fields=["description"],
        webhook_format="simple",
        webhook_auth_method="basic",
        webhook_retry_attempts=3,
        custom_headers={
            "X-Bank-Code": "MOBILE",
            "X-Source": "qrpayhub",
            "X-App-Version": "2.1.0"
        },
        custom_parameters={
            "supports_refunds": False,
            "max_amount": 50000.0,
            "mobile_only": True
        },
        max_amount=50000.0,
        min_amount=1.0,
        supported_currencies=["KGS"],
        supports_partial_payments=False,
        supports_refunds=False,
        supports_installments=False,
        requires_customer_verification=True,
        health_check_url="/api/v1/health",
        status_check_interval=180
    )
