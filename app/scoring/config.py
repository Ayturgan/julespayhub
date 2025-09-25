"""
Конфигурационные файлы для модуля скоринга

Содержит настройки правил, подозрительные слова и другие конфигурации.
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import logging


class ScoringConfigManager:
    """
    Менеджер конфигурации модуля скоринга
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else Path(__file__).parent
        self.logger = logging.getLogger("scoring.config")
        
        # Загружаем конфигурации
        self.suspicious_words = self._load_suspicious_words()
        self.rules_config = self._load_rules_config()
        self.limits_config = self._load_limits_config()
    
    def _load_suspicious_words(self) -> Dict[str, List[str]]:
        """Загрузить список подозрительных слов"""
        config_file = self.config_dir / "suspicious_words.json"
        
        # Значения по умолчанию
        default_words = {
            "fraud_keywords": [
                "мошенничество", "обман", "развод", "кидалово", "лохотрон",
                "халява", "бесплатно", "быстрые деньги", "заработок без вложений",
                "пирамида", "скам", "развод", "обманул", "украли"
            ],
            "money_laundering_keywords": [
                "отмывание", "обналичивание", "конвертация", "обмен валют",
                "черный нал", "серые схемы", "уход от налогов", "оффшор",
                "теневая экономика", "нелегальные операции"
            ],
            "gambling_keywords": [
                "ставки", "казино", "покер", "рулетка", "слоты", "букмекер",
                "азартные игры", "лотерея", "тотализатор", "игровые автоматы"
            ],
            "drugs_keywords": [
                "наркотики", "наркота", "трава", "спайс", "соль", "амфетамин",
                "кокаин", "героин", "марихуана", "конопля", "гашиш", "ЛСД"
            ],
            "weapons_keywords": [
                "оружие", "пистолет", "автомат", "граната", "взрывчатка",
                "бомба", "патроны", "пули", "нож", "холодное оружие"
            ],
            "prostitution_keywords": [
                "проституция", "эскорт", "массаж", "интим", "секс услуги",
                "девушки", "вызов", "сопровождение"
            ],
            "terrorism_keywords": [
                "терроризм", "теракт", "взрыв", "подрыв", "радикализм",
                "экстремизм", "джихад", "халифат"
            ],
            "sanctions_keywords": [
                "санкции", "эмбарго", "блокировка", "заморозка активов",
                "запрещенная деятельность"
            ]
        }
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded_words = json.load(f)
                    self.logger.info(f"Загружены подозрительные слова из {config_file}")
                    return loaded_words
            else:
                # Создаем файл с значениями по умолчанию
                self._save_suspicious_words(default_words)
                self.logger.info(f"Создан файл подозрительных слов: {config_file}")
                return default_words
                
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке подозрительных слов: {e}")
            return default_words
    
    def _save_suspicious_words(self, words: Dict[str, List[str]]) -> None:
        """Сохранить список подозрительных слов"""
        config_file = self.config_dir / "suspicious_words.json"
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Подозрительные слова сохранены в {config_file}")
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении подозрительных слов: {e}")
    
    def _load_rules_config(self) -> Dict[str, Any]:
        """Загрузить конфигурацию правил"""
        config_file = self.config_dir / "rules_config.json"
        
        default_config = {
            "amount_limit": {
                "max_single_transaction": 500000.0,
                "max_daily_amount": 1000000.0,
                "max_monthly_amount": 5000000.0,
                "suspicious_round_amounts": True,
                "weight": 2.0,
                "enabled": True
            },
            "frequency": {
                "max_transactions_per_hour": 10,
                "max_transactions_per_day": 50,
                "max_transactions_per_week": 200,
                "weight": 1.5,
                "enabled": True
            },
            "suspicious_patterns": {
                "case_sensitive": False,
                "exact_match": False,
                "weight": 3.0,
                "enabled": True,
                "categories": ["fraud_keywords", "money_laundering_keywords", "gambling_keywords"]
            },
            "geolocation": {
                "allowed_countries": ["KG", "KZ", "UZ", "TJ", "RU", "CN"],
                "suspicious_countries": ["AF", "IR", "KP", "SY"],
                "require_ip": False,
                "weight": 1.0,
                "enabled": True
            },
            "phone_number": {
                "validate_format": True,
                "check_suspicious_patterns": True,
                "weight": 1.0,
                "enabled": True
            },
            "bank_code": {
                "valid_bank_codes": ["DEMIR", "OPTIMA", "MOBILE", "BTA", "RSK", "KYRGYZSTAN"],
                "check_self_payment": True,
                "weight": 1.0,
                "enabled": True
            },
            "time_based": {
                "business_hours_start": 9,
                "business_hours_end": 18,
                "weekend_penalty": True,
                "night_penalty": True,
                "weight": 0.5,
                "enabled": True
            }
        }
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    self.logger.info(f"Загружена конфигурация правил из {config_file}")
                    return loaded_config
            else:
                # Создаем файл с значениями по умолчанию
                self._save_rules_config(default_config)
                self.logger.info(f"Создан файл конфигурации правил: {config_file}")
                return default_config
                
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке конфигурации правил: {e}")
            return default_config
    
    def _save_rules_config(self, config: Dict[str, Any]) -> None:
        """Сохранить конфигурацию правил"""
        config_file = self.config_dir / "rules_config.json"
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Конфигурация правил сохранена в {config_file}")
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении конфигурации правил: {e}")
    
    def _load_limits_config(self) -> Dict[str, Any]:
        """Загрузить конфигурацию лимитов"""
        config_file = self.config_dir / "limits_config.json"
        
        default_limits = {
            "daily_transaction_limit": 1000000.0,
            "monthly_transaction_limit": 30000000.0,
            "max_transactions_per_hour": 10,
            "max_transactions_per_day": 50,
            "duplicate_check_minutes": 5,
            "history_lookup_days": 30,
            "allow_threshold": 30,
            "review_threshold": 70,
            "block_threshold": 90
        }
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded_limits = json.load(f)
                    self.logger.info(f"Загружены лимиты из {config_file}")
                    return loaded_limits
            else:
                # Создаем файл с значениями по умолчанию
                self._save_limits_config(default_limits)
                self.logger.info(f"Создан файл лимитов: {config_file}")
                return default_limits
                
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке лимитов: {e}")
            return default_limits
    
    def _save_limits_config(self, limits: Dict[str, Any]) -> None:
        """Сохранить конфигурацию лимитов"""
        config_file = self.config_dir / "limits_config.json"
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(limits, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Лимиты сохранены в {config_file}")
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении лимитов: {e}")
    
    def get_suspicious_words(self, category: Optional[str] = None) -> List[str]:
        """Получить подозрительные слова по категории"""
        if category:
            return self.suspicious_words.get(category, [])
        
        # Возвращаем все слова из всех категорий
        all_words = []
        for words_list in self.suspicious_words.values():
            all_words.extend(words_list)
        return all_words
    
    def get_rule_config(self, rule_name: str) -> Dict[str, Any]:
        """Получить конфигурацию конкретного правила"""
        return self.rules_config.get(rule_name, {})
    
    def get_limit(self, limit_name: str) -> Any:
        """Получить значение лимита"""
        return self.limits_config.get(limit_name)
    
    def update_suspicious_words(self, category: str, words: List[str]) -> None:
        """Обновить подозрительные слова в категории"""
        self.suspicious_words[category] = words
        self._save_suspicious_words(self.suspicious_words)
        self.logger.info(f"Обновлены подозрительные слова в категории '{category}': {len(words)} слов")
    
    def update_rule_config(self, rule_name: str, config: Dict[str, Any]) -> None:
        """Обновить конфигурацию правила"""
        self.rules_config[rule_name] = config
        self._save_rules_config(self.rules_config)
        self.logger.info(f"Обновлена конфигурация правила '{rule_name}'")
    
    def update_limits(self, limits: Dict[str, Any]) -> None:
        """Обновить лимиты"""
        self.limits_config.update(limits)
        self._save_limits_config(self.limits_config)
        self.logger.info(f"Обновлены лимиты: {list(limits.keys())}")


# Глобальный экземпляр менеджера конфигурации
_config_manager: Optional[ScoringConfigManager] = None


def get_config_manager(config_dir: Optional[str] = None) -> ScoringConfigManager:
    """Получить экземпляр менеджера конфигурации"""
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ScoringConfigManager(config_dir)
    
    return _config_manager