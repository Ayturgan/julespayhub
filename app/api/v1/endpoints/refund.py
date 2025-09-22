"""
API эндпоинты для управления возвратами
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import time

from app.database import get_db
from app.models.merchant import Merchant, MerchantPayment
from app.models.refund import RefundRequest, RefundOperation, RefundStatus, RefundType
from app.schemas.refund import (
    RefundCreate, RefundResponse, RefundListResponse, RefundSummary,
    RefundValidationResult
)
from app.core.merchant_dependencies import get_current_merchant, get_verified_merchant
from app.services.refund_service import RefundService
from app.services.two_phase_refund_service import TwoPhaseRefundService
from app.services.error_handling_service import (
    ErrorHandlingService, StandardError, ErrorCode, ErrorSeverity
)
from app.services.timeline_service import TimelineService
from app.services.realtime_monitoring_service import realtime_monitoring_service
from app.services.hybrid_logging_service import hybrid_logging_service

logger = logging.getLogger(__name__)
router = APIRouter()



# === СОЗДАНИЕ И УПРАВЛЕНИЕ ВОЗВРАТАМИ ===

@router.post("/refunds", response_model=RefundResponse)
async def create_refund(
    refund_data: RefundCreate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Создание нового возврата
    
    Args:
        refund_data: Данные для создания возврата
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Созданный возврат
        """
    
    start_time = time.time()
    
    logger.error(f"🔄 Создание возврата для продавца {current_merchant.id}")
    logger.error(f"💰 Сумма: {refund_data.amount} {refund_data.currency}")
    logger.error(f"📝 Причина: {refund_data.reason}")
    logger.error(f"🏷️ Тип: {refund_data.refund_type}")
    logger.error(f"🆔 ID оригинального платежа: {refund_data.original_payment_id}")
    logger.error(f"📋 Полные данные запроса: {refund_data.dict()}")
    logger.error(f"🔍 Тип refund_type: {type(refund_data.refund_type)}")
    logger.error(f"🔍 Значение refund_type: {refund_data.refund_type}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Создаем возврат
        refund = await refund_service.create_refund(
            db=db,
            merchant_id=current_merchant.id,
            original_payment_id=refund_data.original_payment_id,
            refund_data=refund_data
        )
        

        
        # Логируем успешное создание
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Возврат создан успешно: {refund.refund_token}")
        logger.info(f"⏱️ Время выполнения: {response_time_ms:.2f}ms")
        
        # Записываем в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_request(
                    merchant_id=current_merchant.id,
                    endpoint="/refunds",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=True,
                    refund_amount=refund_data.amount,
                    refund_type=refund_data.refund_type.value
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
        
        return RefundResponse.from_orm(refund)
        
    except HTTPException:
        raise
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ Ошибка создания возврата: {e}")
        logger.error(f"❌ Тип ошибки: {type(e).__name__}")
        logger.error(f"❌ Детали ошибки: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        
        # Если это ошибка валидации Pydantic, логируем детали
        if hasattr(e, 'errors'):
            logger.error(f"❌ Ошибки валидации: {e.errors}")
        
        # Записываем ошибку в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_request(
                    merchant_id=current_merchant.id,
                    endpoint="/refunds",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e),
                    refund_amount=refund_data.amount,
                    refund_type=refund_data.refund_type.value
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "refund_creation_failed",
            f"Failed to create refund: {str(e)}",
            {"merchant_id": current_merchant.id, "amount": refund_data.amount}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.post("/refunds/{refund_id}/execute", response_model=RefundResponse)
async def execute_refund(
    refund_id: int,
    current_merchant: Merchant = Depends(get_verified_merchant),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Выполнение возврата (запуск двухфазного протокола)
    
    Args:
        refund_id: ID возврата
        current_merchant: Верифицированный продавец
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Обновленный возврат
    """
    
    start_time = time.time()
    
    logger.info(f"🚀 Выполнение возврата {refund_id} для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Проверяем, что возврат принадлежит продавцу
        refund = refund_service.get_refund(db, refund_id, current_merchant.id)
        if not refund:
            error = ErrorHandlingService.create_authorization_error(
                "refund_not_found_or_unauthorized",
                "Refund not found or unauthorized",
                {"refund_id": refund_id, "merchant_id": current_merchant.id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Выполняем возврат
        result = await refund_service.execute_refund(db, refund_id, current_merchant.id)
        
        # Проверяем результат выполнения
        logger.error(f"🔍 Результат выполнения возврата: {result}")
        if not result.get("success", False):
            error_msg = result.get("error", "Неизвестная ошибка выполнения возврата")
            logger.error(f"❌ Ошибка выполнения возврата: {error_msg}")
            raise HTTPException(
                status_code=400,
                detail={"error": error_msg}
            )
        
        # Получаем обновленный объект возврата
        updated_refund = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
        if not updated_refund:
            raise HTTPException(
                status_code=404,
                detail={"error": "Возврат не найден после выполнения"}
            )
        
        # Логируем успешное выполнение
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Возврат {refund_id} выполнен успешно")
        logger.info(f"⏱️ Время выполнения: {response_time_ms:.2f}ms")
        
        # Записываем в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_execution(
                    merchant_id=current_merchant.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/execute",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=True,
                    refund_amount=refund.amount,
                    refund_status=updated_refund.status.value if updated_refund.status else "unknown"
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
        
        return RefundResponse.from_orm(updated_refund)
        
    except HTTPException:
        raise
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"❌ Ошибка выполнения возврата {refund_id}: {e}")
        
        # Записываем ошибку в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_execution(
                    merchant_id=current_merchant.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/execute",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e),
                    refund_amount=0,
                    refund_status="unknown"
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "refund_execution_failed",
            f"Failed to execute refund: {str(e)}",
            {"refund_id": refund_id, "merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds", response_model=RefundListResponse)
async def get_refunds(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Количество записей на странице"),
    status: Optional[RefundStatus] = Query(None, description="Фильтр по статусу"),
    refund_type: Optional[RefundType] = Query(None, description="Фильтр по типу возврата"),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Получение списка возвратов продавца с фильтрацией и пагинацией
    
    Args:
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
        page: Номер страницы
        per_page: Количество записей на странице
        status: Фильтр по статусу
        refund_type: Фильтр по типу возврата
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        RefundListResponse: Список возвратов с метаданными
    """
    
    logger.info(f"📋 Получение списка возвратов для продавца {current_merchant.id}")
    logger.info(f"🔍 Фильтры: status={status}, type={refund_type}, date_range={start_date} - {end_date}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем возвраты с фильтрацией
        result = refund_service.get_refunds(
            db=db,
            merchant_id=current_merchant.id,
            page=page,
            per_page=per_page,
            status=status,
            refund_type=refund_type,
            start_date=start_date,
            end_date=end_date,
            original_payment_id=None
        )
        
        logger.info(f"✅ Получено {len(result.refunds)} возвратов из {result.total}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка возвратов: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "refunds_list_failed",
            f"Failed to get refunds list: {str(e)}",
            {"merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds/summary", response_model=RefundSummary)
async def get_refund_summary(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    start_date: Optional[datetime] = Query(None, description="Начальная дата"),
    end_date: Optional[datetime] = Query(None, description="Конечная дата")
):
    """
    Получение сводки по возвратам продавца
    
    Args:
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
        start_date: Начальная дата
        end_date: Конечная дата
    
    Returns:
        RefundSummary: Сводка по возвратам
    """
    
    logger.info(f"📊 Получение сводки возвратов для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем сводку
        summary = refund_service.get_refund_summary(
            db=db,
            merchant_id=current_merchant.id,
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"✅ Сводка получена: {summary.total_refunds} возвратов на {summary.total_amount} {summary.currency}")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения сводки возвратов: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "refund_summary_failed",
            f"Failed to get refund summary: {str(e)}",
            {"merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

@router.get("/refunds/{refund_id}", response_model=RefundResponse)
async def get_refund(
    refund_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """
    Получение детальной информации о возврате
    
    Args:
        refund_id: ID возврата
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
    
    Returns:
        RefundResponse: Детальная информация о возврате
    """
    
    logger.info(f"🔍 Получение возврата {refund_id} для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем возврат
        refund = refund_service.get_refund(db, refund_id, current_merchant.id)
        
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
        
        # Проверяем, что возврат принадлежит продавцу
        if refund.merchant_id != current_merchant.id:
            error = ErrorHandlingService.create_authorization_error(
                "refund_unauthorized",
                "Refund access unauthorized",
                {"refund_id": refund_id, "merchant_id": current_merchant.id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 403),
                detail=error.to_dict()
            )
        
        logger.info(f"✅ Возврат {refund_id} получен успешно")
        
        return RefundResponse.from_orm(refund)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка получения возврата {refund_id}: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "refund_get_failed",
            f"Failed to get refund: {str(e)}",
            {"refund_id": refund_id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )



@router.post("/refunds/{refund_id}/cancel")
async def cancel_refund(
    refund_id: int,
    current_merchant: Merchant = Depends(get_verified_merchant),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Отмена возврата (если он еще не выполнен)
    
    Args:
        refund_id: ID возврата
        current_merchant: Верифицированный продавец
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Отмененный возврат
    """
    
    start_time = time.time()
    
    logger.info(f"❌ Отмена возврата {refund_id} для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Проверяем, что возврат принадлежит продавцу
        refund = refund_service.get_refund(db, refund_id, current_merchant.id)
        if not refund:
            error = ErrorHandlingService.create_authorization_error(
                "refund_not_found_or_unauthorized",
                "Refund not found or unauthorized",
                {"refund_id": refund_id, "merchant_id": current_merchant.id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Отменяем возврат
        cancelled_refund = refund_service.cancel_refund(db, refund_id, current_merchant.id)
        
        # Логируем успешную отмену
        response_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Возврат {refund_id} отменен успешно")
        logger.info(f"⏱️ Время выполнения: {response_time_ms:.2f}ms")
        
        # Записываем в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_cancellation(
                    merchant_id=current_merchant.id,
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
        logger.error(f"❌ Ошибка отмены возврата {refund_id}: {e}")
        
        # Записываем ошибку в мониторинг
        if request:
            try:
                realtime_monitoring_service.record_refund_cancellation(
                    merchant_id=current_merchant.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/cancel",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e),
                    refund_amount=0
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "refund_cancellation_failed",
            f"Failed to cancel refund: {str(e)}",
            {"refund_id": refund_id, "merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

# === ВАЛИДАЦИЯ ВОЗВРАТОВ ===

@router.post("/refunds/validate", response_model=RefundValidationResult)
async def validate_refund(
    refund_data: RefundCreate,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """
    Валидация данных возврата перед созданием
    
    Args:
        refund_data: Данные для валидации
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
    
    Returns:
        RefundValidationResult: Результат валидации
    """
    
    logger.info(f"🔍 Валидация возврата для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем оригинальный платеж для валидации
        original_payment = db.query(MerchantPayment).filter(
            and_(
                MerchantPayment.id == refund_data.original_payment_id,
                MerchantPayment.merchant_id == current_merchant.id
            )
        ).first()
        
        if not original_payment:
            error = ErrorHandlingService.create_business_logic_error(
                "payment_not_found",
                "Оригинальный платеж не найден",
                {"payment_id": refund_data.original_payment_id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Валидируем данные
        validation_result = refund_service._validate_refund_creation(
            refund_data=refund_data,
            original_payment=original_payment
        )
        
        if validation_result.valid:
            logger.info(f"✅ Валидация прошла успешно")
        else:
            logger.warning(f"⚠️ Валидация не прошла: {len(validation_result.errors)} ошибок")
        
        return validation_result
        
    except Exception as e:
        logger.error(f"❌ Ошибка валидации возврата: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "refund_validation_failed",
            f"Failed to validate refund: {str(e)}",
            {"merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

# === ВОЗВРАТЫ ПО КОНКРЕТНОМУ ПЛАТЕЖУ ===

@router.get("/payments/{payment_id}/refunds", response_model=RefundListResponse)
async def get_payment_refunds(
    payment_id: int,
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db)
):
    """
    Получение всех возвратов для конкретного платежа
    
    Args:
        payment_id: ID платежа
        current_merchant: Текущий аутентифицированный продавец
        db: Сессия базы данных
    
    Returns:
        RefundListResponse: Список возвратов для платежа
    """
    
    logger.info(f"📋 Получение возвратов для платежа {payment_id} продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем возвраты для платежа
        refunds = refund_service.get_payment_refunds(
            db=db,
            payment_id=payment_id,
            merchant_id=current_merchant.id
        )
        
        logger.info(f"✅ Получено {len(refunds)} возвратов для платежа {payment_id}")
        
        return RefundListResponse(
            refunds=[RefundResponse.from_orm(refund) for refund in refunds],
            total=len(refunds),
            page=1,
            per_page=len(refunds),
            total_pages=1
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения возвратов для платежа {payment_id}: {e}")
        
        error = ErrorHandlingService.create_business_logic_error(
            "payment_refunds_failed",
            f"Failed to get payment refunds: {str(e)}",
            {"payment_id": payment_id, "merchant_id": current_merchant.id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )

# === ЭКСПОРТ ВОЗВРАТОВ ===

@router.get("/refunds/export")
async def export_refunds(
    current_merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    status: Optional[RefundStatus] = Query(None, description="Фильтр по статусу"),
    refund_type: Optional[RefundType] = Query(None, description="Фильтр по типу возврата"),
    date_from: Optional[str] = Query(None, description="Дата от (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Дата до (YYYY-MM-DD)"),
    min_amount: Optional[float] = Query(None, description="Минимальная сумма"),
    max_amount: Optional[float] = Query(None, description="Максимальная сумма"),
    request: Request = None
):
    """
    Экспорт возвратов в CSV
    """
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Получаем возвраты с фильтрами
        refunds, _ = refund_service.admin_get_refunds(
            db=db,
            page=1,
            per_page=10000,  # Большой лимит для экспорта
            status=status,
            refund_type=refund_type,
            merchant_id=current_merchant.id,
            start_date=datetime.fromisoformat(date_from) if date_from else None,
            end_date=datetime.fromisoformat(date_to) if date_to else None
        )
        
        # Фильтруем по сумме если указано
        if min_amount is not None or max_amount is not None:
            refunds = [
                r for r in refunds 
                if (min_amount is None or r.amount >= min_amount) and 
                   (max_amount is None or r.amount <= max_amount)
            ]
        
        # Создаем CSV
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow([
            'ID возврата', 'ID платежа', 'Сумма', 'Тип', 'Статус', 
            'Причина', 'Дата создания', 'Дата завершения', 'Токен'
        ])
        
        # Данные
        for refund in refunds:
            writer.writerow([
                refund.id,
                refund.payment_id,
                refund.amount,
                refund.refund_type.value,
                refund.status.value,
                refund.reason,
                refund.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                refund.completed_at.strftime('%Y-%m-%d %H:%M:%S') if refund.completed_at else '',
                refund.refund_token or ''
            ])
        
        # Возвращаем CSV файл
        from fastapi.responses import Response
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=refunds_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта возвратов: {e}")
        raise HTTPException(
            status_code=500,
            detail="Ошибка экспорта возвратов"
        )

@router.post("/refunds/{refund_id}/complete", response_model=RefundResponse)
async def complete_refund(
    refund_id: int,
    current_merchant: Merchant = Depends(get_verified_merchant),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Завершение возврата после подтверждения в банках
    
    Args:
        refund_id: ID возврата
        current_merchant: Верифицированный продавец
        db: Сессия базы данных
        request: HTTP запрос для логирования
    
    Returns:
        RefundResponse: Обновленный возврат
    """
    
    start_time = time.time()
    
    logger.info(f"🏁 Завершение возврата {refund_id} для продавца {current_merchant.id}")
    
    try:
        # Создаем сервис возвратов
        refund_service = RefundService()
        
        # Проверяем, что возврат принадлежит продавцу и находится в статусе PROCESSING
        refund = refund_service.get_refund(db, refund_id, current_merchant.id)
        if not refund:
            error = ErrorHandlingService.create_authorization_error(
                "refund_not_found_or_unauthorized",
                "Refund not found or unauthorized",
                {"refund_id": refund_id, "merchant_id": current_merchant.id}
            )
            raise HTTPException(
                status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 404),
                detail=error.to_dict()
            )
        
        # Получаем объект возврата из базы
        refund_obj = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
        if not refund_obj:
            raise HTTPException(
                status_code=404,
                detail={"error": "Возврат не найден"}
            )
        
        # Проверяем статус
        if refund_obj.status != RefundStatus.PROCESSING:
            raise HTTPException(
                status_code=400,
                detail={"error": f"Возврат должен быть в статусе PROCESSING, текущий статус: {refund_obj.status.value}"}
            )
        
        # Получаем оригинальный платеж
        original_payment = db.query(MerchantPayment).filter(
            MerchantPayment.id == refund_obj.original_payment_id
        ).first()
        
        if not original_payment:
            raise HTTPException(
                status_code=404,
                detail={"error": "Оригинальный платеж не найден"}
            )
        
        # Выполняем commit фазу двухфазного возврата
        logger.info(f"🔄 Выполнение commit фазы для возврата {refund_id}")
        result = await two_phase_refund_service._execute_refund_commit_phase(
            db, refund_obj, []  # Пустой список, так как prepare уже выполнен
        )
        
        if result["success"]:
            # Возврат успешно завершен
            refund_obj.status = RefundStatus.COMPLETED
            refund_obj.completed_at = datetime.now()
            db.commit()
            
            # Отправляем уведомление об успешном завершении
            merchant = db.query(Merchant).filter(Merchant.id == current_merchant.id).first()
            if merchant:
                RefundNotificationService.notify_refund_completed(db, refund_obj, merchant)
            
            logger.info(f"✅ Возврат {refund_id} успешно завершен")
            
            # Логируем успешное завершение
            response_time_ms = (time.time() - start_time) * 1000
            logger.info(f"⏱️ Время завершения: {response_time_ms:.2f}ms")
            
            return RefundResponse.from_orm(refund_obj)
        else:
            # Ошибка завершения
            refund_obj.status = RefundStatus.FAILED
            db.commit()
            
            error_msg = result.get("error", "Неизвестная ошибка завершения возврата")
            logger.error(f"❌ Ошибка завершения возврата {refund_id}: {error_msg}")
            
            raise HTTPException(
                status_code=400,
                detail={"error": error_msg}
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка завершения возврата {refund_id}: {e}")
        
        # Логируем ошибку
        response_time_ms = (time.time() - start_time) * 1000
        if request:
            try:
                realtime_monitoring_service.record_refund_execution(
                    merchant_id=current_merchant.id,
                    refund_id=refund_id,
                    endpoint=f"/refunds/{refund_id}/complete",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=str(e)
                )
            except Exception as monitoring_error:
                logger.error(f"Failed to record monitoring error: {monitoring_error}")
        
        # Создаем стандартную ошибку
        error = ErrorHandlingService.create_business_logic_error(
            "refund_completion_failed",
            f"Failed to complete refund: {str(e)}",
            {"merchant_id": current_merchant.id, "refund_id": refund_id}
        )
        
        raise HTTPException(
            status_code=ErrorHandlingService.ERROR_CODE_TO_HTTP_STATUS.get(error.code, 500),
            detail=error.to_dict()
        )
