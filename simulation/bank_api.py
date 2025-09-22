from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank
from typing import List, Dict, Any

router = APIRouter(prefix="/api/banks", tags=["simulation-banks"])

@router.get("/")
async def get_available_banks(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Получение списка всех доступных банков для симуляции
    """
    banks = db.query(Bank).filter(Bank.is_active == True).all()
    
    return [
        {
            "id": bank.id,
            "code": bank.code,
            "name": bank.name,
            "bik": bank.bik,
            "webhook_url": bank.webhook_url,
            "is_active": bank.is_active
        }
        for bank in banks
    ]

@router.get("/{bank_code}")
async def get_bank_by_code(bank_code: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Получение информации о конкретном банке по коду
    """
    bank = db.query(Bank).filter(Bank.code == bank_code, Bank.is_active == True).first()
    
    if not bank:
        raise HTTPException(status_code=404, detail="Банк не найден")
    
    return {
        "id": bank.id,
        "code": bank.code,
        "name": bank.name,
        "bik": bank.bik,
        "webhook_url": bank.webhook_url,
        "is_active": bank.is_active
    }
