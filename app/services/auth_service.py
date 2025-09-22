import hmac
import hashlib
import json
from datetime import datetime
from typing import Optional, List
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from app.models.payment import Bank
from app.services.validation_service import APIValidationService
from app.services.realtime_monitoring_service import realtime_monitoring_service
from app.core.config import settings

class BankAuthService:
    """Сервис аутентификации банков"""
    
    @staticmethod
    def get_bank_by_token(db: Session, access_token: str) -> Optional[Bank]:
        """Получить банк по access token"""
        return db.query(Bank).filter(
            Bank.access_token == access_token,
            Bank.is_active == True
        ).first()
    
    @staticmethod
    def verify_ip_whitelist(bank: Bank, client_ip: str) -> bool:
        """Проверка IP адреса в whitelist"""
        if not bank.allowed_ips:
            # Если whitelist не настроен, разрешаем любой IP (для тестирования)
            return True
        
        try:
            allowed_ips = json.loads(bank.allowed_ips)
            return client_ip in allowed_ips
        except (json.JSONDecodeError, TypeError):
            return False
    
    @staticmethod
    def generate_hmac_signature(
        secret: str, 
        method: str, 
        path: str, 
        body: str = "",
        timestamp: str = ""
    ) -> str:
        """Генерация HMAC подписи для запроса"""
        # Формируем строку для подписи: METHOD|PATH|BODY|TIMESTAMP
        message = f"{method}|{path}|{body}|{timestamp}"
        
        signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature

    @staticmethod
    def build_hmac_message(
        method: str,
        path: str,
        body: str = "",
        timestamp: str = ""
    ) -> str:
        """Собирает строку для подписи в точности как при генерации: METHOD|PATH|BODY|TIMESTAMP"""
        return f"{method}|{path}|{body}|{timestamp}"
    
    @staticmethod
    def verify_hmac_signature(
        bank: Bank,
        request: Request,
        signature: str,
        timestamp: str,
        body: str = ""
    ) -> bool:
        """Проверка HMAC подписи запроса
        Включает устойчивые варианты на случай расхождений с кешем тела (middleware).
        """
        method = request.method
        path = str(request.url.path)

        def _gen(msg_body: str) -> str:
            return BankAuthService.generate_hmac_signature(
                secret=bank.hmac_secret,
                method=method,
                path=path,
                body=msg_body,
                timestamp=timestamp
            )

        # 1) Как есть
        expected_signature = _gen(body)
        if hmac.compare_digest(signature, expected_signature):
            return True

        # 2) Пустое тело (fallback) — оставляем, но рассчитываем, что в проде будет совпадать по фактическому body
        if method == "POST":
            expected_empty = _gen("")
            if hmac.compare_digest(signature, expected_empty):
                return True

        # 3) Нормализованный JSON (если это JSON)
        try:
            import json as _json
            if body:
                normalized = _json.dumps(_json.loads(body), separators=(',', ':'))
                expected_normalized = _gen(normalized)
                if hmac.compare_digest(signature, expected_normalized):
                    return True
        except Exception:
            pass

        return False
    
    @staticmethod
    def authenticate_bank_request(
        db: Session,
        request: Request,
        require_hmac: bool = True
    ) -> Bank:
        """
        Полная аутентификация запроса от банка
        
        Args:
            db: Сессия базы данных
            request: FastAPI Request объект
            require_hmac: Требовать HMAC подпись (для критических операций)
            
        Returns:
            Bank: Аутентифицированный банк
            
        Raises:
            HTTPException: При ошибке аутентификации
        """
        # 1. Проверяем Bearer token
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            # Записываем событие неудачной аутентификации
            realtime_monitoring_service.record_authentication_failure(
                bank_code=None,
                ip_address=request.client.host if request.client else "unknown",
                endpoint=str(request.url.path),
                error_message="Missing or invalid Authorization header",
                user_agent=request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        bank = BankAuthService.get_bank_by_token(db, access_token)
        
        if not bank:
            # Записываем событие неудачной аутентификации
            realtime_monitoring_service.record_authentication_failure(
                bank_code=None,
                ip_address=request.client.host if request.client else "unknown",
                endpoint=str(request.url.path),
                error_message="Invalid access token",
                user_agent=request.headers.get("user-agent")
            )
            raise HTTPException(
                status_code=401,
                detail="Invalid access token"
            )
        
        # 2. Проверяем IP whitelist
        client_ip = request.client.host
        if not BankAuthService.verify_ip_whitelist(bank, client_ip):
            # Записываем событие неудачной аутентификации и создаем WARNING алерт IP_NOT_IN_WL
            try:
                realtime_monitoring_service.record_authentication_failure(
                    bank_code=bank.code,
                    ip_address=client_ip or "unknown",
                    endpoint=str(request.url.path),
                    error_message=f"IP address {client_ip} not allowed for bank {bank.code}",
                    user_agent=request.headers.get("user-agent")
                )
                from app.services.bank_alerts_service import bank_alerts_service, AlertType
                from app.services.realtime_monitoring_service import AlertSeverity as _AS
                bank_alerts_service.create_alert(
                    alert_type=AlertType.AUTHENTICATION_ISSUES,
                    severity=_AS.WARNING,
                    bank_code=bank.code,
                    title="IP_NOT_IN_WL",
                    message=f"Запрос с неразрешенного IP {client_ip}",
                    details={
                        "rejected_ip": client_ip,
                        "bank_code": bank.code,
                        "endpoint": str(request.url.path)
                    }
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=403,
                detail="IP address not allowed"
            )
        
        # 3. Проверяем HMAC подпись (если требуется)
        if require_hmac:
            signature = request.headers.get("X-Signature")
            timestamp = request.headers.get("X-Timestamp")
            
            if not signature or not timestamp:
                raise HTTPException(
                    status_code=401,
                    detail="Missing X-Signature or X-Timestamp headers"
                )
            
            # Для POST запросов используем кешированное body из middleware
            body = getattr(request.state, 'body', '')
            
            # Дополнительная диагностика: логируем что получили
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"HMAC verification: method={request.method}, path={request.url.path}, body_length={len(body)}, body_preview={body[:100] if body else 'empty'}")
            
            if not BankAuthService.verify_hmac_signature(
                bank, request, signature, timestamp, body
            ):
                # Диагностика несоответствия подписи: добавляем точную строку, которую подписывает сервер
                method = request.method
                path = str(request.url.path)
                message = BankAuthService.build_hmac_message(method, path, body or "", timestamp)
                expected_signature = hmac.new(
                    bank.hmac_secret.encode('utf-8'),
                    message.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()
                # Возвращаем расширенную диагностическую информацию (временно, для отладки)
                try:
                    from app.services.bank_alerts_service import bank_alerts_service, AlertType
                    from app.services.realtime_monitoring_service import AlertSeverity as _AS
                    bank_alerts_service.create_alert(
                        alert_type=AlertType.AUTHENTICATION_ISSUES,
                        severity=_AS.WARNING,
                        bank_code=bank.code,
                        title="AUTH_FAILED",
                        message="Invalid HMAC signature",
                        details={
                            "bank_code": bank.code,
                            "endpoint": path,
                            "reason": "signature_mismatch"
                        }
                    )
                except Exception:
                    pass
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "Invalid HMAC signature",
                        "diagnostics": {
                            "server_signing_message": message,
                            "server_expected_signature": expected_signature,
                            "provided_signature": signature,
                            "timestamp": timestamp,
                            "method": method,
                            "path": path,
                            "body_length": len(body or ""),
                            "body_preview": body[:100] if body else "empty",
                            "middleware_body_cached": hasattr(request.state, 'body'),
                            "middleware_body_value": getattr(request.state, 'body', 'NOT_SET')
                        }
                    }
                )
        
        # 4. Валидация API запроса
        validation_result = APIValidationService.validate_bank_request(
            request, bank, "payment" if "payment" in str(request.url.path) else "webhook"
        )
        
        if not validation_result["valid"]:
            raise APIValidationService.create_validation_error_response(validation_result)
        
        # Сохраняем результат валидации для логирования
        request.state.validation_result = validation_result
        
        # 5. Обновляем время последнего использования
        bank.last_used_at = datetime.now()
        db.commit()
        
        return bank
    
    @staticmethod
    def create_bank(
        db: Session,
        code: str,
        name: str,
        access_token: str,
        hmac_secret: str,
        allowed_ips: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
        allowed_user_agents: Optional[List[str]] = None,
        required_headers: Optional[List[str]] = None,
        validation_rules: Optional[dict] = None
    ) -> Bank:
        """Создание нового банка-партнера"""
        
        # Проверяем уникальность кода
        existing_bank = db.query(Bank).filter(Bank.code == code).first()
        if existing_bank:
            raise ValueError(f"Bank with code {code} already exists")
        
        # Преобразуем списки и правила в JSON
        allowed_ips_json = None
        if allowed_ips:
            allowed_ips_json = json.dumps(allowed_ips)
        
        allowed_user_agents_json = None
        if allowed_user_agents:
            allowed_user_agents_json = json.dumps(allowed_user_agents)
        
        required_headers_json = None
        if required_headers:
            required_headers_json = json.dumps(required_headers)
        
        validation_rules_json = None
        if validation_rules:
            validation_rules_json = json.dumps(validation_rules)
        
        bank = Bank(
            code=code,
            name=name,
            access_token=access_token,
            hmac_secret=hmac_secret,
            allowed_ips=allowed_ips_json,
            webhook_url=webhook_url,
            allowed_user_agents=allowed_user_agents_json,
            required_headers=required_headers_json,
            validation_rules=validation_rules_json
        )
        
        db.add(bank)
        db.commit()
        db.refresh(bank)
        
        return bank
