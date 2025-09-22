# Bank adapters management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank
from app.services.bank_adapter_service import bank_adapter_service, BankConfiguration, BankType
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

# === АДАПТЕРЫ БАНКОВ ===

@router.get("/adapters/banks")
async def get_bank_adapters():
    """
    Получение списка всех адаптеров банков
    """
    try:
        registered_banks = bank_adapter_service.get_all_registered_banks()
        
        return {
            "total_banks": len(registered_banks),
            "registered_banks": registered_banks,
            "available_bank_types": [bt.value for bt in BankType],
            "adapter_registry": {
                bt.value: bt.name for bt in BankType
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get bank adapters: {str(e)}"
        )

@router.post("/adapters/banks/{bank_code}/configure")
async def configure_bank_adapter(
    bank_code: str,
    bank_type: str,
    name: str,
    api_version: str = "1.0",
    timeout_seconds: int = 30,
    amount_format: str = "decimal",
    phone_format: str = "international",
    max_amount: Optional[float] = None,
    min_amount: Optional[float] = None,
    supported_currencies: List[str] = ["KGS"],
    custom_headers: Optional[Dict[str, str]] = None,
    custom_parameters: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db)
):
    """
    Настройка адаптера для банка
    """
    try:
        # Проверяем что банк существует
        bank = db.query(Bank).filter(Bank.code == bank_code).first()
        if not bank:
            raise HTTPException(status_code=404, detail="Bank not found")
        
        # Валидируем тип банка
        try:
            bank_type_enum = BankType(bank_type)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid bank type. Available: {[bt.value for bt in BankType]}"
            )
        
        # Создаем конфигурацию
        config = BankConfiguration(
            bank_code=bank_code,
            bank_type=bank_type_enum,
            name=name,
            api_version=api_version,
            timeout_seconds=timeout_seconds,
            amount_format=amount_format,
            phone_format=phone_format,
            max_amount=max_amount,
            min_amount=min_amount,
            supported_currencies=supported_currencies,
            custom_headers=custom_headers or {},
            custom_parameters=custom_parameters or {}
        )
        
        # Регистрируем адаптер
        bank_adapter_service.register_bank_configuration(config)
        
        return {
            "message": f"Bank adapter configured for {bank_code}",
            "bank_code": bank_code,
            "bank_type": bank_type,
            "configuration": config.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure bank adapter: {str(e)}"
        )

@router.get("/adapters/banks/{bank_code}")
async def get_bank_adapter_info(bank_code: str):
    """
    Получение информации об адаптере банка
    """
    try:
        # Получаем конфигурацию
        config = bank_adapter_service.get_configuration(bank_code)
        if not config:
            raise HTTPException(
                status_code=404,
                detail=f"No adapter configuration found for bank {bank_code}"
            )
        
        # Получаем возможности банка
        capabilities = bank_adapter_service.get_bank_capabilities(bank_code)
        
        # Проверяем есть ли адаптер
        adapter = bank_adapter_service.get_adapter(bank_code)
        
        return {
            "bank_code": bank_code,
            "has_adapter": adapter is not None,
            "configuration": config.to_dict(),
            "capabilities": capabilities,
            "adapter_class": type(adapter).__name__ if adapter else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get bank adapter info: {str(e)}"
        )

@router.get("/adapters/banks/{bank_code}/status")
async def get_bank_adapter_status(
    bank_code: str,
    db: Session = Depends(get_db)
):
    """
    Получение статуса адаптера банка
    """
    try:
        # Проверяем что банк существует
        bank = db.query(Bank).filter(Bank.code == bank_code).first()
        if not bank:
            raise HTTPException(status_code=404, detail="Bank not found")
        
        # Получаем конфигурацию
        config = bank_adapter_service.get_configuration(bank_code)
        if not config:
            raise HTTPException(
                status_code=404,
                detail=f"No adapter configuration found for bank {bank_code}"
            )
        
        # Получаем возможности банка
        capabilities = bank_adapter_service.get_bank_capabilities(bank_code)
        
        # Проверяем есть ли адаптер
        adapter = bank_adapter_service.get_adapter(bank_code)
        
        return {
            "bank_code": bank_code,
            "has_adapter": adapter is not None,
            "configuration": config.to_dict(),
            "capabilities": capabilities,
            "adapter_class": type(adapter).__name__ if adapter else None,
            "status": "active" if adapter else "inactive"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to test bank adapter: {str(e)}"
        )

@router.post("/adapters/initialize-defaults")
async def initialize_default_adapters():
    """
    Инициализация адаптеров по умолчанию для демонстрации
    """
    try:
        default_configs = bank_adapter_service.create_default_configurations()
        
        return {
            "message": "Default bank adapters initialized",
            "created_configurations": [config.to_dict() for config in default_configs],
            "total_created": len(default_configs)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize default adapters: {str(e)}"
        )

@router.get("/adapters/types")
async def get_bank_adapter_types():
    """
    Получение доступных типов адаптеров банков
    """
    
    bank_types_info = []
    
    for bank_type in BankType:
        bank_types_info.append({
            "value": bank_type.value,
            "name": bank_type.name,
            "description": _get_bank_type_description(bank_type)
        })
    
    return {
        "available_types": bank_types_info,
        "total_types": len(BankType),
        "default_type": BankType.STANDARD.value
    }

def _get_bank_type_description(bank_type: BankType) -> str:
    """Получение описания типа банка"""
    
    descriptions = {
        BankType.STANDARD: "Стандартная интеграция для большинства банков",
        BankType.LEGACY: "Для устаревших банковских систем с особыми требованиями",
        BankType.ENTERPRISE: "Для крупных корпоративных банков",
        BankType.MOBILE_FIRST: "Для мобильных банков и финтех приложений",
        BankType.FINTECH: "Для современных финтех компаний",
        BankType.CUSTOM: "Полностью кастомная интеграция"
    }
    
    return descriptions.get(bank_type, "Специализированный тип адаптера")