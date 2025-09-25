"""
Pydantic схемы для модуля скоринга

Определяет структуры данных для передачи в сервис скоринга
и для получения результатов оценки рисков.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ScoringDecision(str, Enum):
    """Решения системы скоринга"""
    ALLOW = "allow"        # Разрешить транзакцию
    REVIEW = "review"      # Требуется ручная проверка
    BLOCK = "block"        # Заблокировать транзакцию


class TransactionDataForScoring(BaseModel):
    """
    Данные транзакции, необходимые для оценки рисков
    """
    
    # Основная информация о транзакции
    amount: float = Field(..., description="Сумма транзакции")
    currency: str = Field(default="KGS", description="Валюта транзакции")
    payment_reference: str = Field(..., description="Референс платежа")
    
    # Информация о плательщике
    payer_phone: Optional[str] = Field(None, description="Телефон плательщика")
    payer_bank_code: str = Field(..., description="Код банка плательщика")
    sender_account: Optional[str] = Field(None, description="Счет отправителя")
    
    # Информация о получателе
    receiver_account: str = Field(..., description="Счет получателя")
    receiver_bank_code: str = Field(..., description="Код банка получателя")
    receiver_name: str = Field(..., description="Имя получателя")
    
    # Техническая информация
    ip_address: Optional[str] = Field(None, description="IP-адрес плательщика")
    user_agent: Optional[str] = Field(None, description="User-Agent браузера")
    
    # Метаданные
    description: Optional[str] = Field(None, description="Описание платежа")
    merchant_id: Optional[int] = Field(None, description="ID продавца")
    token: Optional[str] = Field(None, description="Токен платежа")
    
    # Временные метки
    created_at: Optional[datetime] = Field(None, description="Время создания транзакции")
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Сумма должна быть положительной')
        return v
    
    @validator('currency')
    def validate_currency(cls, v):
        if len(v) != 3:
            raise ValueError('Код валюты должен состоять из 3 символов')
        return v.upper()


class ScoringResult(BaseModel):
    """
    Результат оценки рисков транзакции
    """
    
    # Основные результаты
    score: int = Field(..., ge=0, le=100, description="Скоринговый балл (0-100, где выше = рискованнее)")
    decision: ScoringDecision = Field(..., description="Решение системы")
    
    # Детализация
    errors: List[str] = Field(default_factory=list, description="Список нарушенных правил")
    warnings: List[str] = Field(default_factory=list, description="Предупреждения")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Дополнительные метаданные")
    
    # Временные метки
    evaluated_at: datetime = Field(default_factory=datetime.now, description="Время оценки")
    processing_time_ms: Optional[int] = Field(None, description="Время обработки в миллисекундах")
    
    # История транзакций (если доступна)
    transaction_history_count: Optional[int] = Field(None, description="Количество предыдущих транзакций")
    daily_transaction_count: Optional[int] = Field(None, description="Количество транзакций за день")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RuleEvaluationResult(BaseModel):
    """
    Результат оценки отдельного правила
    """
    
    rule_name: str = Field(..., description="Название правила")
    passed: bool = Field(..., description="Прошло ли правило")
    score_contribution: int = Field(default=0, description="Вклад в общий скоринговый балл")
    error_message: Optional[str] = Field(None, description="Сообщение об ошибке")
    warning_message: Optional[str] = Field(None, description="Предупреждение")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные правила")


class ComplianceCheckResult(BaseModel):
    """
    Результат проверки комплаенса
    """
    
    aml_check: bool = Field(..., description="Проверка на отмывание денег")
    kyc_check: bool = Field(..., description="Проверка клиента")
    sanctions_check: bool = Field(..., description="Проверка санкционных списков")
    pep_check: bool = Field(..., description="Проверка на ПЭП (политически значимые лица)")
    
    # Детали
    aml_details: Optional[Dict[str, Any]] = Field(None, description="Детали AML проверки")
    kyc_details: Optional[Dict[str, Any]] = Field(None, description="Детали KYC проверки")
    sanctions_details: Optional[Dict[str, Any]] = Field(None, description="Детали проверки санкций")
    pep_details: Optional[Dict[str, Any]] = Field(None, description="Детали PEP проверки")


class ScoringConfig(BaseModel):
    """
    Конфигурация системы скоринга
    """
    
    # Пороговые значения для решений
    allow_threshold: int = Field(default=30, ge=0, le=100, description="Порог для разрешения")
    review_threshold: int = Field(default=70, ge=0, le=100, description="Порог для ручной проверки")
    
    # Настройки правил
    enabled_rules: List[str] = Field(default_factory=list, description="Включенные правила")
    rule_weights: Dict[str, float] = Field(default_factory=dict, description="Веса правил")
    
    # Лимиты
    daily_transaction_limit: float = Field(default=1000000.0, description="Дневной лимит транзакций")
    monthly_transaction_limit: float = Field(default=30000000.0, description="Месячный лимит транзакций")
    
    # Настройки комплаенса
    enable_aml_check: bool = Field(default=True, description="Включить AML проверку")
    enable_kyc_check: bool = Field(default=True, description="Включить KYC проверку")
    enable_sanctions_check: bool = Field(default=True, description="Включить проверку санкций")
    enable_pep_check: bool = Field(default=True, description="Включить PEP проверку")
    
    @validator('review_threshold')
    def validate_thresholds(cls, v, values):
        if 'allow_threshold' in values and v <= values['allow_threshold']:
            raise ValueError('review_threshold должен быть больше allow_threshold')
        return v