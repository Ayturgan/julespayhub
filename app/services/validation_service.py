import json
import re
from typing import Dict, List, Optional, Any
from fastapi import Request, HTTPException
from app.models.payment import Bank
import logging

logger = logging.getLogger(__name__)

class APIValidationService:
    """Сервис для валидации API запросов от банков"""
    
    # Стандартные правила валидации
    DEFAULT_VALIDATION_RULES = {
        "user_agent": {
            "required": True,
            "min_length": 5,
            "max_length": 500,
            "forbidden_patterns": [
                r"curl",
                r"wget",
                r"python-requests",
                r"bot",
                r"crawler",
                r"spider"
            ]
        },
        "content_type": {
            "required_for_post": True,
            "allowed_values": [
                "application/json",
                "application/json; charset=utf-8"
            ]
        },
        "accept": {
            "required": False,
            "allowed_values": [
                "application/json",
                "*/*"
            ]
        }
    }
    
    @staticmethod
    def validate_bank_request(
        request: Request,
        bank: Bank,
        endpoint_type: str = "default"
    ) -> Dict[str, Any]:
        """
        Полная валидация запроса от банка
        
        Args:
            request: FastAPI Request объект
            bank: Объект банка
            endpoint_type: Тип эндпоинта для специфичных правил
            
        Returns:
            Dict[str, Any]: Результат валидации
        """
        
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "validation_details": {}
        }
        
        # 1. Валидация User-Agent
        user_agent_result = APIValidationService._validate_user_agent(
            request, bank
        )
        result["validation_details"]["user_agent"] = user_agent_result
        
        if not user_agent_result["valid"]:
            result["valid"] = False
            result["errors"].extend(user_agent_result["errors"])
        
        # 2. Валидация обязательных заголовков
        headers_result = APIValidationService._validate_required_headers(
            request, bank
        )
        result["validation_details"]["headers"] = headers_result
        
        if not headers_result["valid"]:
            result["valid"] = False
            result["errors"].extend(headers_result["errors"])
        
        # 3. Валидация Content-Type для POST запросов
        content_type_result = APIValidationService._validate_content_type(
            request
        )
        result["validation_details"]["content_type"] = content_type_result
        
        if not content_type_result["valid"]:
            result["valid"] = False
            result["errors"].extend(content_type_result["errors"])
        
        # 4. Валидация специфичных правил банка
        custom_rules_result = APIValidationService._validate_custom_rules(
            request, bank, endpoint_type
        )
        result["validation_details"]["custom_rules"] = custom_rules_result
        
        if not custom_rules_result["valid"]:
            result["valid"] = False
            result["errors"].extend(custom_rules_result["errors"])
        
        # 5. Проверка подозрительных паттернов
        security_result = APIValidationService._validate_security_patterns(
            request
        )
        result["validation_details"]["security"] = security_result
        
        if security_result["suspicious"]:
            result["warnings"].extend(security_result["warnings"])
        
        # Логируем результат валидации
        if not result["valid"]:
            logger.warning(
                f"API validation failed for bank {bank.code} from IP {request.client.host}: "
                f"{'; '.join(result['errors'])}"
            )
        
        return result
    
    @staticmethod
    def _validate_user_agent(request: Request, bank: Bank) -> Dict[str, Any]:
        """Валидация User-Agent заголовка"""
        
        result = {"valid": True, "errors": [], "details": {}}
        
        user_agent = request.headers.get("user-agent", "")
        result["details"]["value"] = user_agent
        
        # Проверяем наличие User-Agent
        if not user_agent:
            result["valid"] = False
            result["errors"].append("User-Agent header is required")
            return result
        
        # Проверяем длину
        if len(user_agent) < 5:
            result["valid"] = False
            result["errors"].append("User-Agent is too short")
        
        if len(user_agent) > 500:
            result["valid"] = False
            result["errors"].append("User-Agent is too long")
        
        # Проверяем против списка разрешенных User-Agent банка
        if bank.allowed_user_agents:
            try:
                allowed_agents = json.loads(bank.allowed_user_agents)
                if isinstance(allowed_agents, list) and allowed_agents:
                    user_agent_allowed = False
                    for allowed_pattern in allowed_agents:
                        if re.search(allowed_pattern, user_agent, re.IGNORECASE):
                            user_agent_allowed = True
                            break
                    
                    if not user_agent_allowed:
                        result["valid"] = False
                        result["errors"].append(
                            f"User-Agent not in allowed list for bank {bank.code}"
                        )
            except (json.JSONDecodeError, TypeError):
                pass  # Игнорируем некорректные настройки
        
        # Проверяем запрещенные паттерны
        for pattern in APIValidationService.DEFAULT_VALIDATION_RULES["user_agent"]["forbidden_patterns"]:
            if re.search(pattern, user_agent, re.IGNORECASE):
                result["valid"] = False
                result["errors"].append(f"User-Agent contains forbidden pattern: {pattern}")
        
        return result
    
    @staticmethod
    def _validate_required_headers(request: Request, bank: Bank) -> Dict[str, Any]:
        """Валидация обязательных заголовков"""
        
        result = {"valid": True, "errors": [], "details": {}}
        
        # Стандартные обязательные заголовки
        required_headers = ["authorization", "user-agent"]
        
        # Добавляем кастомные обязательные заголовки банка
        if bank.required_headers:
            try:
                custom_headers = json.loads(bank.required_headers)
                if isinstance(custom_headers, list):
                    required_headers.extend(custom_headers)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Проверяем наличие всех обязательных заголовков
        missing_headers = []
        for header in required_headers:
            header_lower = header.lower()
            if header_lower not in [h.lower() for h in request.headers.keys()]:
                missing_headers.append(header)
        
        if missing_headers:
            result["valid"] = False
            result["errors"].append(f"Missing required headers: {', '.join(missing_headers)}")
        
        result["details"]["required"] = required_headers
        result["details"]["missing"] = missing_headers
        result["details"]["present"] = list(request.headers.keys())
        
        return result
    
    @staticmethod
    def _validate_content_type(request: Request) -> Dict[str, Any]:
        """Валидация Content-Type для POST запросов"""
        
        result = {"valid": True, "errors": [], "details": {}}
        
        content_type = request.headers.get("content-type", "")
        result["details"]["value"] = content_type
        
        # Для POST запросов Content-Type обязателен
        if request.method == "POST":
            if not content_type:
                result["valid"] = False
                result["errors"].append("Content-Type header is required for POST requests")
                return result
            
            # Проверяем допустимые значения
            allowed_types = APIValidationService.DEFAULT_VALIDATION_RULES["content_type"]["allowed_values"]
            content_type_base = content_type.split(';')[0].strip().lower()
            
            if content_type_base not in [ct.split(';')[0].strip().lower() for ct in allowed_types]:
                result["valid"] = False
                result["errors"].append(f"Invalid Content-Type: {content_type}")
        
        return result
    
    @staticmethod
    def _validate_custom_rules(
        request: Request, 
        bank: Bank, 
        endpoint_type: str
    ) -> Dict[str, Any]:
        """Валидация кастомных правил банка"""
        
        result = {"valid": True, "errors": [], "details": {}}
        
        if not bank.validation_rules:
            return result
        
        try:
            rules = json.loads(bank.validation_rules)
            
            # Проверяем правила для конкретного типа эндпоинта
            endpoint_rules = rules.get(endpoint_type, {})
            
            # Валидация заголовков
            if "headers" in endpoint_rules:
                for header_name, header_rules in endpoint_rules["headers"].items():
                    header_value = request.headers.get(header_name.lower(), "")
                    
                    # Проверка на обязательность
                    if header_rules.get("required", False) and not header_value:
                        result["valid"] = False
                        result["errors"].append(f"Required header missing: {header_name}")
                        continue
                    
                    # Проверка паттерна
                    if "pattern" in header_rules and header_value:
                        if not re.match(header_rules["pattern"], header_value):
                            result["valid"] = False
                            result["errors"].append(f"Header {header_name} doesn't match pattern")
                    
                    # Проверка значений
                    if "allowed_values" in header_rules and header_value:
                        if header_value not in header_rules["allowed_values"]:
                            result["valid"] = False
                            result["errors"].append(f"Header {header_name} has invalid value")
            
            result["details"]["applied_rules"] = endpoint_rules
            
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            result["details"]["rule_parse_error"] = str(e)
        
        return result
    
    @staticmethod
    def _validate_security_patterns(request: Request) -> Dict[str, Any]:
        """Проверка подозрительных паттернов в запросе"""
        
        result = {"suspicious": False, "warnings": [], "details": {}}
        
        user_agent = request.headers.get("user-agent", "").lower()
        
        # Подозрительные паттерны
        suspicious_patterns = [
            ("automation_tools", r"(selenium|puppeteer|playwright|webdriver)"),
            ("testing_tools", r"(postman|insomnia|httpie)"),
            ("scripting", r"(python|php|ruby|perl|java)"),
            ("suspicious_keywords", r"(hack|exploit|inject|bypass)")
        ]
        
        detected_patterns = []
        for pattern_name, pattern in suspicious_patterns:
            if re.search(pattern, user_agent):
                detected_patterns.append(pattern_name)
                result["suspicious"] = True
                result["warnings"].append(f"Suspicious pattern detected: {pattern_name}")
        
        # Проверяем необычные заголовки
        unusual_headers = []
        for header in request.headers.keys():
            header_lower = header.lower()
            if header_lower.startswith(('x-debug', 'x-test', 'x-hack')):
                unusual_headers.append(header)
                result["suspicious"] = True
                result["warnings"].append(f"Unusual header detected: {header}")
        
        result["details"]["detected_patterns"] = detected_patterns
        result["details"]["unusual_headers"] = unusual_headers
        
        return result
    
    @staticmethod
    def create_validation_error_response(validation_result: Dict[str, Any]) -> HTTPException:
        """Создание HTTP ошибки на основе результата валидации"""
        
        error_details = {
            "error": "Request validation failed",
            "validation_errors": validation_result["errors"],
            "details": validation_result.get("validation_details", {})
        }
        
        if validation_result.get("warnings"):
            error_details["warnings"] = validation_result["warnings"]
        
        return HTTPException(
            status_code=400,
            detail=error_details
        )
