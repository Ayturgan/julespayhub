# Test endpoint for admin authentication
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_admin_user

router = APIRouter()

@router.get("/test-auth")
async def test_admin_auth(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Простой тестовый эндпоинт для проверки аутентификации админа
    """
    return {
        "status": "success",
        "message": "Admin authentication working",
        "admin": current_admin
    }

@router.get("/test-db")
async def test_database(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Тестовый эндпоинт для проверки подключения к базе данных
    """
    try:
        # Простой запрос к базе данных
        result = db.execute("SELECT 1 as test").scalar()
        return {
            "status": "success",
            "message": "Database connection working",
            "test_result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_admin_user

router = APIRouter()

@router.get("/test-auth")
async def test_admin_auth(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Простой тестовый эндпоинт для проверки аутентификации админа
    """
    return {
        "status": "success",
        "message": "Admin authentication working",
        "admin": current_admin
    }

@router.get("/test-db")
async def test_database(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Тестовый эндпоинт для проверки подключения к базе данных
    """
    try:
        # Простой запрос к базе данных
        result = db.execute("SELECT 1 as test").scalar()
        return {
            "status": "success",
            "message": "Database connection working",
            "test_result": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
