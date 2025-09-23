from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin import AdminFullResponse, AdminProfileUpdate, AdminQRCodeCreate
from app.services.hybrid_logging_service import hybrid_logging_service
from app.services.two_phase_commit_service import two_phase_commit_service
from app.core.dependencies import get_current_admin_user
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import secrets

router = APIRouter()


# Эндпоинты для администраторов
@router.get("/admins")
async def get_admins(db: Session = Depends(get_db)):
    """Получение списка администраторов"""
    admins = db.query(Admin).all()
    return [
        {
            "id": admin.id,
            "username": admin.username,
            "email": admin.email,
            "full_name": admin.full_name,
            "is_active": admin.is_active,
            "is_superuser": admin.is_superuser,
            "created_at": admin.created_at.isoformat() if admin.created_at else None,
            "last_login": admin.last_login.isoformat() if admin.last_login else None
        }
        for admin in admins
    ]

@router.post("/admins")
async def create_admin(
    admin_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Создание нового администратора"""
    try:
        # Проверяем уникальность email и username
        existing_admin = db.query(Admin).filter(
            (Admin.email == admin_data.get("email")) | 
            (Admin.username == admin_data.get("username"))
        ).first()
        
        if existing_admin:
            raise HTTPException(status_code=400, detail="Администратор с таким email или username уже существует")
        
        # Создаем нового администратора
        new_admin = Admin(
            username=admin_data.get("username"),
            email=admin_data.get("email"),
            full_name=admin_data.get("full_name", ""),
            password_hash=admin_data.get("password"),  # В реальности нужно хешировать
            is_active=admin_data.get("is_active", True),
            is_superuser=admin_data.get("is_superuser", False)
        )
        
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
        
        return {"message": "Администратор создан успешно", "admin_id": new_admin.id}
        
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Ошибка создания администратора")

@router.patch("/admins/{admin_id}")
async def update_admin(
    admin_id: int,
    admin_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Обновление администратора"""
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    # Обновляем только переданные поля
    for field, value in admin_data.items():
        if hasattr(admin, field) and field != "id":
            setattr(admin, field, value)
    
    db.commit()
    return {"message": "Администратор обновлен успешно"}

@router.delete("/admins/{admin_id}")
async def delete_admin(admin_id: int, db: Session = Depends(get_db)):
    """Удаление администратора"""
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    db.delete(admin)
    db.commit()
    return {"message": "Администратор удален успешно"}

@router.post("/admins/{admin_id}/reset-password")
async def reset_admin_password(admin_id: int, db: Session = Depends(get_db)):
    """Сброс пароля администратора"""
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Администратор не найден")
    
    # В реальности здесь нужно генерировать и отправлять новый пароль
    new_password = secrets.token_urlsafe(12)
    admin.password_hash = new_password  # В реальности нужно хешировать
    
    db.commit()
    return {"message": "Пароль сброшен", "new_password": new_password}





# === ПРОФИЛЬ АДМИНА ===

@router.get("/profile", response_model=AdminFullResponse)
async def get_admin_profile(
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)  # Нужно будет добавить эту зависимость
):
    """
    Получение профиля текущего администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Создаем расширенный ответ с проверкой профиля
    admin_dict = {
        **admin.__dict__,
        'has_complete_profile': admin.has_complete_profile()
    }
    
    return AdminFullResponse(**admin_dict)

@router.put("/profile", response_model=AdminFullResponse)
async def update_admin_profile(
    profile_data: AdminProfileUpdate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Обновление профиля администратора
    """
    admin = db.query(Admin).filter(Admin.id == current_admin["id"]).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    # Обновляем только переданные поля
    for field, value in profile_data.dict(exclude_unset=True).items():
        setattr(admin, field, value)
    
    try:
        db.commit()
        db.refresh(admin)
        
        # Создаем расширенный ответ
        admin_dict = {
            **admin.__dict__,
            'has_complete_profile': admin.has_complete_profile()
        }
        
        return AdminFullResponse(**admin_dict)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating profile: {str(e)}")



