from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.admin import Admin
from app.schemas.admin import AdminLogin, AdminCreate, AdminResponse
from typing import Optional
import jwt
from datetime import datetime, timezone, timedelta
import secrets
from app.core.config import settings

# Схема для Bearer токена
security = HTTPBearer()

class AdminAuthService:
    """Сервис аутентификации администраторов"""
    
    SECRET_KEY = "your-secret-key-here"  # В продакшене использовать переменную окружения
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
        """Создание JWT токена"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=AdminAuthService.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, AdminAuthService.SECRET_KEY, algorithm=AdminAuthService.ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> dict:
        """Проверка JWT токена"""
        try:
            payload = jwt.decode(token, AdminAuthService.SECRET_KEY, algorithms=[AdminAuthService.ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    @staticmethod
    def authenticate_admin(db: Session, username: str, password: str) -> Optional[Admin]:
        """Аутентификация админа по логину и паролю"""
        admin = db.query(Admin).filter(Admin.username == username).first()
        
        if not admin:
            return None
        
        # Проверяем, не заблокирован ли аккаунт
        if admin.is_locked():
            raise HTTPException(
                status_code=423, 
                detail=f"Account is locked until {admin.locked_until}"
            )
        
        # Проверяем пароль
        if not admin.verify_password(password):
            admin.increment_failed_attempts()
            db.commit()
            return None
        
        # Успешный вход
        admin.record_login()
        db.commit()
        return admin
    
    @staticmethod
    def login_admin(db: Session, login_data: AdminLogin) -> dict:
        """Вход админа в систему"""
        admin = AdminAuthService.authenticate_admin(db, login_data.username, login_data.password)
        
        if not admin:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        
        if not admin.is_active:
            raise HTTPException(status_code=401, detail="Account is deactivated")
        
        # Создаем токен
        access_token = AdminAuthService.create_access_token(
            data={"sub": admin.username, "admin_id": admin.id, "role": admin.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "admin": AdminResponse.from_orm(admin)
        }
    
    @staticmethod
    def create_admin(db: Session, admin_data: AdminCreate) -> Admin:
        """Создание нового админа"""
        # Проверяем, не существует ли уже админ с таким username или email
        existing_admin = db.query(Admin).filter(
            (Admin.username == admin_data.username) | (Admin.email == admin_data.email)
        ).first()
        
        if existing_admin:
            raise HTTPException(status_code=400, detail="Username or email already exists")
        
        # Создаем нового админа
        admin = Admin(
            username=admin_data.username,
            email=admin_data.email,
            full_name=admin_data.full_name,
            role=admin_data.role.value
        )
        admin.set_password(admin_data.password)
        
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        return admin
    
    @staticmethod
    def get_current_admin(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db)
    ) -> Admin:
        """Получение текущего админа по токену"""
        token = credentials.credentials
        payload = AdminAuthService.verify_token(token)
        
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        admin = db.query(Admin).filter(Admin.username == username).first()
        if admin is None:
            raise HTTPException(status_code=401, detail="Admin not found")
        
        if not admin.is_active:
            raise HTTPException(status_code=401, detail="Admin account is deactivated")
        
        return admin
    
    @staticmethod
    def get_current_super_admin(
        current_admin: Admin = Depends(get_current_admin)
    ) -> Admin:
        """Получение текущего супер-админа"""
        if current_admin.role != "super_admin":
            raise HTTPException(status_code=403, detail="Super admin access required")
        return current_admin
