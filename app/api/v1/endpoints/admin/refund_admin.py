"""
Административные API эндпоинты для управления возвратами
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import time

from app.database import get_db
from app.models.refund import RefundRequest, RefundOperation, RefundStatus, RefundType
from app.models.merchant import Merchant
from app.schemas.refund import (
    RefundResponse, RefundListResponse, RefundSummary,
    RefundValidationResult
)
from app.core.dependencies import get_current_admin_user
from app.services.admin_auth_service import AdminAuthService
from app.services.refund_service import RefundService
from app.services.error_handling_service import (
    ErrorHandlingService, StandardError, ErrorCode, ErrorSeverity
)
from app.services.timeline_service import TimelineService
from app.services.realtime_monitoring_service import realtime_monitoring_service
from app.services.refund_notification_service import RefundNotificationService

logger = logging.getLogger(__name__)
router = APIRouter()

# === АДМИНИСТРАТИВНОЕ УПРАВЛЕНИЕ ВОЗВРАТАМИ ===

@router.get("/refunds", response_model=RefundListResponse)
async def admin_get_refunds(
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Количество записей на странице"),
    status: Optional[RefundStatus] = Query(None, description="Фильтр по статусу"),
    refund_type: Optional[RefundType] = Query(None, description="Фильтр по типу возврата"),
    merchant_id: Optional[int] = Query(None, description="Фильтр по ID продавца"),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Административное получение списка всех возвратов с фильтрацией
    
    Args:
        current_admin: Текущий аутентифицированный администратор
        db: Сессия базы данных
        page: Номер страницы
        per_page: Количество записей на странице
        status: Фильтр по статусу
        refund_type: Фильтр по типу возврата
        merchant_id: Фильтр по ID продавца
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        RefundListResponse: Список возвратов с метаданными
    """
    
    logger.info(f"👨‍💼 Админ {current_admin.id} получает список возвратов")
    logger.info(f"🔍 Фильтры: status={status}, type={refund_type}, merchant_id={merchant_id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем возвраты с фильтрацией (для админа - все возвраты)
        refunds, total = refund_service.admin_get_refunds(
            page=page,
            per_page=per_page,
            status=status,
            refund_type=refund_type,
            merchant_id=merchant_id,
            start_date=start_date,
            end_date=end_date
        )
        
        # Вычисляем метаданные пагинации
        total_pages = (total + per_page - 1) // per_page
        
        logger.info(f"✅ Админ получил {len(refunds)} возвратов из {total}")
        
        return RefundListResponse(
            refunds=[RefundResponse.from_orm(refund) for refund in refunds],
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка возвратов админом: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "admin_refunds_list_failed",
            f"Failed to get refunds list: {str(e)}",
            {"admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds/{refund_id}", response_model=RefundResponse)
async def admin_get_refund(
    refund_id: int,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Административное получение детальной информации о возврате
    
    Args:
        refund_id: ID возврата
        current_admin: Текущий аутентифицированный администратор
        db: Сессия базы данных
    
    Returns:
        RefundResponse: Детальная информация о возврате
    """
    
    logger.info(f"👨‍💼 Админ {current_admin.id} получает возврат {refund_id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем возврат (админ может получить любой возврат)
        refund = refund_service.get_refund(refund_id)
        
        if not refund:
            error = ErrorHandlingService.create_business_logic_error(
                "refund_not_found",
                "Refund not found",
                {"refund_id": refund_id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        logger.info(f"✅ Админ получил возврат {refund_id} успешно")
        
        return RefundResponse.from_orm(refund)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения возврата админом {refund_id}: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "admin_refund_get_failed",
            f"Failed to get refund: {str(e)}",
            {"refund_id": refund_id, "admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds/summary", response_model=RefundSummary)
async def admin_get_refund_summary(
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    merchant_id: Optional[int] = Query(None, description="Фильтр по ID продавца"),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Административное получение сводки по возвратам
    
    Args:
        current_admin: Текущий аутентифицированный администратор
        db: Сессия базы данных
        merchant_id: Фильтр по ID продавца
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        RefundSummary: Сводка по возвратам
    """
    
    logger.info(f"👨‍💼 Админ {current_admin.id} получает сводку возвратов")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем сводку (для админа - общая сводка)
        summary = refund_service.admin_get_refund_summary(
            merchant_id=merchant_id,
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"✅ Админ получил сводку: {summary.total_refunds} возвратов на {summary.total_amount} {summary.currency}")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения сводки возвратов админом: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "admin_refund_summary_failed",
            f"Failed to get refund summary: {str(e)}",
            {"admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.post("/refunds/{refund_id}/force-execute", response_model=RefundResponse)
async def admin_force_execute_refund(
    refund_id: int,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Принудительное выполнение возврата администратором
    
    Args:
        refund_id: ID возврата
        current_admin: Верифицированный администратор
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Обновленный возврат
    """
    
    start_time = time.time()
    
    logger.info(f"👨‍💼 Админ {current_admin.id} принудительно выполняет возврат {refund_id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем возврат
        refund = refund_service.get_refund(refund_id)
        if not refund:
            error = ErrorHandlingService.create_business_logic_error(
                "refund_not_found",
                "Refund not found",
                {"refund_id": refund_id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Принудительно выполняем возврат
        updated_refund = refund_service.admin_force_execute_refund(refund_id, current_admin.id)
        
        # Отправляем уведомление о действии администратора
        try:
            RefundNotificationService.notify_admin_refund_action(
                db=db,
                refund=refund,
                admin_id=current_admin.id,
                action="force_execute",
                description="Принудительное выполнение возврата администратором"
            )
        except Exception as notification_error:
            logger.error(f"Failed to send admin notification: {notification_error}")
        
        # Логируем успешное выполнение
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Админ принудительно выполнил возврат {refund_id}")
        logger.info(f"⏱️ Время выполнения: {response_time_ms:.2f}ms")
        
        # Записываем в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_admin_refund_execution(
                    admin_id=current_admin.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/force-execute",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=True,
                    refund_amount=refund.amount,
                    refund_status=updated_refund.status.value
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
        
        return RefundResponse.from_orm(updated_refund)
        
    except HTTPException:
        raise
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ Ошибка принудительного выполнения возврата {refund_id} админом: {e}")
        
        # Записываем ошибку в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_admin_refund_execution(
                    admin_id=current_admin.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/force-execute",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e)
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "admin_refund_force_execution_failed",
            f"Failed to force execute refund: {str(e)}",
            {"refund_id": refund_id, "admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.post("/refunds/{refund_id}/cancel", response_model=RefundResponse)
async def admin_cancel_refund(
    refund_id: int,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Административная отмена возврата
    
    Args:
        refund_id: ID возврата
        current_admin: Верифицированный администратор
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Отмененный возврат
    """
    
    start_time = time.time()
    
    logger.info(f"👨‍💼 Админ {current_admin.id} отменяет возврат {refund_id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем возврат
        refund = refund_service.get_refund(refund_id)
        if not refund:
            error = ErrorHandlingService.create_business_logic_error(
                "refund_not_found",
                "Refund not found",
                {"refund_id": refund_id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Отменяем возврат
        cancelled_refund = refund_service.admin_cancel_refund(refund_id, current_admin.id)
        
        # Отправляем уведомление о действии администратора
        try:
            RefundNotificationService.notify_admin_refund_action(
                db=db,
                refund=refund,
                admin_id=current_admin.id,
                action="cancel",
                description="Отмена возврата администратором"
            )
        except Exception as notification_error:
            logger.error(f"Failed to send admin notification: {notification_error}")
        
        # Логируем успешную отмену
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Админ отменил возврат {refund_id}")
        logger.info(f"⏱️ Время выполнения: {response_time_ms:.2f}ms")
        
        # Записываем в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_admin_refund_cancellation(
                    admin_id=current_admin.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/cancel",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=True,
                    refund_amount=refund.amount
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
        
        return RefundResponse.from_orm(cancelled_refund)
        
    except HTTPException:
        raise
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ Ошибка отмены возврата {refund_id} админом: {e}")
        
        # Записываем ошибку в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_admin_refund_cancellation(
                    admin_id=current_admin.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/cancel",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e)
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "admin_refund_cancellation_failed",
            f"Failed to cancel refund: {str(e)}",
            {"refund_id": refund_id, "admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

# === АНАЛИТИКА ВОЗВРАТОВ ===

@router.get("/refunds/analytics/merchant/{merchant_id}")
async def admin_get_merchant_refund_analytics(
    merchant_id: int,
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Аналитика возвратов для конкретного продавца
    
    Args:
        merchant_id: ID продавца
        current_admin: Текущий аутентифицированный администратор
        db: Сессия базы данных
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        Dict: Аналитические данные по возвратам продавца
    """
    
    logger.info(f"👨‍💼 Админ {current_admin.id} получает аналитику возвратов продавца {merchant_id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем аналитику
        analytics = refund_service.get_merchant_refund_analytics(
            merchant_id=merchant_id,
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"✅ Админ получил аналитику возвратов продавца {merchant_id}")
        
        return analytics
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения аналитики возвратов продавца {merchant_id}: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "merchant_refund_analytics_failed",
            f"Failed to get merchant refund analytics: {str(e)}",
            {"merchant_id": merchant_id, "admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds/analytics/global")
async def admin_get_global_refund_analytics(
    current_admin = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Глобальная аналитика возвратов по всей системе
    
    Args:
        current_admin: Текущий аутентифицированный администратор
        db: Сессия базы данных
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        Dict: Глобальные аналитические данные по возвратам
    """
    
    logger.info(f"👨‍💼 Админ {current_admin.id} получает глобальную аналитику возвратов")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService(db)
        
        # Получаем глобальную аналитику
        analytics = refund_service.get_global_refund_analytics(
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"✅ Админ получил глобальную аналитику возвратов")
        
        return analytics
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения глобальной аналитики возвратов: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "global_refund_analytics_failed",
            f"Failed to get global refund analytics: {str(e)}",
            {"admin_id": current_admin.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )
    