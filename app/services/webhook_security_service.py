import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException
from app.models.payment import Bank
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class WebhookSecurityService:
    """Сервис безопасности webhook с расширенной проверкой подписи"""
    
    # Допустимое время жизни timestamp (в секундах)
    MAX_TIMESTAMP_AGE = 300  # 5 минут
    
    @staticmethod
    def verify_webhook_signature(
        request: Request,
        bank: Bank,
        body: str,
        require_timestamp: bool = True
    ) -> Dict[str, Any]:
        """
        Полная проверка подписи webhook с дополнительными проверками безопасности
        
        Args:
            request: FastAPI Request объект
            bank: Объект банка
            body: Тело запроса в виде строки
            require_timestamp: Требовать проверку timestamp
            
        Returns:
            Dict[str, Any]: Результат проверки
        """
        
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "details": {}
        }
        
        # 1. Проверяем наличие подписи
        signature = request.headers.get("x-signature") or request.headers.get("x-hub-signature-256")
        if not signature:
            result["errors"].append("Missing webhook signature header")
            return result
        
        # 2. Проверяем timestamp если требуется
        timestamp_result = None
        if require_timestamp:
            timestamp_result = WebhookSecurityService._verify_timestamp(request)
            result["details"]["timestamp"] = timestamp_result
            
            if not timestamp_result["valid"]:
                result["errors"].extend(timestamp_result["errors"])
                if timestamp_result.get("critical", False):
                    return result  # Критическая ошибка timestamp
        
        # 3. Проверяем формат подписи
        signature_format = WebhookSecurityService._parse_signature(signature)
        result["details"]["signature_format"] = signature_format
        
        if not signature_format["valid"]:
            result["errors"].extend(signature_format["errors"])
            return result
        
        # 4. Вычисляем ожидаемую подпись
        expected_signature = WebhookSecurityService._compute_signature(
            bank.hmac_secret,
            request.method,
            str(request.url.path),
            body,
            timestamp_result["timestamp"] if timestamp_result else ""
        )
        
        result["details"]["expected_signature"] = expected_signature[:20] + "..."  # Частично для логов
        
        # 5. Сравниваем подписи
        provided_signature = signature_format["signature"]
        
        if not hmac.compare_digest(expected_signature, provided_signature):
            result["errors"].append("Invalid webhook signature")
            
            # Дополнительные проверки для диагностики
            WebhookSecurityService._diagnose_signature_mismatch(
                request, bank, body, provided_signature, expected_signature, result
            )
            
            return result
        
        # 6. Дополнительные проверки безопасности
        security_checks = WebhookSecurityService._perform_security_checks(request, bank)
        result["details"]["security_checks"] = security_checks
        
        if security_checks["suspicious"]:
            result["warnings"].extend(security_checks["warnings"])
        
        result["valid"] = True
        
        logger.info(f"Webhook signature verified successfully for bank {bank.code}")
        
        return result
    
    @staticmethod
    def _verify_timestamp(request: Request) -> Dict[str, Any]:
        """Проверка timestamp webhook"""
        
        result = {"valid": False, "errors": [], "timestamp": None, "critical": False}
        
        timestamp_header = request.headers.get("x-timestamp")
        if not timestamp_header:
            result["errors"].append("Missing x-timestamp header")
            result["critical"] = True
            return result
        
        try:
            # Парсим timestamp
            if timestamp_header.isdigit():
                # Unix timestamp
                timestamp = int(timestamp_header)
                timestamp_dt = datetime.fromtimestamp(timestamp)
            else:
                # ISO format
                timestamp_dt = datetime.fromisoformat(timestamp_header.replace('Z', '+00:00'))
                timestamp = int(timestamp_dt.timestamp())
            
            result["timestamp"] = timestamp_header
            
            # Проверяем возраст timestamp
            current_time = int(time.time())
            age = abs(current_time - timestamp)
            
            if age > WebhookSecurityService.MAX_TIMESTAMP_AGE:
                result["errors"].append(f"Timestamp too old: {age} seconds (max: {WebhookSecurityService.MAX_TIMESTAMP_AGE})")
                result["critical"] = True
                return result
            
            result["valid"] = True
            
        except (ValueError, OverflowError, OSError) as e:
            result["errors"].append(f"Invalid timestamp format: {e}")
            result["critical"] = True
        
        return result
    
    @staticmethod
    def _parse_signature(signature: str) -> Dict[str, Any]:
        """Парсинг формата подписи"""
        
        result = {"valid": False, "errors": [], "signature": None, "algorithm": None}
        
        # Поддерживаем разные форматы подписи
        if signature.startswith("sha256="):
            # GitHub style: sha256=abc123...
            result["algorithm"] = "sha256"
            result["signature"] = signature[7:]
        elif signature.startswith("sha1="):
            # Legacy format
            result["algorithm"] = "sha1"
            result["signature"] = signature[5:]
        elif len(signature) == 64:
            # Raw hex signature (предполагаем sha256)
            result["algorithm"] = "sha256"
            result["signature"] = signature
        else:
            result["errors"].append("Unknown signature format")
            return result
        
        # Проверяем что подпись в hex формате
        try:
            bytes.fromhex(result["signature"])
            result["valid"] = True
        except ValueError:
            result["errors"].append("Signature is not valid hex")
        
        return result
    
    @staticmethod
    def _compute_signature(
        secret: str,
        method: str,
        path: str,
        body: str,
        timestamp: str = ""
    ) -> str:
        """Вычисление ожидаемой подписи"""
        
        # Формируем строку для подписи
        message_parts = [method.upper(), path]
        
        if body:
            message_parts.append(body)
        
        if timestamp:
            message_parts.append(timestamp)
        
        message = "|".join(message_parts)
        
        # Вычисляем HMAC-SHA256
        signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    @staticmethod
    def _diagnose_signature_mismatch(
        request: Request,
        bank: Bank,
        body: str,
        provided: str,
        expected: str,
        result: Dict[str, Any]
    ):
        """Диагностика несовпадения подписи для отладки"""
        
        diagnostics = {
            "method": request.method,
            "path": str(request.url.path),
            "body_length": len(body),
            "body_hash": hashlib.md5(body.encode()).hexdigest(),
            "timestamp_header": request.headers.get("x-timestamp"),
            "provided_signature_length": len(provided),
            "expected_signature_length": len(expected)
        }
        
        # Проверяем возможные причины
        possible_causes = []
        
        if len(provided) != len(expected):
            possible_causes.append("Different signature lengths - algorithm mismatch?")
        
        if not body and request.method == "POST":
            possible_causes.append("Empty body for POST request")
        
        timestamp = request.headers.get("x-timestamp")
        if not timestamp:
            possible_causes.append("Missing timestamp in signature calculation")
        
        # Тестируем альтернативные способы вычисления
        alternative_signatures = {}
        
        # Без timestamp
        alt_sig_no_ts = WebhookSecurityService._compute_signature(
            bank.hmac_secret, request.method, str(request.url.path), body, ""
        )
        alternative_signatures["without_timestamp"] = alt_sig_no_ts
        
        # Только body
        if body:
            alt_sig_body_only = hmac.new(
                bank.hmac_secret.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            alternative_signatures["body_only"] = alt_sig_body_only
        
        # Проверяем совпадения с альтернативными подписями
        for alt_name, alt_sig in alternative_signatures.items():
            if hmac.compare_digest(alt_sig, provided):
                possible_causes.append(f"Signature matches {alt_name} calculation method")
        
        diagnostics["possible_causes"] = possible_causes
        diagnostics["alternative_signatures"] = {
            k: v[:20] + "..." for k, v in alternative_signatures.items()
        }
        
        result["details"]["diagnostics"] = diagnostics
        
        logger.warning(
            f"Webhook signature mismatch for bank {bank.code}: {diagnostics}"
        )
    
    @staticmethod
    def _perform_security_checks(request: Request, bank: Bank) -> Dict[str, Any]:
        """Дополнительные проверки безопасности"""
        
        result = {"suspicious": False, "warnings": [], "details": {}}
        
        # 1. Проверяем IP банка (если настроен whitelist)
        if bank.allowed_ips:
            try:
                allowed_ips = json.loads(bank.allowed_ips)
                if isinstance(allowed_ips, list) and allowed_ips:
                    client_ip = request.client.host
                    if client_ip not in allowed_ips:
                        result["suspicious"] = True
                        result["warnings"].append(f"Request from non-whitelisted IP: {client_ip}")
            except (json.JSONDecodeError, TypeError):
                pass
        
        # 2. Проверяем частоту запросов
        user_agent = request.headers.get("user-agent", "")
        if "test" in user_agent.lower() or "debug" in user_agent.lower():
            result["warnings"].append("Test/debug user agent detected")
        
        # 3. Проверяем размер body
        body_size = int(request.headers.get("content-length", 0))
        if body_size > 10 * 1024:  # 10KB
            result["warnings"].append(f"Large webhook body: {body_size} bytes")
        
        # 4. Проверяем подозрительные заголовки
        suspicious_headers = []
        for header_name in request.headers.keys():
            if header_name.lower().startswith(('x-debug', 'x-test', 'x-forwarded')):
                suspicious_headers.append(header_name)
        
        if suspicious_headers:
            result["warnings"].append(f"Suspicious headers: {', '.join(suspicious_headers)}")
        
        result["details"]["checks_performed"] = [
            "ip_whitelist", "user_agent", "body_size", "suspicious_headers"
        ]
        
        return result
    
    @staticmethod
    def create_webhook_signature(
        secret: str,
        method: str,
        path: str,
        body: str,
        timestamp: Optional[str] = None
    ) -> str:
        """
        Создание подписи webhook для тестирования
        
        Args:
            secret: HMAC секрет
            method: HTTP метод
            path: Путь запроса
            body: Тело запроса
            timestamp: Timestamp (опционально)
            
        Returns:
            str: Подпись в формате sha256=...
        """
        
        if not timestamp:
            timestamp = str(int(time.time()))
        
        signature = WebhookSecurityService._compute_signature(
            secret, method, path, body, timestamp
        )
        
        return f"sha256={signature}"
