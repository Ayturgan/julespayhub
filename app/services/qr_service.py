import base64
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional, List

import qrcode
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.merchant import Merchant
from app.models.unified import UnifiedQRCode
from app.schemas.unified_qr_code import (
    UnifiedQRCodeCreate,
    UnifiedQRCodeResponse,
    QRCodeUpdateRequest,
)
from app.services.merchant_auth_service import MerchantAuthService


class QRService:
    @staticmethod
    def create_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_data: UnifiedQRCodeCreate,
    ) -> UnifiedQRCodeResponse:
        """Создание унифицированного QR-кода для продавца"""
        auth_service = MerchantAuthService(db)
        if qr_data.amount:
            limits_check = auth_service.check_merchant_limits(
                merchant, qr_data.amount
            )
            if not limits_check["within_limits"]:
                raise ValueError(f"Превышен {limits_check['limit_type']} лимит")

        qr_token = str(uuid.uuid4())
        expires_at = None
        if qr_data.expires_in_minutes:
            expires_at = datetime.now(timezone.utc) + timedelta(
                minutes=qr_data.expires_in_minutes
            )

        qr_url = f"{settings.BASE_URL}/pay?token={qr_token}"
        qr_image_base64 = QRService.generate_qr_image(qr_url)

        qr_code = UnifiedQRCode(
            name=qr_data.name,
            description=qr_data.description,
            amount=qr_data.amount,
            currency=qr_data.currency,
            merchant_id=merchant.id,
            outlet_id=qr_data.outlet_id,
            qr_token=qr_token,
            qr_url=qr_url,
            qr_image_base64=qr_image_base64,
            expires_at=expires_at,
            max_uses=qr_data.max_uses,
        )

        db.add(qr_code)
        db.commit()
        db.refresh(qr_code)

        return UnifiedQRCodeResponse.model_validate(qr_code)

    @staticmethod
    def get_merchant_qr_codes(
        db: Session, merchant: Merchant, skip: int = 0, limit: int = 100
    ) -> List[UnifiedQRCodeResponse]:
        """Получение списка QR-кодов для продавца"""
        qr_codes = (
            db.query(UnifiedQRCode)
            .filter(UnifiedQRCode.merchant_id == merchant.id)
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [UnifiedQRCodeResponse.model_validate(qr) for qr in qr_codes]

    @staticmethod
    def get_merchant_qr_code(
        db: Session, merchant: Merchant, qr_code_id: int
    ) -> Optional[UnifiedQRCodeResponse]:
        """Получение одного QR-кода по ID"""
        qr_code = (
            db.query(UnifiedQRCode)
            .filter(
                UnifiedQRCode.id == qr_code_id,
                UnifiedQRCode.merchant_id == merchant.id,
            )
            .first()
        )

        if not qr_code:
            return None

        return UnifiedQRCodeResponse.model_validate(qr_code)

    @staticmethod
    def update_merchant_qr_code(
        db: Session,
        merchant: Merchant,
        qr_code_id: int,
        qr_data: QRCodeUpdateRequest,
    ) -> Optional[UnifiedQRCodeResponse]:
        """Обновление QR-кода"""
        qr_code = (
            db.query(UnifiedQRCode)
            .filter(
                UnifiedQRCode.id == qr_code_id,
                UnifiedQRCode.merchant_id == merchant.id,
            )
            .first()
        )

        if not qr_code:
            return None

        update_data = qr_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(qr_code, key, value)

        db.commit()
        db.refresh(qr_code)

        return UnifiedQRCodeResponse.model_validate(qr_code)

    @staticmethod
    def delete_merchant_qr_code(
        db: Session, merchant: Merchant, qr_code_id: int
    ) -> bool:
        """Удаление QR-кода"""
        qr_code = (
            db.query(UnifiedQRCode)
            .filter(
                UnifiedQRCode.id == qr_code_id,
                UnifiedQRCode.merchant_id == merchant.id,
            )
            .first()
        )

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


