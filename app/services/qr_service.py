import uuid
import qrcode
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from typing import Optional
from app.models.payment import PaymentRequest
from app.models.merchant import Merchant, QRCode
from app.schemas.unified import UnifiedQRCodeCreate, UnifiedQRCodeRead
from app.services.token_service import SecureTokenService
from app.services.reference_service import PaymentReferenceService
from app.services.qr_security_service import QRSecurityService
from app.services.merchant_auth_service import MerchantAuthService
from app.core.config import settings
from io import BytesIO
import base64
from app.services.timeline_service import TimelineService

class QRService:
    @staticmethod
    def generate_token() -> str:
        """Генерация уникального токена"""
        return str(uuid.uuid4())
    
    @staticmethod
    def create_payment_reference(token: str) -> str:
        """Создание уникального номера платежа"""
        date_str = datetime.now().strftime("%Y%m%d")
        short_token = token[:8]
        return f"QRHUB-{short_token}-{date_str}"
    
    @staticmethod
    def create_payment_request(
        db: Session, 
        payment_data: UnifiedQRCodeCreate,
        merchant_id: Optional[int] = None
    ) -> dict:
        """Создание платежного запроса и защищенного QR-кода"""
        
        # Генерируем уникальный payment_reference согласно ТЗ
        payment_reference = PaymentReferenceService.generate_payment_reference(db)
        
        # Если указан merchant_id, получаем банковские данные из профиля продавца
        receiver_account = payment_data.receiver_account
        receiver_bank_code = payment_data.receiver_bank_code
        receiver_name = payment_data.receiver_name
        
        if merchant_id:
            from app.models.merchant import Merchant
            merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
            if merchant and merchant.bank_name:
                # Ищем банк по названию
                from app.models.payment import Bank
                bank = db.query(Bank).filter(Bank.name == merchant.bank_name).first()
                if bank:
                    receiver_bank_code = bank.code
                    receiver_account = merchant.bank_account or payment_data.receiver_account
                    receiver_name = merchant.name or payment_data.receiver_name
        
        # Подготавливаем данные для создания защищенного токена
        token_payload = {
            "receiver_account": receiver_account,
            "receiver_bank_code": receiver_bank_code,
            "amount": payment_data.amount,
            "payment_reference": payment_reference
        }
        
        # Генерируем защищенный токен с подписью
        secure_token = SecureTokenService.generate_secure_token(
            token_payload, 
            settings.QR_TOKEN_EXPIRE_MINUTES
        )
        
        # Извлекаем UUID для хранения в БД
        token_uuid = SecureTokenService.extract_uuid_from_token(secure_token)
        
        # Создаем запись в БД
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.QR_TOKEN_EXPIRE_MINUTES)
        
        db_payment = PaymentRequest(
            token=token_uuid,  # Храним только UUID в БД
            receiver_account=receiver_account,
            receiver_bank_code=receiver_bank_code,
            receiver_name=receiver_name,
            description=payment_data.description,
            amount=payment_data.amount,
            currency=payment_data.currency,
            payment_reference=payment_reference,
            expires_at=expires_at,
            merchant_id=merchant_id  # Связываем с продавцом
        )
        
        db.add(db_payment)
        db.commit()
        db.refresh(db_payment)
        
        # Создаем защищенный QR URL с дополнительными мерами безопасности
        secure_qr_data = QRSecurityService.create_secure_qr_url(
            payment_data=token_payload,
            base_url=settings.BASE_URL,
            expires_in_minutes=settings.QR_TOKEN_EXPIRE_MINUTES,
            additional_security=True
        )

        # Событие таймлайна: QR создан
        try:
            TimelineService.record_event(
                db,
                payment_token=db_payment.token,
                event_type='qr_created',
                title='QR-код сгенерирован',
                description=f"Продавец {receiver_name} создал QR",
                actor='merchant',
                source='service',
                status='info',
                metadata={"payment_reference": payment_reference}
            )
        except Exception:
            pass
        
        return {
            "qr_url": secure_qr_data["qr_url"],
            "token": secure_token,
            "expires_in": settings.QR_TOKEN_EXPIRE_MINUTES * 60
        }
    
    @staticmethod
    def create_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_data: UnifiedQRCodeCreate
    ) -> UnifiedQRCodeRead:
        """Создание QR-кода для продавца"""
        
        # Проверяем лимиты продавца
        auth_service = MerchantAuthService(db)
        if qr_data.amount:
            limits_check = auth_service.check_merchant_limits(merchant, qr_data.amount)
            if not limits_check["within_limits"]:
                raise ValueError(f"Превышен {limits_check['limit_type']} лимит")
        
        # Генерируем уникальный токен для QR-кода
        qr_token = str(uuid.uuid4())
        
        # Устанавливаем время истечения (10 минут по умолчанию)
        if qr_data.expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.QR_TOKEN_EXPIRE_MINUTES)
        else:
            expires_at = qr_data.expires_at
        
        # Создаем QR-код в БД
        qr_code = QRCode(
            merchant_id=merchant.id,
            name=qr_data.name,
            description=qr_data.description,
            amount=qr_data.amount,
            currency=qr_data.currency or "KGS",
            qr_token=qr_token,
            qr_url=f"{settings.BASE_URL}/pay?token={qr_token}",
            expires_at=expires_at,  # Устанавливаем время истечения
            max_uses=qr_data.max_uses,
            is_active=True
        )
        
        db.add(qr_code)
        db.commit()
        db.refresh(qr_code)
        
        # Генерируем QR-изображение
        qr_image = QRService.generate_qr_image(qr_code.qr_url)
        
        return UnifiedQRCodeRead(
            id=qr_code.id,
            merchant_id=qr_code.merchant_id,
            admin_id=getattr(qr_code, 'admin_id', None),
            name=qr_code.name,
            description=qr_code.description,
            amount=qr_code.amount,
            currency=qr_code.currency,
            qr_token=qr_code.qr_token,
            qr_url=qr_code.qr_url,
            expires_at=qr_code.expires_at,
            max_uses=qr_code.max_uses,
            current_uses=qr_code.current_uses,
            is_active=qr_code.is_active,
            created_at=qr_code.created_at,
            updated_at=qr_code.updated_at
        )
    
    @staticmethod
    def get_merchant_qr_codes(
        db: Session,
        merchant: Merchant,
        skip: int = 0,
        limit: int = 100
    ) -> list[UnifiedQRCodeRead]:
        """Получение QR-кодов продавца"""
        
        qr_codes = db.query(QRCode).filter(
            QRCode.merchant_id == merchant.id
        ).offset(skip).limit(limit).all()
        
        return [
            UnifiedQRCodeRead(
                id=qr.id,
                merchant_id=qr.merchant_id,
                admin_id=getattr(qr, 'admin_id', None),
                name=qr.name,
                description=qr.description,
                amount=qr.amount,
                currency=qr.currency,
                qr_token=qr.qr_token,
                qr_url=qr.qr_url,
                expires_at=qr.expires_at,
                max_uses=qr.max_uses,
                current_uses=qr.current_uses,
                is_active=qr.is_active,
                created_at=qr.created_at,
                updated_at=qr.updated_at
            )
            for qr in qr_codes
        ]
    
    @staticmethod
    def get_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_code_id: int
    ) -> Optional[UnifiedQRCodeRead]:
        """Получение конкретного QR-кода продавца"""
        
        qr_code = db.query(QRCode).filter(
            QRCode.id == qr_code_id,
            QRCode.merchant_id == merchant.id
        ).first()
        
        if not qr_code:
            return None
        
        return UnifiedQRCodeRead(
            id=qr_code.id,
            merchant_id=qr_code.merchant_id,
            admin_id=getattr(qr_code, 'admin_id', None),
            name=qr_code.name,
            description=qr_code.description,
            amount=qr_code.amount,
            currency=qr_code.currency,
            qr_token=qr_code.qr_token,
            qr_url=qr_code.qr_url,
            expires_at=qr_code.expires_at,
            max_uses=qr_code.max_uses,
            current_uses=qr_code.current_uses,
            is_active=qr_code.is_active,
            created_at=qr_code.created_at,
            updated_at=qr_code.updated_at
        )
    
    @staticmethod
    def update_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_code_id: int,
        qr_data: UnifiedQRCodeCreate
    ) -> Optional[UnifiedQRCodeRead]:
        """Обновление QR-кода продавца"""
        
        qr_code = db.query(QRCode).filter(
            QRCode.id == qr_code_id,
            QRCode.merchant_id == merchant.id
        ).first()
        
        if not qr_code:
            return None
        
        # Обновляем данные
        qr_code.name = qr_data.name
        qr_code.description = qr_data.description
        qr_code.amount = qr_data.amount
        qr_code.currency = qr_data.currency or "KGS"
        qr_code.expires_at = qr_data.expires_at
        qr_code.max_uses = qr_data.max_uses
        
        db.commit()
        db.refresh(qr_code)
        
        return UnifiedQRCodeRead(
            id=qr_code.id,
            merchant_id=qr_code.merchant_id,
            admin_id=getattr(qr_code, 'admin_id', None),
            name=qr_code.name,
            description=qr_code.description,
            amount=qr_code.amount,
            currency=qr_code.currency,
            qr_token=qr_code.qr_token,
            qr_url=qr_code.qr_url,
            expires_at=qr_code.expires_at,
            max_uses=qr_code.max_uses,
            current_uses=qr_code.current_uses,
            is_active=qr_code.is_active,
            created_at=qr_code.created_at,
            updated_at=qr_code.updated_at
        )
    
    @staticmethod
    def delete_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_code_id: int
    ) -> bool:
        """Удаление QR-кода продавца"""
        
        qr_code = db.query(QRCode).filter(
            QRCode.id == qr_code_id,
            QRCode.merchant_id == merchant.id
        ).first()
        
        if not qr_code:
            return False
        
        db.delete(qr_code)
        db.commit()
        
        return True
    
    @staticmethod
    def generate_qr_image(qr_url: str) -> str:
        """Генерация изображения QR-кода в base64"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Конвертируем в base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"


