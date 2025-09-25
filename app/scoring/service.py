"""
Основной сервис скоринга

Оркестрирует процесс оценки рисков транзакций, применяя различные правила
и возвращая итоговое решение.
"""

import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .schemas import (
    TransactionDataForScoring, 
    ScoringResult, 
    ScoringDecision, 
    RuleEvaluationResult,
    ScoringConfig
)
from .rules import (
    BaseRule, 
    AmountLimitRule, 
    FrequencyRule, 
    GeolocationRule, 
    PhoneNumberRule, 
    BankCodeRule,
    TimeBasedRule
)
from .exceptions import ScoringError, ScoringServiceError


class ScoringService:
    """
    Основной сервис для оценки рисков транзакций
    """
    
    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.logger = logging.getLogger("scoring.service")
        
        # Инициализация правил
        self.rules = self._initialize_rules()
        
        # Кэш для хранения результатов (опционально)
        self.cache = {}
    
    def _initialize_rules(self) -> List[BaseRule]:
        """Инициализация правил скоринга"""
        rules = [
            AmountLimitRule(),
            FrequencyRule(),
            GeolocationRule(),
            PhoneNumberRule(),
            BankCodeRule(),
            TimeBasedRule()
        ]
        
        # Фильтруем только включенные правила
        enabled_rules = []
        for rule in rules:
            if rule.name in self.config.enabled_rules or not self.config.enabled_rules:
                enabled_rules.append(rule)
                self.logger.info(f"Правило '{rule.name}' включено с весом {rule.get_weight()}")
            else:
                self.logger.info(f"Правило '{rule.name}' отключено")
        
        return enabled_rules
    
    def evaluate_transaction(self, data: TransactionDataForScoring) -> ScoringResult:
        """
        Оценить транзакцию на предмет рисков
        
        Args:
            data: Данные транзакции для анализа
            
        Returns:
            ScoringResult: Результат оценки
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"Начинаем оценку транзакции: {data.payment_reference}")
            
            # Валидация входных данных
            self._validate_transaction_data(data)
            
            # Применение правил
            rule_results = self._apply_rules(data)
            
            # Вычисление итогового скорингового балла
            total_score = self._calculate_total_score(rule_results)
            
            # Принятие решения
            decision = self._make_decision(total_score)
            
            # Сбор ошибок и предупреждений
            errors, warnings = self._collect_messages(rule_results)
            
            # Получение истории транзакций (заглушка)
            transaction_history = self._get_transaction_history(data)
            
            processing_time = int((time.time() - start_time) * 1000)
            
            result = ScoringResult(
                score=total_score,
                decision=decision,
                errors=errors,
                warnings=warnings,
                metadata={
                    "rules_applied": len(rule_results),
                    "rule_results": [result.dict() for result in rule_results],
                    "config": self.config.dict()
                },
                processing_time_ms=processing_time,
                transaction_history_count=transaction_history.get("total_count"),
                daily_transaction_count=transaction_history.get("daily_count")
            )
            
            self.logger.info(
                f"Оценка завершена: балл={total_score}, решение={decision.value}, "
                f"время={processing_time}мс"
            )
            
            return result
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            self.logger.error(f"Ошибка при оценке транзакции: {str(e)}")
            
            raise ScoringServiceError(
                operation="evaluate_transaction",
                message=str(e),
                details={
                    "payment_reference": data.payment_reference,
                    "processing_time_ms": processing_time
                }
            )
    
    def _validate_transaction_data(self, data: TransactionDataForScoring) -> None:
        """Валидация данных транзакции"""
        if data.amount <= 0:
            raise ScoringError("Сумма транзакции должна быть положительной")
        
        if not data.payment_reference:
            raise ScoringError("Референс платежа обязателен")
        
        if not data.receiver_account or not data.receiver_bank_code:
            raise ScoringError("Данные получателя обязательны")
    
    def _apply_rules(self, data: TransactionDataForScoring) -> List[RuleEvaluationResult]:
        """Применить все правила к данным транзакции"""
        results = []
        
        for rule in self.rules:
            if not rule.is_enabled():
                continue
            
            try:
                result = rule.apply(data)
                results.append(result)
                
                self.logger.debug(
                    f"Правило '{rule.name}': прошло={result.passed}, "
                    f"балл={result.score_contribution}"
                )
                
            except Exception as e:
                self.logger.error(f"Ошибка при применении правила '{rule.name}': {str(e)}")
                
                # Создаем результат с ошибкой
                error_result = RuleEvaluationResult(
                    rule_name=rule.name,
                    passed=False,
                    score_contribution=50,  # Высокий балл за ошибку
                    error_message=f"Ошибка применения правила: {str(e)}"
                )
                results.append(error_result)
        
        return results
    
    def _calculate_total_score(self, rule_results: List[RuleEvaluationResult]) -> int:
        """Вычислить итоговый скоринговый балл"""
        total_score = 0
        total_weight = 0
        
        for result in rule_results:
            rule_weight = self.config.rule_weights.get(result.rule_name, 1.0)
            
            # Находим правило для получения его веса
            rule = next((r for r in self.rules if r.name == result.rule_name), None)
            if rule:
                rule_weight = rule.get_weight()
            
            weighted_score = result.score_contribution * rule_weight
            total_score += weighted_score
            total_weight += rule_weight
        
        # Нормализуем результат
        if total_weight > 0:
            normalized_score = min(100, int(total_score / total_weight))
        else:
            normalized_score = 0
        
        return normalized_score
    
    def _make_decision(self, score: int) -> ScoringDecision:
        """Принять решение на основе скорингового балла"""
        if score <= self.config.allow_threshold:
            return ScoringDecision.ALLOW
        elif score <= self.config.review_threshold:
            return ScoringDecision.REVIEW
        else:
            return ScoringDecision.BLOCK
    
    def _collect_messages(self, rule_results: List[RuleEvaluationResult]) -> tuple[List[str], List[str]]:
        """Собрать все ошибки и предупреждения из результатов правил"""
        errors = []
        warnings = []
        
        for result in rule_results:
            if result.error_message:
                errors.append(f"{result.rule_name}: {result.error_message}")
            if result.warning_message:
                warnings.append(f"{result.rule_name}: {result.warning_message}")
        
        return errors, warnings
    
    def _get_transaction_history(self, data: TransactionDataForScoring) -> Dict[str, Any]:
        """Получить историю транзакций (заглушка)"""
        # В реальной реализации здесь должен быть запрос к БД
        # для получения истории транзакций по payer_phone или sender_account
        return {
            "total_count": 0,
            "daily_count": 0,
            "weekly_count": 0,
            "monthly_count": 0
        }
    
    def get_rule_status(self) -> Dict[str, Any]:
        """Получить статус всех правил"""
        return {
            "total_rules": len(self.rules),
            "enabled_rules": [rule.name for rule in self.rules if rule.is_enabled()],
            "disabled_rules": [rule.name for rule in self.rules if not rule.is_enabled()],
            "rule_weights": {rule.name: rule.get_weight() for rule in self.rules},
            "config": self.config.dict()
        }
    
    def update_config(self, new_config: ScoringConfig) -> None:
        """Обновить конфигурацию скоринга"""
        self.config = new_config
        self.rules = self._initialize_rules()
        self.logger.info("Конфигурация скоринга обновлена")
    
    def test_rule(self, rule_name: str, data: TransactionDataForScoring) -> RuleEvaluationResult:
        """Тестировать конкретное правило"""
        rule = next((r for r in self.rules if r.name == rule_name), None)
        if not rule:
            raise ScoringError(f"Правило '{rule_name}' не найдено")
        
        return rule.apply(data)


# Глобальный экземпляр сервиса (singleton)
_scoring_service_instance: Optional[ScoringService] = None


def get_scoring_service(config: Optional[ScoringConfig] = None) -> ScoringService:
    """Получить экземпляр сервиса скоринга (singleton)"""
    global _scoring_service_instance
    
    if _scoring_service_instance is None:
        _scoring_service_instance = ScoringService(config)
    
    return _scoring_service_instance