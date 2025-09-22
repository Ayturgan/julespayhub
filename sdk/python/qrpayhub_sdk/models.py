"""
QRPayHub SDK Models
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional


class PaymentStatus(str, Enum):
    """Статусы платежа"""
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"


@dataclass
class PaymentInfo:
    """Информация о платеже"""
    receiver_account: str
    receiver_bank_code: str
    receiver_name: str
    description: str
    amount: float
    currency: str
    payment_reference: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PaymentInfo':
        """Создание объекта из словаря"""
        return cls(
            receiver_account=data['receiver_account'],
            receiver_bank_code=data['receiver_bank_code'],
            receiver_name=data['receiver_name'],
            description=data['description'],
            amount=float(data['amount']),
            currency=data['currency'],
            payment_reference=data['payment_reference']
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            'receiver_account': self.receiver_account,
            'receiver_bank_code': self.receiver_bank_code,
            'receiver_name': self.receiver_name,
            'description': self.description,
            'amount': self.amount,
            'currency': self.currency,
            'payment_reference': self.payment_reference
        }


@dataclass
class WebhookData:
    """Данные для webhook о статусе платежа"""
    token: str
    status: PaymentStatus
    transaction_id: str
    amount: float
    currency: str
    payer_phone: str
    timestamp: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    fee_amount: Optional[float] = None
    processing_time_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для JSON"""
        result = {
            'token': self.token,
            'status': self.status.value if isinstance(self.status, PaymentStatus) else self.status,
            'transaction_id': self.transaction_id,
            'amount': self.amount,
            'currency': self.currency,
            'payer_phone': self.payer_phone,
            'timestamp': self.timestamp
        }
        
        # Добавляем опциональные поля если они есть
        if self.error_code is not None:
            result['error_code'] = self.error_code
        if self.error_message is not None:
            result['error_message'] = self.error_message
        if self.fee_amount is not None:
            result['fee_amount'] = self.fee_amount
        if self.processing_time_ms is not None:
            result['processing_time_ms'] = self.processing_time_ms
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WebhookData':
        """Создание объекта из словаря"""
        return cls(
            token=data['token'],
            status=PaymentStatus(data['status']),
            transaction_id=data['transaction_id'],
            amount=float(data['amount']),
            currency=data['currency'],
            payer_phone=data['payer_phone'],
            timestamp=data['timestamp'],
            error_code=data.get('error_code'),
            error_message=data.get('error_message'),
            fee_amount=float(data['fee_amount']) if data.get('fee_amount') is not None else None,
            processing_time_ms=int(data['processing_time_ms']) if data.get('processing_time_ms') is not None else None
        )
