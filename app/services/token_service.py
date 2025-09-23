import hmac
import hashlib
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from app.core.config import settings
from app.models.unified import UnifiedPayment
from app.schemas.unified_payment import PaymentStatus

class SecureTokenService:
    """Сервис для создания и проверки защищенных токенов"""
    
    @staticmethod
    def generate_secure_token(
        payment_data: Dict[str, Any],
        expires_in_minutes: Optional[int] = None,
        token_uuid: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> str:
        """
        Генерация защищенного токена с подписью
        
        Args:
            payment_data: Данные платежа для подписи
            expires_in_minutes: Время жизни токена в минутах
            
        Returns:
            str: Защищенный токен в формате UUID.SIGNATURE
        """
        if expires_in_minutes is None and expires_at is None:
            expires_in_minutes = settings.QR_TOKEN_EXPIRE_MINUTES
        
        # UUID токена (может быть передан снаружи для согласованности с БД)
        token_uuid = token_uuid or str(uuid.uuid4())
        
        # Время истечения (может быть передано снаружи)
        expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes))
        
        # Данные для подписи (используем UNIX-время в секундах для стабильности)
        expires_at_ts = int(expires_at.timestamp())
        payload = {
            "uuid": token_uuid,
            "expires_at_ts": expires_at_ts,
            "receiver_account": payment_data.get("receiver_account"),
            "receiver_bank_code": payment_data.get("receiver_bank_code"),
            "amount": payment_data.get("amount"),
            "payment_reference": payment_data.get("payment_reference")
        }
        
        # Создаем подпись
        signature = SecureTokenService._create_signature(payload)
        
        # Возвращаем токен в формате UUID.SIGNATURE
        return f"{token_uuid}.{signature}"
    
    @staticmethod
    def verify_token_signature(token: str, payment_request: "UnifiedPayment") -> bool:
        """
        Проверка подписи токена
        
        Args:
            token: Токен для проверки
            payment_request: Объект UnifiedPayment из БД
            
        Returns:
            bool: True если подпись корректна
        """
        try:
            # Разбираем токен
            if "." not in token:
                return False
            
            token_uuid, signature = token.rsplit(".", 1)
            
            # Восстанавливаем payload (новый формат с UNIX-временем)
            expires_dt = payment_request.expires_at
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            expires_at_ts = int(expires_dt.timestamp())
            payload_new = {
                "uuid": token_uuid,
                "expires_at_ts": expires_at_ts,
                "receiver_account": payment_request.receiver_account,
                "receiver_bank_code": payment_request.receiver_bank_code,
                "amount": payment_request.amount,
                "payment_reference": payment_request.payment_reference
            }
            expected_signature = SecureTokenService._create_signature(payload_new)
            
            # Сравниваем подписи (защищено от timing attacks)
            if hmac.compare_digest(signature, expected_signature):
                return True
            
            # Fallback: проверяем старый формат (ISO), чтобы не ломать ранее созданные токены
            try:
                payload_old = {
                    "uuid": token_uuid,
                    "expires_at": expires_dt.isoformat(),
                    "receiver_account": payment_request.receiver_account,
                    "receiver_bank_code": payment_request.receiver_bank_code,
                    "amount": payment_request.amount,
                    "payment_reference": payment_request.payment_reference
                }
                expected_signature_old = SecureTokenService._create_signature(payload_old)
                return hmac.compare_digest(signature, expected_signature_old)
            except Exception:
                return False
            
        except Exception:
            return False
    
    @staticmethod
    def extract_uuid_from_token(token: str) -> Optional[str]:
        """
        Извлечение UUID из токена
        
        Args:
            token: Токен в формате UUID.SIGNATURE
            
        Returns:
            str: UUID часть токена или None
        """
        try:
            if "." not in token:
                # Для обратной совместимости со старыми токенами
                return token
            
            token_uuid, _ = token.rsplit(".", 1)
            return token_uuid
        except Exception:
            return None
    
    @staticmethod
    def _create_signature(payload: Dict[str, Any]) -> str:
        """
        Создание HMAC подписи для payload
        
        Args:
            payload: Данные для подписи
            
        Returns:
            str: HMAC подпись
        """
        # Сортируем ключи для консистентности
        sorted_payload = json.dumps(payload, sort_keys=True, default=str)
        
        # Создаем HMAC подпись
        signature = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            sorted_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    @staticmethod
    def is_token_expired(token: str, payment_request: "UnifiedPayment") -> bool:
        """
        Проверка истечения срока действия токена
        
        Args:
            token: Токен для проверки
            payment_request: Объект UnifiedPayment из БД
            
        Returns:
            bool: True если токен истек
        """
        now_utc = datetime.now(timezone.utc)
        # Если в БД дата без tzinfo, считаем её UTC
        expires_at = payment_request.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return now_utc > expires_at
    
    @staticmethod
    def validate_token(token: str, payment_request: "UnifiedPayment") -> Dict[str, Any]:
        """
        Полная валидация токена
        
        Args:
            token: Токен для проверки
            payment_request: Объект UnifiedPayment из БД
            
        Returns:
            dict: Результат валидации
        """
        result = {
            "valid": False,
            "error": None,
            "expired": False,
            "used": False,
            "signature_valid": False
        }
        
        # Временно отключаем проверку истечения срока
        # if SecureTokenService.is_token_expired(token, payment_request):
        #     result["expired"] = True
        #     result["error"] = "Token expired"
        #     return result
        
        # Проверяем использование
        if payment_request.status == PaymentStatus.COMPLETED:
            result["used"] = True
            result["error"] = "Token already used"
            return result
        
        # Проверяем подпись
        if not SecureTokenService.verify_token_signature(token, payment_request):
            result["error"] = "Invalid token signature"
            return result
        
        result["signature_valid"] = True
        result["valid"] = True
        return result
    
    @staticmethod
    def generate_refund_token(original_payment_id: int) -> str:
        """
        Генерация токена для возврата
        
        Args:
            original_payment_id: ID оригинального платежа
            
        Returns:
            str: Токен возврата
        """
        # Создаем уникальный токен для возврата
        token_uuid = str(uuid.uuid4())
        
        # Данные для подписи
        payload = {
            "uuid": token_uuid,
            "type": "refund",
            "original_payment_id": original_payment_id,
            "timestamp": int(datetime.now(timezone.utc).timestamp())
        }
        
        # Создаем подпись
        signature = SecureTokenService._create_signature(payload)
        
        # Возвращаем токен в формате UUID.SIGNATURE
        return f"{token_uuid}.{signature}"