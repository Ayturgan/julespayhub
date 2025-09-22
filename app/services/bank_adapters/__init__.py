"""
Фабрика для создания банковских адаптеров с поддержкой возвратов
"""

from typing import Dict, Type
from app.services.bank_adapter_service import BaseBankAdapter, BankConfiguration
from app.services.bank_adapters.optima_bank_adapter import OptimaBankAdapter, create_optima_bank_configuration
from app.services.bank_adapters.demir_bank_adapter import DemirBankAdapter, create_demir_bank_configuration
from app.services.bank_adapters.mobile_bank_adapter import MobileBankRefundAdapter, create_mobile_bank_configuration

# Реестр доступных адаптеров
BANK_ADAPTERS: Dict[str, Type[BaseBankAdapter]] = {
    "OPTIMA": OptimaBankAdapter,
    "DEMIR": DemirBankAdapter,
    "MOBILE": MobileBankRefundAdapter,
}

# Реестр конфигураций по умолчанию
BANK_CONFIGURATIONS: Dict[str, callable] = {
    "OPTIMA": create_optima_bank_configuration,
    "DEMIR": create_demir_bank_configuration,
    "MOBILE": create_mobile_bank_configuration,
}

def create_bank_adapter(bank_code: str, config: BankConfiguration = None) -> BaseBankAdapter:
    """
    Создание адаптера для банка
    
    Args:
        bank_code: Код банка (OPTIMA, DEMIR, MOBILE)
        config: Конфигурация банка (если None, используется конфигурация по умолчанию)
    
    Returns:
        Экземпляр адаптера банка
    
    Raises:
        ValueError: Если банк не поддерживается
    """
    
    bank_code = bank_code.upper()
    
    if bank_code not in BANK_ADAPTERS:
        supported_banks = ", ".join(BANK_ADAPTERS.keys())
        raise ValueError(
            f"Банк '{bank_code}' не поддерживается. "
            f"Поддерживаемые банки: {supported_banks}"
        )
    
    # Если конфигурация не предоставлена, используем конфигурацию по умолчанию
    if config is None:
        config_factory = BANK_CONFIGURATIONS.get(bank_code)
        if config_factory:
            config = config_factory()
        else:
            raise ValueError(f"Конфигурация по умолчанию для банка '{bank_code}' не найдена")
    
    # Создаем адаптер
    adapter_class = BANK_ADAPTERS[bank_code]
    return adapter_class(config)

def get_supported_banks() -> list:
    """Получение списка поддерживаемых банков"""
    return list(BANK_ADAPTERS.keys())

def get_bank_refund_support(bank_code: str) -> bool:
    """
    Проверка поддержки возвратов банком
    
    Args:
        bank_code: Код банка
    
    Returns:
        True если банк поддерживает возвраты, False в противном случае
    """
    
    try:
        adapter = create_bank_adapter(bank_code)
        return adapter.config.supports_refunds
    except (ValueError, AttributeError):
        return False

def get_bank_configuration(bank_code: str) -> BankConfiguration:
    """
    Получение конфигурации по умолчанию для банка
    
    Args:
        bank_code: Код банка
    
    Returns:
        Конфигурация банка
    
    Raises:
        ValueError: Если банк не поддерживается
    """
    
    bank_code = bank_code.upper()
    
    if bank_code not in BANK_CONFIGURATIONS:
        supported_banks = ", ".join(BANK_CONFIGURATIONS.keys())
        raise ValueError(
            f"Конфигурация для банка '{bank_code}' не найдена. "
            f"Поддерживаемые банки: {supported_banks}"
        )
    
    config_factory = BANK_CONFIGURATIONS[bank_code]
    return config_factory()

# Экспорт основных классов
__all__ = [
    "OptimaBankAdapter",
    "DemirBankAdapter", 
    "MobileBankRefundAdapter",
    "create_bank_adapter",
    "get_supported_banks",
    "get_bank_refund_support",
    "get_bank_configuration",
    "BANK_ADAPTERS",
    "BANK_CONFIGURATIONS"
]
