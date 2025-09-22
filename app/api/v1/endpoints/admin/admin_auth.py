from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.admin import AdminLogin, AdminCreate, AdminResponse, AdminToken, AdminUpdate, AdminPasswordChange, AdminFullResponse
from app.services.admin_auth_service import AdminAuthService
from app.models.admin import Admin
from typing import List

router = APIRouter()

@router.post("/login", response_model=AdminToken)
async def login_admin(
    login_data: AdminLogin,
    db: Session = Depends(get_db)
):
    """Вход админа в систему"""
    return AdminAuthService.login_admin(db, login_data)

@router.post("/register", response_model=AdminResponse)
async def register_admin(
    admin_data: AdminCreate,
    db: Session = Depends(get_db)
):
    """Регистрация нового админа (только для супер-админов)"""
    # В MVP разрешаем регистрацию всем, в продакшене добавить проверку супер-админа
    admin = AdminAuthService.create_admin(db, admin_data)
    return AdminResponse.from_orm(admin)

@router.get("/me", response_model=AdminFullResponse)
async def get_current_admin_info(
    current_admin: Admin = Depends(AdminAuthService.get_current_admin)
):
    """Получение информации о текущем админе"""
    # Создаем расширенный ответ с проверкой профиля
    admin_dict = {
        **current_admin.__dict__,
        'has_complete_profile': current_admin.has_complete_profile()
    }
    return AdminFullResponse(**admin_dict)

@router.put("/me", response_model=AdminResponse)
async def update_current_admin(
    admin_update: AdminUpdate,
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Обновление данных текущего админа"""
    if admin_update.email is not None:
        current_admin.email = admin_update.email
    if admin_update.full_name is not None:
        current_admin.full_name = admin_update.full_name
    if admin_update.role is not None:
        current_admin.role = admin_update.role.value
    if admin_update.is_active is not None:
        current_admin.is_active = admin_update.is_active
    
    db.commit()
    db.refresh(current_admin)
    return AdminResponse.from_orm(current_admin)

@router.post("/me/change-password")
async def change_admin_password(
    password_data: AdminPasswordChange,
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Смена пароля текущего админа"""
    if not current_admin.verify_password(password_data.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    current_admin.set_password(password_data.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}

@router.get("/admins", response_model=List[AdminResponse])
async def list_admins(
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Список всех админов (только для супер-админов)"""
    if current_admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    admins = db.query(Admin).all()
    return [AdminResponse.from_orm(admin) for admin in admins]

@router.get("/admins/{admin_id}", response_model=AdminResponse)
async def get_admin(
    admin_id: int,
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Получение информации об админе по ID"""
    if current_admin.role != "super_admin" and current_admin.id != admin_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    return AdminResponse.from_orm(admin)

@router.put("/admins/{admin_id}", response_model=AdminResponse)
async def update_admin(
    admin_id: int,
    admin_update: AdminUpdate,
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Обновление админа (только для супер-админов)"""
    if current_admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    if admin_update.email is not None:
        admin.email = admin_update.email
    if admin_update.full_name is not None:
        admin.full_name = admin_update.full_name
    if admin_update.role is not None:
        admin.role = admin_update.role.value
    if admin_update.is_active is not None:
        admin.is_active = admin_update.is_active
    
    db.commit()
    db.refresh(admin)
    return AdminResponse.from_orm(admin)

@router.delete("/admins/{admin_id}")
async def delete_admin(
    admin_id: int,
    current_admin: Admin = Depends(AdminAuthService.get_current_admin),
    db: Session = Depends(get_db)
):
    """Удаление админа (только для супер-админов)"""
    if current_admin.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    
    if current_admin.id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    db.delete(admin)
    db.commit()
    
    return {"message": "Admin deleted successfully"}
