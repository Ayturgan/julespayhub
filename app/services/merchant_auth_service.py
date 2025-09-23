import secrets
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.merchant import Merchant
from app.models.unified import UnifiedPayment
from app.schemas.merchant import MerchantRegister, MerchantLogin
from app.services.error_handling_service import ErrorHandlingService, ErrorCode, ErrorSeverity
from fastapi import HTTPException

class MerchantAuthService:
    """Сервис для аутентификации и управления продавцами"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def register_merchant(self, merchant_data: MerchantRegister) -> Merchant:
        """Регистрация нового продавца"""
        
        # Проверяем уникальность email и ИНН
        existing_merchant = self.db.query(Merchant).filter(
            (Merchant.email == merchant_data.email) | 
            (Merchant.inn == merchant_data.inn)
        ).first()
        
        if existing_merchant:
            err = ErrorHandlingService.create_validation_error(
                "email_or_inn",
                merchant_data.email,
                "Продавец с таким email или ИНН уже зарегистрирован"
            )
            status_code = ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(err.code, 400)
            raise HTTPException(status_code=status_code, detail=err.to_dict())
        
        # Генерируем API ключи
        api_key = f"merchant_{secrets.token_urlsafe(32)}"
        api_secret = secrets.token_urlsafe(64)
        
        # Хешируем пароль
        import bcrypt
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(merchant_data.password.encode('utf-8'), salt).decode('utf-8')
        
        # Создаем продавца
        merchant = Merchant(
            name=merchant_data.name,
            legal_name=merchant_data.legal_name,
            inn=merchant_data.inn,
            kpp=merchant_data.kpp,
            email=merchant_data.email,
            phone=merchant_data.phone,
            address=merchant_data.address,
            bank_account=merchant_data.bank_account,
            bank_name=merchant_data.bank_name,
            bank_bik=merchant_data.bank_bik,
            api_key=api_key,
            api_secret=api_secret,
            hashed_password=hashed_password
        )
        
        self.db.add(merchant)
        self.db.commit()
        self.db.refresh(merchant)
        
        return merchant
    
    def authenticate_merchant(self, login_data: MerchantLogin) -> Optional[Merchant]:
        """Аутентификация продавца по email и паролю"""
        
        merchant = self.db.query(Merchant).filter(
            Merchant.email == login_data.email,
            Merchant.is_active == True
        ).first()
        
        if not merchant:
            return None
        
        # Проверяем пароль
        import bcrypt
        if not merchant.hashed_password or not bcrypt.checkpw(login_data.password.encode('utf-8'), merchant.hashed_password.encode('utf-8')):
            return None
        
        # Обновляем время последней активности
        merchant.last_activity = datetime.now(timezone.utc)
        self.db.commit()
        
        return merchant
    
    def verify_merchant_signature(
        self, 
        merchant: Merchant, 
        payload: str, 
        signature: str
    ) -> bool:
        """Проверка HMAC подписи от продавца"""
        
        expected_signature = hmac.new(
            merchant.api_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def get_merchant_by_api_key(self, api_key: str) -> Optional[Merchant]:
        """Получение продавца по API ключу"""
        
        return self.db.query(Merchant).filter(
            Merchant.api_key == api_key,
            Merchant.is_active == True
        ).first()
    
    def get_merchant_by_id(self, merchant_id: int) -> Optional[Merchant]:
        """Получение продавца по ID"""
        
        return self.db.query(Merchant).filter(
            Merchant.id == merchant_id,
            Merchant.is_active == True
        ).first()
    
    def update_merchant_activity(self, merchant_id: int) -> None:
        """Обновление времени последней активности продавца"""
        
        merchant = self.get_merchant_by_id(merchant_id)
        if merchant:
            merchant.last_activity = datetime.now(timezone.utc)
            self.db.commit()
    
    def check_merchant_limits(
        self, 
        merchant: Merchant, 
        amount: float
    ) -> Dict[str, Any]:
        """Проверка лимитов продавца"""
        
        # Получаем статистику за день
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        daily_payments = self.db.query(UnifiedPayment).filter(
            UnifiedPayment.merchant_id == merchant.id,
            UnifiedPayment.created_at >= today_start,
            UnifiedPayment.status == "completed"
        ).all()
        
        daily_total = sum(payment.amount for payment in daily_payments)
        
        # Проверяем дневной лимит
        if daily_total + amount > merchant.daily_limit:
            return {
                "within_limits": False,
                "limit_type": "daily",
                "current_total": daily_total,
                "limit": merchant.daily_limit,
                "remaining": merchant.daily_limit - daily_total
            }
        
        # Получаем статистику за месяц
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        
        monthly_payments = self.db.query(UnifiedPayment).filter(
            UnifiedPayment.merchant_id == merchant.id,
            UnifiedPayment.created_at >= month_start,
            UnifiedPayment.status == "completed"
        ).all()
        
        monthly_total = sum(payment.amount for payment in monthly_payments)
        
        # Проверяем месячный лимит
        if monthly_total + amount > merchant.monthly_limit:
            return {
                "within_limits": False,
                "limit_type": "monthly",
                "current_total": monthly_total,
                "limit": merchant.monthly_limit,
                "remaining": merchant.monthly_limit - monthly_total
            }
        
        return {
            "within_limits": True,
            "daily_total": daily_total,
            "monthly_total": monthly_total,
            "daily_remaining": merchant.daily_limit - daily_total,
            "monthly_remaining": merchant.monthly_limit - monthly_total
        }
    
    def create_merchant_session_token(self, merchant: Merchant) -> str:
        """Создание временного токена сессии для продавца"""
        
        # Создаем токен с временем жизни 24 часа
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        
        # Генерируем токен на основе API ключа и времени
        token_data = f"{merchant.api_key}:{expires_at.isoformat()}"
        session_token = hashlib.sha256(token_data.encode()).hexdigest()
        
        return session_token
    
    def validate_merchant_permissions(
        self, 
        merchant: Merchant, 
        required_permission: str
    ) -> bool:
        """Проверка прав доступа продавца"""
        
        # Базовая проверка активности
        if not merchant.is_active:
            return False
        
        # Проверка верификации для критических операций
        if required_permission in ["create_payment", "withdraw_funds"]:
            return merchant.is_verified
        
        # Для остальных операций достаточно активности
        return True
