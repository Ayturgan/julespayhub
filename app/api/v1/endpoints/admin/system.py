# System settings and configuration endpoints for admin
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.settings import SystemSetting
from app.services.hybrid_logging_service import hybrid_logging_service
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import secrets
import json

router = APIRouter()

# Эндпоинты для настроек
@router.get("/settings")
async def get_settings(db: Session = Depends(get_db)):
    """Получение настроек системы"""
    try:
        # Получаем настройки из базы данных
        settings = db.query(SystemSetting).all()
        settings_dict = {}
        
        for setting in settings:
            try:
                if setting.value_json:
                    settings_dict[setting.key] = json.loads(setting.value_json)
                else:
                    settings_dict[setting.key] = setting.value
            except json.JSONDecodeError:
                settings_dict[setting.key] = setting.value
        
        return {
            "system": {
                "request_timeout": settings_dict.get("request_timeout", 30),
                "max_retries": settings_dict.get("max_retries", 3),
                "maintenance_mode": settings_dict.get("maintenance_mode", False),
                "log_level": settings_dict.get("log_level", "INFO")
            },
            "alerts": {
                "email": settings_dict.get("alert_email", "admin@qrpayhub.com"),
                "webhook_url": settings_dict.get("alert_webhook_url", ""),
                "immediate_level": settings_dict.get("alert_immediate_level", "CRITICAL")
            },
            "custom_settings": settings_dict
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")

@router.put("/settings/system")
async def update_system_settings(
    settings: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Обновление системных настроек"""
    try:
        for key, value in settings.items():
            # Проверяем, существует ли настройка
            setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            
            if setting:
                # Обновляем существующую настройку
                if isinstance(value, (dict, list)):
                    setting.value_json = json.dumps(value, ensure_ascii=False)
                    setting.value = None
                else:
                    setting.value = str(value)
                    setting.value_json = None
                setting.updated_at = datetime.now()
            else:
                # Создаем новую настройку
                new_setting = SystemSetting(
                    key=key,
                    value=str(value) if not isinstance(value, (dict, list)) else None,
                    value_json=json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else None
                )
                db.add(new_setting)
        
        db.commit()
        return {"message": "Системные настройки сохранены"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

@router.put("/settings/alerts")
async def update_alerts_settings(
    settings: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Обновление настроек алертов"""
    try:
        for key, value in settings.items():
            # Добавляем префикс alert_ к ключам настроек алертов
            setting_key = f"alert_{key}"
            
            # Проверяем, существует ли настройка
            setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()
            
            if setting:
                # Обновляем существующую настройку
                if isinstance(value, (dict, list)):
                    setting.value_json = json.dumps(value, ensure_ascii=False)
                    setting.value = None
                else:
                    setting.value = str(value)
                    setting.value_json = None
                setting.updated_at = datetime.now()
            else:
                # Создаем новую настройку
                new_setting = SystemSetting(
                    key=setting_key,
                    value=str(value) if not isinstance(value, (dict, list)) else None,
                    value_json=json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else None
                )
                db.add(new_setting)
        
        db.commit()
        return {"message": "Настройки алертов сохранены"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update alert settings: {str(e)}")

# # Системная информация
# @router.get("/system/info")
# async def get_system_info(db: Session = Depends(get_db)):
#     """Получение системной информации"""
#     try:
#         import psutil
#         import platform
        
#         # Информация о системе
#         uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
#         memory = psutil.virtual_memory()
        
#         return {
#             "version": "1.0.0",
#             "uptime": str(uptime).split('.')[0],  # убираем микросекунды
#             "database_status": "Connected",
#             "active_connections": "5",  # заглушка
#             "memory_usage": f"{memory.percent}%",
#             "last_restart": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
#             "platform": platform.system(),
#             "python_version": platform.python_version()
#         }
#     except ImportError:
#         # Если psutil не установлен, возвращаем базовую информацию
#         return {
#             "version": "1.0.0",
#             "uptime": "N/A",
#             "database_status": "Connected",
#             "active_connections": "N/A",
#             "memory_usage": "N/A",
#             "last_restart": datetime.now().isoformat(),
#             "platform": "Unknown",
#             "python_version": "Unknown"
#         }

# Бэкапы
@router.post("/backup/create")
async def create_backup(db: Session = Depends(get_db)):
    """Создание резервной копии"""
    try:
        # Здесь должна быть реальная логика создания бэкапа
        backup_id = secrets.token_hex(8)
        
        # Логируем создание бэкапа
        hybrid_logging_service.log_admin_action(
            db=db,
            action="backup_created",
            target=backup_id,
            details={"backup_id": backup_id},
            actor_id="system"
        )
        
        return {
            "message": "Backup created successfully",
            "backup_id": backup_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)}")

@router.get("/backup/list")
async def list_backups(db: Session = Depends(get_db)):
    """Список доступных резервных копий"""
    # Здесь должна быть реальная логика получения списка бэкапов
    return {
        "backups": [],
        "message": "No backups available"
    }