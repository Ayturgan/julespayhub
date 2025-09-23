"""
Сервис для работы с торговыми точками продавцов
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app.models.merchant import Merchant, TradingPoint
from app.models.unified import UnifiedPayment, UnifiedQRCode
from app.services.token_service import SecureTokenService
from app.core.config import settings
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
import uuid
import qrcode
import qrcode.image.svg as qrcode_svg
import io
import base64


class MerchantOutletService:
    """Сервис для работы с торговыми точками продавцов"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_outlet(
        self,
        merchant: Merchant,
        name: str,
        address: Optional[str] = None,
        description: Optional[str] = None
    ) -> TradingPoint:
        """
        Создает новую торговую точку
        """
        outlet = TradingPoint(
            merchant_id=merchant.id,
            name=name,
            address=address,
            description=description,
            status="ACTIVE"
        )
        
        self.db.add(outlet)
        self.db.commit()
        self.db.refresh(outlet)
        
        return outlet
    
    def list_outlets(self, merchant: Merchant) -> List[TradingPoint]:
        """
        Получает список торговых точек продавца
        """
        return self.db.query(TradingPoint).filter(
            TradingPoint.merchant_id == merchant.id
        ).order_by(TradingPoint.created_at.desc()).all()
    
    def get_outlet(
        self,
        merchant: Merchant,
        outlet_id: int
    ) -> TradingPoint:
        """
        Получает торговую точку по ID с проверкой принадлежности
        """
        outlet = self.db.query(TradingPoint).filter(
            TradingPoint.id == outlet_id,
            TradingPoint.merchant_id == merchant.id
        ).first()
        
        if not outlet:
            raise HTTPException(status_code=404, detail="Outlet not found")
        
        return outlet
    
    def update_outlet(
        self,
        merchant: Merchant,
        outlet_id: int,
        name: Optional[str] = None,
        address: Optional[str] = None,
        description: Optional[str] = None
    ) -> TradingPoint:
        """
        Обновляет торговую точку
        """
        outlet = self.get_outlet(merchant, outlet_id)
        
        if name is not None:
            outlet.name = name
        if address is not None:
            outlet.address = address
        if description is not None:
            outlet.description = description
            
        outlet.updated_at = datetime.now(timezone.utc)
        
        self.db.commit()
        self.db.refresh(outlet)
        
        return outlet
    
    def archive_outlet(self, merchant: Merchant, outlet_id: int) -> Dict[str, str]:
        """
        Архивирует торговую точку и деактивирует связанные QR коды
        """
        outlet = self.get_outlet(merchant, outlet_id)
        
        outlet.status = "ARCHIVED"
        outlet.updated_at = datetime.now(timezone.utc)
        
        # Деактивируем связанные статические QR
        self.db.query(UnifiedQRCode).filter(
            UnifiedQRCode.merchant_id == merchant.id,
            UnifiedQRCode.outlet_id == outlet_id
        ).update({UnifiedQRCode.is_active: False})
        
        self.db.commit()
        self.db.refresh(outlet)
        
        return {"status": "success", "message": "Outlet archived"}
    
    def activate_outlet(self, merchant: Merchant, outlet_id: int) -> Dict[str, str]:
        """
        Активирует торговую точку
        """
        outlet = self.get_outlet(merchant, outlet_id)
        
        outlet.status = "ACTIVE"
        outlet.updated_at = datetime.now(timezone.utc)
        
        self.db.commit()
        self.db.refresh(outlet)
        
        return {"status": "success", "message": "Outlet activated"}
    
    def generate_outlet_qr(
        self,
        merchant: Merchant,
        outlet_id: int,
        format: str = "png"
    ) -> Dict[str, Any]:
        """
        Генерирует статический QR код для торговой точки
        """
        outlet = self.get_outlet(merchant, outlet_id)
        
        # Создаем UnifiedQRCode c outlet_id и без суммы
        qr_token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=365)
        
        # Создаем данные для токена
        payment_data_for_token = {
            "receiver_account": merchant.bank_account,
            "receiver_bank_code": "TESTBANK",
            "amount": None,
            "payment_reference": f"OUTLET-{outlet.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
        
        secure_token = SecureTokenService.generate_secure_token(
            payment_data_for_token,
            token_uuid=qr_token,
            expires_at=expires_at,
        )
        
        qr_url = f"{settings.BASE_URL}/pay?token={secure_token}"

        qr_code = UnifiedQRCode(
            name=f"Outlet QR: {outlet.name}",
            description=f"Статический QR для точки {outlet.name}",
            amount=None,
            currency="KGS",
            merchant_id=merchant.id,
            outlet_id=outlet.id,
            qr_token=qr_token,
            qr_url=qr_url,
            expires_at=expires_at
        )
        
        self.db.add(qr_code)
        self.db.commit()
        self.db.refresh(qr_code)
        
        # Генерация изображения
        if format == "svg":
            factory = qrcode_svg.SvgImage
            img = qrcode.make(qr_url, image_factory=factory)
            output = io.BytesIO()
            img.save(output)
            data = output.getvalue().decode()
            data_uri = f"data:image/svg+xml;utf8,{data}"
        else:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4
            )
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            data_uri = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
        
        return {
            "status": "success",
            "data": {
                "qr_url": qr_url,
                "image_data_uri": data_uri,
                "format": format,
            },
            "timestamp": datetime.now().isoformat()
        }
    
    def get_outlet_stats(
        self,
        merchant: Merchant,
        outlet_id: int,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Получает статистику платежей по торговой точке
        """
        outlet = self.get_outlet(merchant, outlet_id)
        
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Получаем статистику платежей по этой точке
        stats = self.db.query(
            func.count(UnifiedPayment.id).label('payments_count'),
            func.sum(UnifiedPayment.amount).label('total_amount')
        ).filter(
            UnifiedPayment.merchant_id == merchant.id,
            UnifiedPayment.outlet_id == outlet_id,
            UnifiedPayment.status == 'completed',
            UnifiedPayment.created_at >= since
        ).first()
        
        payments_count = stats.payments_count or 0
        total_amount = float(stats.total_amount or 0)
        
        return {
            "status": "success",
            "data": {
                "outlet_id": outlet_id,
                "outlet_name": outlet.name,
                "hours": hours,
                "payments_count": payments_count,
                "total_amount": total_amount,
                "currency": "KGS"
            },
            "timestamp": datetime.now().isoformat()
        }
    
    def get_outlets_distribution(
        self,
        merchant: Merchant,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Получает распределение оборота по торговым точкам
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Подтянем названия точек
        outlets = self.db.query(TradingPoint.id, TradingPoint.name).filter(
            TradingPoint.merchant_id == merchant.id
        ).all()
        outlet_names = {oid: oname for oid, oname in outlets}
        
        rows = self.db.query(
            UnifiedPayment.outlet_id.label('outlet_id'),
            func.count(UnifiedPayment.id).label('payments_count'),
            func.sum(UnifiedPayment.amount).label('total_amount')
        ).filter(
            UnifiedPayment.merchant_id == merchant.id,
            UnifiedPayment.created_at >= since,
            UnifiedPayment.status == 'completed',
            UnifiedPayment.outlet_id.isnot(None)
        ).group_by(UnifiedPayment.outlet_id).all()
        
        data = []
        for row in rows:
            oid = row.outlet_id
            data.append({
                "outlet_id": oid,
                "outlet_name": outlet_names.get(oid, f"ID {oid}"),
                "payments_count": int(row.payments_count or 0),
                "total_amount": float(row.total_amount or 0.0)
            })
        
        # Также можно вернуть total_sum для нормализации на клиенте
        total_sum = sum(item["total_amount"] for item in data) if data else 0.0
        
        return {
            "status": "success",
            "data": data,
            "total_amount": total_sum,
            "timestamp": datetime.now().isoformat()
        }
