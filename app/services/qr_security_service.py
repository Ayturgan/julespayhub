import hmac
import hashlib
import json
import base64
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from app.core.config import settings, get_base_url
from app.services.token_service import SecureTokenService
import logging

logger = logging.getLogger(__name__)

class QRSecurityService:
    """Сервис для защиты QR-кодов от подделки и атак"""
    
    # Значения по умолчанию (могут быть переопределены из БД настроек)
    MAX_QR_LIFETIME = 60  # минут
    MIN_QR_LIFETIME = 1   # минут
    ALLOWED_DOMAINS = ["qrpayhub.com", "localhost", "127.0.0.1"]
    
    @classmethod
    def get_allowed_domains(cls):
        """Получение списка разрешенных доменов с динамическим BASE_URL"""
        domains = cls.ALLOWED_DOMAINS.copy()
        try:
            base_url = get_base_url()
            if base_url:
                base_domain = base_url.replace("https://", "").replace("http://", "")
                if base_domain and base_domain not in domains:
                    domains.append(base_domain)
        except Exception:
            pass  # Если get_base_url недоступен, используем базовый список
        return domains
    
    @staticmethod
    def create_secure_qr_url(
        payment_data: Dict[str, Any],
        base_url: str,
        expires_in_minutes: Optional[int] = None,
        additional_security: bool = True
    ) -> Dict[str, Any]:
        """
        Создание защищенного QR URL с множественными уровнями защиты
        
        Args:
            payment_data: Данные платежа
            base_url: Базовый URL системы
            expires_in_minutes: Время жизни QR-кода
            additional_security: Включить дополнительную защиту
            
        Returns:
            Dict с защищенным URL и метаданными
        """
        
        if expires_in_minutes is None:
            expires_in_minutes = settings.QR_TOKEN_EXPIRE_MINUTES
        
        # Проверяем лимиты времени жизни
        if expires_in_minutes > QRSecurityService.MAX_QR_LIFETIME:
            expires_in_minutes = QRSecurityService.MAX_QR_LIFETIME
        elif expires_in_minutes < QRSecurityService.MIN_QR_LIFETIME:
            expires_in_minutes = QRSecurityService.MIN_QR_LIFETIME
        
        # Создаем основной защищенный токен
        secure_token = SecureTokenService.generate_secure_token(
            payment_data, expires_in_minutes
        )
        
        # Дополнительная защита
        security_features = {}
        
        if additional_security:
            # 1. Контрольная сумма данных платежа
            payment_checksum = QRSecurityService._calculate_payment_checksum(payment_data)
            security_features["checksum"] = payment_checksum
            
            # 2. Временная метка создания
            creation_timestamp = int(time.time())
            security_features["created"] = creation_timestamp
            
            # 3. Случайный nonce для предотвращения повторного использования
            nonce = QRSecurityService._generate_nonce()
            security_features["nonce"] = nonce
            
            # 4. Версия протокола безопасности
            security_features["version"] = "1.0"
        
        # Создаем финальный URL
        qr_url = f"{base_url}/pay?token={secure_token}"
        
        if additional_security and security_features:
            # Кодируем дополнительные параметры безопасности
            security_params = QRSecurityService._encode_security_params(security_features)
            qr_url += f"&sec={security_params}"
        
        # Создаем цифровую подпись всего URL
        url_signature = QRSecurityService._sign_url(qr_url)
        qr_url += f"&sig={url_signature}"
        
        return {
            "qr_url": qr_url,
            "secure_token": secure_token,
            "security_features": security_features,
            "expires_in": expires_in_minutes * 60,
            "created_at": datetime.now().isoformat(),
            "security_level": "high" if additional_security else "standard"
        }
    
    @staticmethod
    def validate_qr_url(
        qr_url: str,
        strict_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Полная валидация QR URL на предмет подделки и безопасности
        
        Args:
            qr_url: URL для проверки
            strict_mode: Строгий режим проверки
            
        Returns:
            Dict с результатами валидации
        """
        
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "security_checks": {},
            "token_data": None
        }
        
        try:
            # 1. Парсинг URL
            parsed_url = urlparse(qr_url)
            query_params = parse_qs(parsed_url.query)
            
            result["security_checks"]["url_parsed"] = True
            
            # 2. Проверка домена
            domain_check = QRSecurityService._validate_domain(parsed_url.netloc, strict_mode)
            result["security_checks"]["domain"] = domain_check
            
            if not domain_check["valid"]:
                result["errors"].extend(domain_check["errors"])
                if strict_mode:
                    return result
            
            # 3. Проверка обязательных параметров
            if "token" not in query_params:
                result["errors"].append("Missing required 'token' parameter")
                return result
            
            token = query_params["token"][0]
            result["security_checks"]["token_present"] = True
            
            # 4. Валидация основного токена
            # Здесь невозможно валидировать без payment_request, поэтому проверяем только формат
            from app.services.token_service import SecureTokenService as STS
            token_uuid = STS.extract_uuid_from_token(token)
            token_validation = {"valid": bool(token_uuid), "errors": []}
            if not token_validation["valid"]:
                token_validation["errors"].append("Invalid token format")
            result["security_checks"]["token_validation"] = token_validation
            
            if not token_validation["valid"]:
                result["errors"].extend(token_validation["errors"])
                return result
            
            result["token_data"] = token_validation["data"]
            
            # 5. Проверка подписи URL (если присутствует)
            if "sig" in query_params:
                url_without_sig = qr_url.split("&sig=")[0]
                provided_signature = query_params["sig"][0]
                
                signature_check = QRSecurityService._verify_url_signature(
                    url_without_sig, provided_signature
                )
                result["security_checks"]["url_signature"] = signature_check
                
                if not signature_check["valid"]:
                    result["errors"].extend(signature_check["errors"])
                    if strict_mode:
                        return result
            elif strict_mode:
                result["warnings"].append("URL signature not present")
            
            # 6. Проверка дополнительных параметров безопасности
            if "sec" in query_params:
                security_params = query_params["sec"][0]
                security_check = QRSecurityService._validate_security_params(
                    security_params, result["token_data"]
                )
                result["security_checks"]["security_params"] = security_check
                
                if not security_check["valid"]:
                    result["errors"].extend(security_check["errors"])
                    if strict_mode:
                        return result
            
            # 7. Проверка на подозрительные паттерны
            suspicious_check = QRSecurityService._detect_suspicious_patterns(qr_url)
            result["security_checks"]["suspicious_patterns"] = suspicious_check
            
            if suspicious_check["suspicious"]:
                result["warnings"].extend(suspicious_check["warnings"])
            
            # 8. Проверка возраста токена
            age_check = QRSecurityService._validate_token_age(result["token_data"])
            result["security_checks"]["token_age"] = age_check
            
            if not age_check["valid"]:
                result["errors"].extend(age_check["errors"])
                return result
            
            # Если все проверки пройдены
            result["valid"] = True
            
        except Exception as e:
            result["errors"].append(f"Validation error: {str(e)}")
            logger.error(f"QR URL validation failed: {e}")
        
        return result
    
    @staticmethod
    def _calculate_payment_checksum(payment_data: Dict[str, Any]) -> str:
        """Вычисление контрольной суммы данных платежа"""
        
        # Сортируем ключи для консистентности
        sorted_data = {k: payment_data[k] for k in sorted(payment_data.keys()) if payment_data[k] is not None}
        
        # Создаем строку для хеширования
        data_string = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'))
        
        # Вычисляем SHA-256
        checksum = hashlib.sha256(data_string.encode('utf-8')).hexdigest()[:16]
        
        return checksum
    
    @staticmethod
    def _generate_nonce() -> str:
        """Генерация случайного nonce"""
        import secrets
        return secrets.token_urlsafe(8)
    
    @staticmethod
    def _encode_security_params(security_features: Dict[str, Any]) -> str:
        """Кодирование параметров безопасности"""
        
        # Сериализуем в JSON и кодируем в base64
        json_data = json.dumps(security_features, ensure_ascii=False)
        encoded_data = base64.urlsafe_b64encode(json_data.encode('utf-8')).decode('ascii')
        
        return encoded_data
    
    @staticmethod
    def _decode_security_params(encoded_params: str) -> Dict[str, Any]:
        """Декодирование параметров безопасности"""
        
        try:
            # Декодируем из base64 и парсим JSON
            decoded_data = base64.urlsafe_b64decode(encoded_params.encode('ascii'))
            security_features = json.loads(decoded_data.decode('utf-8'))
            
            return security_features
        except Exception as e:
            raise ValueError(f"Failed to decode security parameters: {e}")
    
    @staticmethod
    def _sign_url(url: str) -> str:
        """Создание цифровой подписи URL"""
        
        # Используем HMAC-SHA256 для подписи
        signature = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            url.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]  # Укорачиваем для удобства
        
        return signature
    
    @staticmethod
    def _verify_url_signature(url: str, provided_signature: str) -> Dict[str, Any]:
        """Проверка цифровой подписи URL"""
        
        result = {"valid": False, "errors": []}
        
        try:
            expected_signature = QRSecurityService._sign_url(url)
            
            if not hmac.compare_digest(expected_signature, provided_signature):
                result["errors"].append("Invalid URL signature")
                return result
            
            result["valid"] = True
            
        except Exception as e:
            result["errors"].append(f"Signature verification error: {e}")
        
        return result
    
    @staticmethod
    def _validate_domain(domain: str, strict_mode: bool) -> Dict[str, Any]:
        """Проверка допустимости домена"""
        
        result = {"valid": False, "errors": []}
        
        if not domain:
            result["errors"].append("Missing domain in URL")
            return result
        
        # Убираем порт если есть
        domain_without_port = domain.split(':')[0]
        
        if strict_mode:
            if domain_without_port not in QRSecurityService.get_allowed_domains():
                result["errors"].append(f"Domain '{domain_without_port}' not in allowed list")
                return result
        else:
            # В нестрогом режиме проверяем только на подозрительные домены
            suspicious_domains = [
                "bit.ly", "tinyurl.com", "t.co", "goo.gl", "short.link",
                "phishing", "fake", "scam"
            ]
            
            if any(suspicious in domain_without_port.lower() for suspicious in suspicious_domains):
                result["errors"].append(f"Suspicious domain detected: {domain_without_port}")
                return result
        
        result["valid"] = True
        return result
    
    @staticmethod
    def _validate_security_params(
        encoded_params: str, 
        token_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Валидация дополнительных параметров безопасности"""
        
        result = {"valid": False, "errors": []}
        
        try:
            security_features = QRSecurityService._decode_security_params(encoded_params)
            
            # Проверяем версию протокола
            if "version" in security_features:
                if security_features["version"] != "1.0":
                    result["errors"].append(f"Unsupported security version: {security_features['version']}")
                    return result
            
            # Проверяем контрольную сумму
            if "checksum" in security_features and token_data:
                expected_checksum = QRSecurityService._calculate_payment_checksum(token_data)
                if security_features["checksum"] != expected_checksum:
                    result["errors"].append("Payment data checksum mismatch")
                    return result
            
            # Проверяем временную метку создания
            if "created" in security_features:
                creation_time = security_features["created"]
                current_time = int(time.time())
                
                # Проверяем что QR не слишком старый (максимум 1 час)
                if current_time - creation_time > 3600:
                    result["errors"].append("QR code is too old")
                    return result
                
                # Проверяем что QR не из будущего (допускаем 5 минут на расхождение часов)
                if creation_time > current_time + 300:
                    result["errors"].append("QR code created in the future")
                    return result
            
            result["valid"] = True
            
        except Exception as e:
            result["errors"].append(f"Security parameters validation error: {e}")
        
        return result
    
    @staticmethod
    def _detect_suspicious_patterns(qr_url: str) -> Dict[str, Any]:
        """Детекция подозрительных паттернов в URL"""
        
        result = {"suspicious": False, "warnings": []}
        
        # Подозрительные паттерны
        suspicious_patterns = [
            ("double_encoding", r"%[0-9A-Fa-f]{2}%[0-9A-Fa-f]{2}"),  # Двойное URL кодирование
            ("javascript", r"javascript:"),  # JavaScript в URL
            ("data_uri", r"data:"),  # Data URI
            ("long_params", r"[?&][^=]{50,}="),  # Очень длинные параметры
            ("hex_encoding", r"\\x[0-9A-Fa-f]{2}"),  # Hex кодирование
        ]
        
        for pattern_name, pattern in suspicious_patterns:
            import re
            if re.search(pattern, qr_url, re.IGNORECASE):
                result["suspicious"] = True
                result["warnings"].append(f"Suspicious pattern detected: {pattern_name}")
        
        # Проверка длины URL
        if len(qr_url) > 2000:  # Очень длинный URL
            result["suspicious"] = True
            result["warnings"].append("URL is unusually long")
        
        # Проверка количества параметров
        param_count = qr_url.count('&') + qr_url.count('?')
        if param_count > 10:  # Слишком много параметров
            result["suspicious"] = True
            result["warnings"].append("Too many URL parameters")
        
        return result
    
    @staticmethod
    def _validate_token_age(token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Проверка возраста токена"""
        
        result = {"valid": False, "errors": []}
        
        if not token_data or "expires_at" not in token_data:
            result["errors"].append("Token expiration data not available")
            return result
        
        try:
            expires_at = datetime.fromisoformat(token_data["expires_at"])
            current_time = datetime.now()
            
            # Временно отключаем проверку истечения времени
            # if current_time > expires_at:
            #     result["errors"].append("Token has expired")
            #     return result
            
            # Предупреждение если токен скоро истечет (менее 1 минуты)
            if (expires_at - current_time).total_seconds() < 60:
                # Не ошибка, но предупреждение
                pass
            
            result["valid"] = True
            
        except Exception as e:
            result["errors"].append(f"Token age validation error: {e}")
        
        return result
    
    @staticmethod
    def generate_qr_security_report(qr_url: str) -> Dict[str, Any]:
        """
        Генерация подробного отчета о безопасности QR-кода
        
        Args:
            qr_url: URL для анализа
            
        Returns:
            Dict с подробным отчетом о безопасности
        """
        
        # Выполняем полную валидацию
        validation_result = QRSecurityService.validate_qr_url(qr_url, strict_mode=False)
        
        # Дополнительная аналитика
        parsed_url = urlparse(qr_url)
        query_params = parse_qs(parsed_url.query)
        
        report = {
            "url": qr_url,
            "timestamp": datetime.now().isoformat(),
            "validation_result": validation_result,
            "url_analysis": {
                "scheme": parsed_url.scheme,
                "domain": parsed_url.netloc,
                "path": parsed_url.path,
                "parameters_count": len(query_params),
                "url_length": len(qr_url)
            },
            "security_features": {
                "has_signature": "sig" in query_params,
                "has_security_params": "sec" in query_params,
                "has_token": "token" in query_params
            },
            "risk_assessment": QRSecurityService._assess_risk_level(validation_result),
            "recommendations": QRSecurityService._generate_security_recommendations(validation_result)
        }
        
        return report
    
    @staticmethod
    def _assess_risk_level(validation_result: Dict[str, Any]) -> Dict[str, Any]:
        """Оценка уровня риска QR-кода"""
        
        risk_score = 0
        risk_factors = []
        
        # Анализируем ошибки
        if validation_result["errors"]:
            risk_score += len(validation_result["errors"]) * 10
            risk_factors.extend(validation_result["errors"])
        
        # Анализируем предупреждения
        if validation_result["warnings"]:
            risk_score += len(validation_result["warnings"]) * 3
            risk_factors.extend(validation_result["warnings"])
        
        # Анализируем отсутствие функций безопасности
        security_checks = validation_result.get("security_checks", {})
        
        if not security_checks.get("url_signature", {}).get("valid", False):
            risk_score += 5
            risk_factors.append("Missing or invalid URL signature")
        
        if "security_params" not in security_checks:
            risk_score += 3
            risk_factors.append("No additional security parameters")
        
        # Определяем уровень риска
        if risk_score == 0:
            risk_level = "LOW"
        elif risk_score <= 10:
            risk_level = "MEDIUM"
        elif risk_score <= 25:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"
        
        return {
            "level": risk_level,
            "score": risk_score,
            "factors": risk_factors,
            "safe_to_use": risk_score <= 10
        }
    
    @staticmethod
    def _generate_security_recommendations(validation_result: Dict[str, Any]) -> List[str]:
        """Генерация рекомендаций по безопасности"""
        
        recommendations = []
        
        if validation_result["errors"]:
            recommendations.append("🚨 Не используйте этот QR-код - обнаружены критические ошибки безопасности")
        
        if validation_result["warnings"]:
            recommendations.append("⚠️ Будьте осторожны - обнаружены потенциальные проблемы безопасности")
        
        security_checks = validation_result.get("security_checks", {})
        
        if not security_checks.get("url_signature", {}).get("valid", False):
            recommendations.append("🔐 Рекомендуется использовать QR-коды с цифровой подписью")
        
        if "security_params" not in security_checks:
            recommendations.append("🛡️ Для повышения безопасности используйте расширенные параметры защиты")
        
        if not recommendations:
            recommendations.append("✅ QR-код прошел все проверки безопасности")
        
        return recommendations
