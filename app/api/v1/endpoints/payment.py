from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
import logging
from app.database import get_db
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.payment import Bank
from app.services.hybrid_logging_service import hybrid_logging_service
from app.schemas.payment import PaymentInfo, PaymentStatusWebhook, PaymentStatusResponse
from app.schemas.bank import TwoPhasePaymentRequest, TwoPhasePaymentResponse
from app.core.dependencies import get_authenticated_bank_no_hmac, get_authenticated_bank, get_bank_for_payment_info, get_bank_for_webhook
from app.services.token_service import SecureTokenService
from app.services.webhook_service import WebhookService
from app.services.qr_security_service import QRSecurityService
from app.services.error_handling_service import (
    ErrorHandlingService, StandardError, ErrorCode, ErrorSeverity
)
from app.services.bank_adapter_service import bank_adapter_service
from typing import Optional
from app.services.timeline_service import TimelineService
from app.services.realtime_monitoring_service import realtime_monitoring_service
from app.services.two_phase_commit_service import two_phase_commit_service
from app.services.idempotency_service import idempotency_service
from app.models.payment import TransactionStatus
import time

# Специальный логгер для платежных операций
logger = logging.getLogger("payment_operations")

router = APIRouter()

@router.get("/payment-info")
async def get_payment_info(
    token: str,
    request: Request,
    bank: Bank = Depends(get_bank_for_payment_info),
    db: Session = Depends(get_db)
) -> PaymentInfo:
    """
    Эндпоинт для банков - получение информации о платеже по токену
    """
    
    start_time = time.time()
    
    logger.info(f"🏦 Запрос информации о платеже от банка {bank.code} ({bank.name})")
    logger.info(f"🔑 Токен: {token[:20]}..., IP: {request.client.host}")
    logger.info(f"📱 User-Agent: {request.headers.get('user-agent', 'N/A')}")
    logger.info(f"📋 Заголовки: {dict(request.headers)}")
    
    # Логируем запрос с информацией о банке (только в файлы)
    hybrid_logging_service.log_api_request(
        request_type="payment_info",
        endpoint="/payment-info",
        method="GET",
        status_code=200,
        duration_ms=0,  # Будет обновлено позже
        ip_address=request.client.host,
        bank_code=bank.code,
        payment_token=token,
        user_agent=request.headers.get("user-agent")
    )
    
    # Извлекаем UUID из защищенного токена
    token_uuid = SecureTokenService.extract_uuid_from_token(token)
    if not token_uuid:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="payment_info",
            endpoint="/payment-info",
            method="GET",
            status_code=400,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=token,
            error_message="Invalid token format",
            user_agent=request.headers.get("user-agent")
        )
        
        # Записываем событие ошибки в мониторинг
        try:
            realtime_monitoring_service.record_payment_request(
                bank_code=bank.code,
                endpoint="/payment-info",
                ip_address=request.client.host,
                response_time_ms=response_time_ms,
                success=False,
                error_message="Invalid token format",
                user_agent=request.headers.get("user-agent")
            )
        except Exception as e:
            logger.error(f"Failed to record monitoring event: {e}")
        
        error = StandardError(
            code=ErrorCode.INVALID_TOKEN,
            message="Invalid token format",
            details={"token_length": len(token)},
            severity=ErrorSeverity.LOW,
            user_message="Неверный формат токена",
            suggestions=["Проверьте правильность токена", "Убедитесь что токен не поврежден"]
        )
        
        # Таймлайн: ошибка формата токена
        try:
            TimelineService.record_event(
                db,
                event_type='info_error',
                title='Ошибка запроса информации: неверный формат токена',
                description='Банк запросил /payment-info с некорректным токеном',
                actor='bank',
                source='api',
                status='failed'
            )
        except Exception:
            pass

        return ErrorHandlingService.create_error_response(error, request)
    
    # Ищем платежный запрос по UUID
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.token == token_uuid
    ).first()
    
    if not payment_request:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="payment_info",
            endpoint="/payment-info",
            method="GET",
            status_code=404,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=token,
            error_message="Payment request not found",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.PAYMENT_NOT_FOUND,
            message="Payment request not found",
            details={"token_uuid": token_uuid},
            severity=ErrorSeverity.MEDIUM,
            user_message="Платежный запрос не найден",
            suggestions=[
                "Проверьте правильность токена",
                "Убедитесь что платежный запрос не истек",
                "Обратитесь к получателю за новым QR-кодом"
            ]
        )
        
        try:
            TimelineService.record_event(
                db,
                payment_token=token_uuid,
                event_type='info_error',
                title='Ошибка запроса информации: платёж не найден',
                description=f'GET /payment-info для token {token_uuid}',
                actor='bank',
                source='api',
                status='failed'
            )
        except Exception:
            pass
        return ErrorHandlingService.create_error_response(error, request)
    
    # Полная валидация защищенного токена
    validation_result = SecureTokenService.validate_token(token, payment_request)
    
    if not validation_result["valid"]:
        response_time_ms = (time.time() - start_time) * 1000
        status_code = 400 if validation_result["expired"] or validation_result["used"] else 401
        
        # Логируем ошибку валидации (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="payment_info",
            endpoint="/payment-info",
            method="GET",
            status_code=status_code,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=token,
            error_message=validation_result.get("error", "Token validation failed"),
            user_agent=request.headers.get("user-agent")
        )
        
        # Определяем тип ошибки для правильного кода
        if validation_result.get("expired"):
            error_code = ErrorCode.EXPIRED_TOKEN
            user_message = "Токен истек"
            suggestions = ["Получите новый QR-код", "Проверьте время создания платежа"]
            # Алерт TOKEN_EXPIRED (INFO)
            try:
                from app.services.bank_alerts_service import bank_alerts_service, AlertType
                from app.services.realtime_monitoring_service import AlertSeverity as _AS
                bank_alerts_service.create_alert(
                    alert_type=AlertType.TOKEN_EXPIRED,
                    severity=_AS.INFO,
                    bank_code=bank.code,
                    title="TOKEN_EXPIRED",
                    message=f"Запрос к /payment-info с истекшим токеном",
                    details={
                        "token": token_uuid,
                        "bank_code": bank.code,
                        "expired_at": payment_request.expires_at.isoformat() if getattr(payment_request, 'expires_at', None) else None
                    }
                )
            except Exception:
                pass
        elif validation_result.get("used"):
            error_code = ErrorCode.PAYMENT_ALREADY_PROCESSED
            user_message = "Платеж уже был обработан"
            suggestions = ["Этот QR-код уже использован", "Получите новый QR-код для нового платежа"]
            # Алерт TOKEN_REUSE_ATTEMPT (INFO)
            try:
                from app.services.bank_alerts_service import bank_alerts_service, AlertType
                from app.services.realtime_monitoring_service import AlertSeverity as _AS
                bank_alerts_service.create_alert(
                    alert_type=AlertType.TOKEN_REUSE_ATTEMPT,
                    severity=_AS.INFO,
                    bank_code=bank.code,
                    title="TOKEN_REUSE_ATTEMPT",
                    message="Попытка повторного использования QR-токена",
                    details={
                        "token": token_uuid,
                        "bank_code": bank.code,
                        "original_transaction_id": payment_request.transaction_id
                    }
                )
            except Exception:
                pass
        else:
            error_code = ErrorCode.INVALID_TOKEN
            user_message = "Неверный токен"
            suggestions = ["Проверьте правильность токена", "Обратитесь к получателю за новым QR-кодом"]
        
        error = StandardError(
            code=error_code,
            message=validation_result.get("error", "Token validation failed"),
            details=validation_result,
            severity=ErrorSeverity.MEDIUM,
            user_message=user_message,
            suggestions=suggestions
        )
        
        try:
            TimelineService.record_event(
                db,
                payment_token=token_uuid,
                event_type='info_error',
                title='Ошибка запроса информации: токен недействителен',
                description=validation_result.get('error', ''),
                actor='bank',
                source='api',
                status='failed',
                metadata=validation_result
            )
        except Exception:
            pass
        return ErrorHandlingService.create_error_response(error, request)
    
    # Дополнительная проверка QR безопасности (если передан полный URL)
    referer = request.headers.get("referer")
    if referer and "token=" in referer:
        try:
            qr_security_check = QRSecurityService.validate_qr_url(referer, strict_mode=False)
            
            # Логируем результаты проверки безопасности
            if not qr_security_check["valid"]:
                import logging
                qr_logger = logging.getLogger(__name__)
                qr_logger.warning(
                    f"QR security validation failed for bank {bank.code} from {request.client.host}: "
                    f"{'; '.join(qr_security_check['errors'])}"
                )
            
            # Сохраняем результат для логирования
            request.state.qr_security_result = qr_security_check
        except Exception as e:
            # Не блокируем запрос при ошибке проверки QR
            import logging
            qr_logger = logging.getLogger(__name__)
            qr_logger.error(f"QR security check error: {e}")
    
    # Логируем успешный запрос (только в файлы)
    response_time_ms = (time.time() - start_time) * 1000
    hybrid_logging_service.log_api_request(
        request_type="payment_info",
        endpoint="/payment-info",
        method="GET",
        status_code=200,
        duration_ms=int(response_time_ms),
        ip_address=request.client.host,
        bank_code=bank.code,
        payment_token=token,
        user_agent=request.headers.get("user-agent")
    )
    
    # Записываем событие в мониторинг
    try:
        realtime_monitoring_service.record_payment_request(
            bank_code=bank.code,
            endpoint="/payment-info",
            ip_address=request.client.host,
            response_time_ms=response_time_ms,
            success=True,
            amount=payment_request.amount,
            currency=payment_request.currency,
            user_agent=request.headers.get("user-agent")
        )
    except Exception as e:
        logger.error(f"Failed to record monitoring event: {e}")
    
    # Событие таймлайна: банк запросил информацию
    try:
        TimelineService.record_event(
            db,
            payment_token=token_uuid,
            event_type='info_requested',
            title='Банк запросил информацию о платеже',
            description=f"GET /payment-info, банк {bank.code}",
            actor='bank',
            source='api',
            status='info'
        )
    except Exception:
        pass
    
    # Форматируем ответ с использованием адаптера банка
    try:
        formatted_payment_info = bank_adapter_service.format_payment_info_for_bank(
            bank.code, payment_request
        )
        
        # Преобразуем в стандартный формат PaymentInfo, но с возможными изменениями формата
        return PaymentInfo(
            receiver_account=formatted_payment_info.get("receiver_account", payment_request.receiver_account),
            receiver_bank_code=formatted_payment_info.get("receiver_bank_code", payment_request.receiver_bank_code), 
            receiver_name=formatted_payment_info.get("receiver_name", payment_request.receiver_name),
            description=formatted_payment_info.get("description", payment_request.description),
            amount=formatted_payment_info.get("amount", payment_request.amount),
            currency=formatted_payment_info.get("currency", payment_request.currency),
            payment_reference=formatted_payment_info.get("payment_reference", payment_request.payment_reference),
            sender_bank_code=payment_request.sender_bank_code,
            sender_account=payment_request.sender_account
        )
        
    except Exception as e:
        # Если адаптер не работает, возвращаем стандартный формат
        import logging
        adapter_logger = logging.getLogger(__name__)
        adapter_logger.error(f"Bank adapter error for {bank.code}: {e}")
        
        return PaymentInfo(
            receiver_account=payment_request.receiver_account,
            receiver_bank_code=payment_request.receiver_bank_code,
            receiver_name=payment_request.receiver_name,
            description=payment_request.description,
            amount=payment_request.amount,
            currency=payment_request.currency,
            payment_reference=payment_request.payment_reference,
            sender_bank_code=payment_request.sender_bank_code,
            sender_account=payment_request.sender_account
        )

@router.post("/payment-status")
async def payment_status_webhook(
    webhook_data: PaymentStatusWebhook,
    request: Request,
    bank: Bank = Depends(get_bank_for_webhook),  # С rate limiting и HMAC
    db: Session = Depends(get_db)
) -> PaymentStatusResponse:
    """
    Webhook для получения уведомлений от банков о статусе платежа
    """
    
    start_time = time.time()
    
    # Логируем webhook с информацией о банке (только в файлы)
    hybrid_logging_service.log_api_request(
        request_type="webhook",
        endpoint="/payment-status",
        method="POST",
        status_code=200,
        duration_ms=0,  # Будет обновлено позже
        ip_address=request.client.host,
        bank_code=bank.code,
        payment_token=webhook_data.token,
        user_agent=request.headers.get("user-agent")
    )
    
    # Сразу фиксируем получение webhook в таймлайне (до обработки)
    try:
        TimelineService.record_event(
            db,
            payment_token=SecureTokenService.extract_uuid_from_token(webhook_data.token),
            event_type='webhook_received',
            title='Получен webhook со статусом оплаты',
            description=f"Банк {bank.code}",
            actor='bank',
            source='webhook',
            status='info',
            metadata={
                "payload_present": True
            }
        )
    except Exception:
        pass

    # Используем WebhookService для идемпотентной обработки через адаптер
    try:
        # Преобразуем webhook_data в dict для адаптера
        webhook_dict = webhook_data.dict()
        
        # Обрабатываем через адаптер банка
        processed_webhook = bank_adapter_service.process_webhook_for_bank(
            bank.code, webhook_dict
        )
        
        # Обрабатываем webhook с идемпотентностью
        result = WebhookService.process_payment_webhook(
            db=db,
            webhook_data=processed_webhook,
            bank_code=bank.code,
            token=processed_webhook.token
        )
        
    except Exception as e:
        # Если адаптер не работает, используем стандартную обработку
        import logging
        adapter_logger = logging.getLogger(__name__)
        adapter_logger.warning(f"Bank adapter webhook processing failed for {bank.code}: {e}")
        
        result = WebhookService.process_payment_webhook(
            db=db,
            webhook_data=webhook_data,
            bank_code=bank.code,
            token=webhook_data.token
        )
    
    # Обновляем логирование webhook
    response_time_ms = (time.time() - start_time) * 1000
    
    # Логируем результат webhook (только в файлы)
    hybrid_logging_service.log_api_request(
        request_type="webhook",
        endpoint="/payment-status",
        method="POST",
        status_code=result["status_code"],
        duration_ms=int(response_time_ms),
        ip_address=request.client.host,
        bank_code=bank.code,
        payment_token=webhook_data.token,
        error_message=result["message"] if result["status_code"] != 200 else None,
        user_agent=request.headers.get("user-agent")
    )
    
    # Записываем событие webhook в мониторинг
    try:
        realtime_monitoring_service.record_webhook_event(
            bank_code=bank.code,
            success=result["status_code"] == 200,
            error_message=result["message"] if result["status_code"] != 200 else None,
            response_time_ms=response_time_ms,
            transaction_id=webhook_data.transaction_id
        )
    except Exception as e:
        logger.error(f"Failed to record webhook monitoring event: {e}")

    # (Убираем постфактум-событие, чтобы порядок был: webhook_received -> transaction_recorded -> billing_recorded)
    
    if result["status_code"] != 200:
        raise HTTPException(
            status_code=result["status_code"],
            detail=result["message"]
        )
    
    # Добавляем информацию об идемпотентности в ответ
    response_message = result["message"]
    if result.get("idempotent"):
        response_message += f" (original: {result.get('original_processed_at')})"
    
    return PaymentStatusResponse(
        success=result["success"],
        message=response_message
    )

@router.post("/two-phase-payment", response_model=TwoPhasePaymentResponse)
async def initiate_two_phase_payment(
    payment_data: TwoPhasePaymentRequest,
    request: Request,
    bank: Bank = Depends(get_bank_for_webhook),  # С rate limiting и HMAC
    db: Session = Depends(get_db)
) -> TwoPhasePaymentResponse:
    """
    Новый эндпоинт для инициации двухфазной транзакции
    
    Банк отправляет уведомление о намерении совершить платеж,
    система запускает двухфазную транзакцию
    """
    
    start_time = time.time()
    
    logger.info(f"🔄 Запрос на двухфазную транзакцию от банка {bank.code}")
    logger.info(f"🔑 Токен: {payment_data.token[:20]}..., Сумма: {payment_data.amount}")
    logger.info(f"🔑 Ключ идемпотентности: {payment_data.idempotency_key[:20]}...")
    
    # Проверяем идемпотентность
    if not idempotency_service.validate_idempotency_key(payment_data.idempotency_key):
        error = StandardError(
            code=ErrorCode.INVALID_REQUEST,
            message="Invalid idempotency key format",
            details={"idempotency_key": payment_data.idempotency_key},
            severity=ErrorSeverity.MEDIUM,
            user_message="Неверный формат ключа идемпотентности",
            suggestions=["Используйте только буквы, цифры, дефисы и подчеркивания"]
        )
        raise HTTPException(
            status_code=400,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Проверяем существующий ключ идемпотентности
    existing_result = idempotency_service.check_idempotency_key(
        db, payment_data.idempotency_key, payment_data.token, bank.code
    )
    
    if existing_result:
        logger.info(f"🔄 Возвращаем результат из кэша идемпотентности")
        return TwoPhasePaymentResponse(
            success=existing_result["success"],
            transaction_id=existing_result["response_data"].get("transaction_id", ""),
            status=existing_result["response_data"].get("status", "unknown"),
            message=existing_result["response_data"].get("message", "Cached response"),
            amount=existing_result["response_data"].get("amount"),
            currency=existing_result["response_data"].get("currency"),
            requires_manual_intervention=existing_result["response_data"].get("requires_manual_intervention", False)
        )
    
    # Создаем ключ идемпотентности
    idempotency_record = idempotency_service.create_idempotency_key(
        db=db,
        idempotency_key=payment_data.idempotency_key,
        payment_token=payment_data.token,
        bank_code=bank.code,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    # Логируем запрос (только в файлы)
    hybrid_logging_service.log_api_request(
        request_type="two_phase_payment",
        endpoint="/two-phase-payment",
        method="POST",
        status_code=200,
        duration_ms=0,  # Будет обновлено позже
        ip_address=request.client.host,
        bank_code=bank.code,
        payment_token=payment_data.token,
        user_agent=request.headers.get("user-agent")
    )
    
    # Извлекаем UUID из токена
    token_uuid = SecureTokenService.extract_uuid_from_token(payment_data.token)
    if not token_uuid:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=400,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message="Invalid token format",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.INVALID_TOKEN,
            message="Invalid token format",
            details={"token_length": len(payment_data.token)},
            severity=ErrorSeverity.LOW,
            user_message="Неверный формат токена",
            suggestions=["Проверьте правильность токена"]
        )
        
        raise HTTPException(
            status_code=400,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Ищем платежный запрос
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.token == token_uuid
    ).first()
    
    if not payment_request:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=404,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message="Payment request not found",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.PAYMENT_NOT_FOUND,
            message="Payment request not found",
            details={"token_uuid": token_uuid},
            severity=ErrorSeverity.MEDIUM,
            user_message="Платежный запрос не найден",
            suggestions=["Проверьте правильность токена", "Убедитесь что платежный запрос не истек"]
        )
        
        raise HTTPException(
            status_code=404,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Проверяем текущий статус платежа
    if payment_request.status != TransactionStatus.PENDING:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=409,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message=f"Payment already in status: {payment_request.status.value}",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.PAYMENT_ALREADY_PROCESSED,
            message=f"Payment already in status: {payment_request.status.value}",
            details={"current_status": payment_request.status.value},
            severity=ErrorSeverity.MEDIUM,
            user_message="Платеж уже обрабатывается или завершен",
            suggestions=["Проверьте статус платежа"]
        )
        
        raise HTTPException(
            status_code=409,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Проверяем сумму платежа
    if payment_request.amount != payment_data.amount:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=400,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message=f"Amount mismatch: expected {payment_request.amount}, got {payment_data.amount}",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.INVALID_REQUEST,
            message="Amount mismatch",
            details={
                "expected_amount": payment_request.amount,
                "provided_amount": payment_data.amount,
                "currency": payment_request.currency
            },
            severity=ErrorSeverity.MEDIUM,
            user_message="Сумма платежа не совпадает",
            suggestions=["Проверьте правильность суммы платежа"]
        )
        
        raise HTTPException(
            status_code=400,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Проверяем валюту
    if payment_request.currency != payment_data.currency:
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=400,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message=f"Currency mismatch: expected {payment_request.currency}, got {payment_data.currency}",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.INVALID_REQUEST,
            message="Currency mismatch",
            details={
                "expected_currency": payment_request.currency,
                "provided_currency": payment_data.currency
            },
            severity=ErrorSeverity.MEDIUM,
            user_message="Валюта платежа не совпадает",
            suggestions=["Проверьте правильность валюты платежа"]
        )
        
        raise HTTPException(
            status_code=400,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    
    # Определяем роль банка в транзакции
    if payment_request.receiver_bank_code == bank.code:
        # Банк получателя не может инициировать платеж
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=400,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message="Receiver bank cannot initiate payment",
            user_agent=request.headers.get("user-agent")
        )
        
        error = StandardError(
            code=ErrorCode.INVALID_REQUEST,
            message="Receiver bank cannot initiate payment",
            details={"bank_code": bank.code, "role": "receiver"},
            severity=ErrorSeverity.MEDIUM,
            user_message="Банк получателя не может инициировать платеж",
            suggestions=["Платеж должен инициировать банк отправителя"]
        )
        
        raise HTTPException(
            status_code=400,
            detail=ErrorHandlingService.create_error_response(error, request)
        )
    else:
        # Банк отправителя инициирует платеж
        sender_bank_code = bank.code
        sender_account = payment_data.sender_account
        payer_phone = payment_data.payer_phone
    
    # Записываем событие в таймлайн
    TimelineService.record_event(
        db,
        payment_token=token_uuid,
        event_type='two_phase_requested',
        title='Запрос на двухфазную транзакцию',
        description=f'Банк {sender_bank_code} инициировал двухфазную транзакцию',
        actor='bank',
        source='two_phase_api',
        status='info',
        metadata={
            "amount": payment_data.amount,
            "payer_phone": payer_phone,
            "sender_bank": sender_bank_code,
            "idempotency_key": payment_data.idempotency_key[:20] + "..."
        }
    )
    
    try:
        # Запускаем двухфазную транзакцию
        logger.info(f"🚀 Запуск двухфазной транзакции для платежа {token_uuid}")
        
        result = await two_phase_commit_service.execute_transaction(
            db=db,
            payment_request=payment_request,
            sender_bank_code=sender_bank_code,
            payer_phone=payer_phone,
            sender_account=sender_account
        )
        
        # Обновляем лог
        response_time_ms = (time.time() - start_time) * 1000
        
        # Подготавливаем ответ
        if result["success"]:
            success_message = f"Two-phase transaction completed successfully. Transaction ID: {result['transaction_id']}"
            
            # Логируем успешную транзакцию (в БД и файлы)
            hybrid_logging_service.log_payment_success(
                db=db,
                payment_token=payment_data.token,
                transaction_id=result["transaction_id"],
                amount=result.get("amount"),
                currency=payment_request.currency,
                bank_code=sender_bank_code,
                payer_phone=payer_phone,
                receiver_account=payment_request.receiver_account,
                receiver_bank_code=payment_request.receiver_bank_code,
                receiver_name=payment_request.receiver_name,
                description=payment_request.description,
                reference=payment_request.payment_reference,
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
            
            response_data = {
                "success": True,
                "transaction_id": result["transaction_id"],
                "status": result["status"],
                "message": success_message,
                "amount": result.get("amount"),
                "currency": payment_request.currency,
                "requires_manual_intervention": False
            }
            
            # Записываем успех в мониторинг
            try:
                realtime_monitoring_service.record_payment_request(
                    bank_code=sender_bank_code,
                    endpoint="/two-phase-payment",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=True,
                    amount=result.get("amount"),
                    currency=payment_request.currency,
                    user_agent=request.headers.get("user-agent")
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
            
            # Обновляем результат идемпотентности
            idempotency_service.update_idempotency_result(
                db, payment_data.idempotency_key, response_data, 200, True
            )
            
            return TwoPhasePaymentResponse(**response_data)
        else:
            # Обрабатываем неуспешные результаты
            if result.get("requires_manual_intervention"):
                error_message = f"Critical error in two-phase transaction: {result['error']}"
                
                # Логируем критическую ошибку (только в файлы)
                hybrid_logging_service.log_api_request(
                    request_type="two_phase_payment",
                    endpoint="/two-phase-payment",
                    method="POST",
                    status_code=500,
                    duration_ms=int(response_time_ms),
                    ip_address=request.client.host,
                    bank_code=bank.code,
                    payment_token=payment_data.token,
                    error_message=f"Critical error: {result['error']}",
                    user_agent=request.headers.get("user-agent")
                )
                
                # Алерт о критической ошибке
                try:
                    from app.services.bank_alerts_service import bank_alerts_service, AlertType
                    from app.services.realtime_monitoring_service import AlertSeverity as _AS
                    bank_alerts_service.create_alert(
                        alert_type=AlertType.TRANSACTION_FAILED,
                        severity=_AS.CRITICAL,
                        bank_code=sender_bank_code,
                        title="TWO_PHASE_COMMIT_CRITICAL_ERROR",
                        message="Критическая ошибка двухфазной транзакции",
                        details={
                            "transaction_id": result.get("transaction_id"),
                            "error": result["error"],
                            "requires_manual_intervention": True
                        }
                    )
                except Exception:
                    pass
            else:
                error_message = f"Two-phase transaction failed: {result['error']}"
                
                # Логируем ошибку транзакции (только в файлы)
                hybrid_logging_service.log_api_request(
                    request_type="two_phase_payment",
                    endpoint="/two-phase-payment",
                    method="POST",
                    status_code=400,
                    duration_ms=int(response_time_ms),
                    ip_address=request.client.host,
                    bank_code=bank.code,
                    payment_token=payment_data.token,
                    error_message=f"Transaction failed: {result['error']}",
                    user_agent=request.headers.get("user-agent")
                )
            
            # Записываем ошибку в мониторинг
            try:
                realtime_monitoring_service.record_payment_request(
                    bank_code=sender_bank_code,
                    endpoint="/two-phase-payment",
                    ip_address=request.client.host,
                    response_time_ms=response_time_ms,
                    success=False,
                    error_message=result["error"],
                    user_agent=request.headers.get("user-agent")
                )
            except Exception as e:
                logger.error(f"Failed to record monitoring event: {e}")
            
            # Подготавливаем ответ об ошибке
            error_response_data = {
                "success": False,
                "transaction_id": result.get("transaction_id", ""),
                "status": result.get("status", "failed"),
                "message": error_message,
                "requires_manual_intervention": result.get("requires_manual_intervention", False)
            }
            
            # Обновляем результат идемпотентности
            status_code = 500 if result.get("requires_manual_intervention") else 400
            idempotency_service.update_idempotency_result(
                db, payment_data.idempotency_key, error_response_data, 
                status_code, False
            )
            
            return TwoPhasePaymentResponse(**error_response_data)
            
    except Exception as e:
        # Критическая ошибка
        logger.error(f"💥 Критическая ошибка при обработке двухфазной транзакции: {e}")
        
        response_time_ms = (time.time() - start_time) * 1000
        
        # Логируем критическую ошибку (только в файлы)
        hybrid_logging_service.log_api_request(
            request_type="two_phase_payment",
            endpoint="/two-phase-payment",
            method="POST",
            status_code=500,
            duration_ms=int(response_time_ms),
            ip_address=request.client.host,
            bank_code=bank.code,
            payment_token=payment_data.token,
            error_message=str(e),
            user_agent=request.headers.get("user-agent")
        )
        
        TimelineService.record_event(
            db,
            payment_token=token_uuid,
            event_type='two_phase_error',
            title='Критическая ошибка двухфазной транзакции',
            description=f'Исключение: {str(e)}',
            actor='system',
            source='two_phase_api',
            status='error'
        )
        
        # Подготавливаем ответ об ошибке
        error_response_data = {
            "success": False,
            "transaction_id": "",
            "status": "error",
            "message": f"Internal server error: {str(e)}",
            "requires_manual_intervention": True
        }
        
        # Обновляем результат идемпотентности
        try:
            idempotency_service.update_idempotency_result(
                db, payment_data.idempotency_key, error_response_data, 500, False
            )
        except Exception as idemp_error:
            logger.error(f"Failed to update idempotency result: {idemp_error}")
        
        error = StandardError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Internal server error during two-phase transaction",
            details={"error": str(e)},
            severity=ErrorSeverity.CRITICAL,
            user_message="Внутренняя ошибка сервера",
            suggestions=["Попробуйте позже", "Обратитесь в техподдержку"]
        )
        
        raise HTTPException(
            status_code=500,
            detail=ErrorHandlingService.create_error_response(error, request)
        )

@router.get("/{payment_token}/logs")
async def get_payment_logs(
    payment_token: str,
    db: Session = Depends(get_db)
):
    """
    Получение логов двухфазной транзакции для симулятора
    
    Этот эндпоинт используется симулятором банков для 
    отображения процесса транзакции в реальном времени
    """
    
    from app.services.token_service import SecureTokenService
    from app.models.payment import TwoPhaseOperation
    
    # Извлекаем UUID из токена
    token_uuid = SecureTokenService.extract_uuid_from_token(payment_token)
    if not token_uuid:
        token_uuid = payment_token  # Если это уже UUID
    
    # Получаем все операции для данного платежа
    operations = db.query(TwoPhaseOperation).filter(
        TwoPhaseOperation.payment_token == token_uuid
    ).order_by(TwoPhaseOperation.started_at.asc()).all()
    
    # Получаем информацию о платеже
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.token == token_uuid
    ).first()
    
    if not payment_request:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Формируем логи для фронтенда
    logs = []
    
    # Добавляем статус самого платежа
    logs.append({
        "timestamp": payment_request.created_at.isoformat() if payment_request.created_at else None,
        "level": "info",
        "message": f"Платежный запрос создан: {payment_request.payment_reference}",
        "details": {
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "status": payment_request.status.value if payment_request.status else "unknown"
        }
    })
    
    # Добавляем логи операций
    for op in operations:
        level = "success" if op.response_status in ["prepared", "committed", "aborted"] else "error"
        if op.error_message:
            level = "error"
        
        message = f"{op.phase.upper()} {op.operation_type} -> {op.bank_code} ({op.bank_role})"
        if op.response_status:
            message += f" = {op.response_status}"
        
        logs.append({
            "timestamp": op.started_at.isoformat() if op.started_at else None,
            "level": level,
            "message": message,
            "details": {
                "phase": op.phase,
                "operation_type": op.operation_type,
                "bank_code": op.bank_code,
                "bank_role": op.bank_role,
                "response_status": op.response_status,
                "duration_ms": op.duration_ms,
                "error_message": op.error_message
            }
        })
    
    return {
        "payment_reference": payment_request.payment_reference,
        "current_status": payment_request.status.value if payment_request.status else "unknown",
        "transaction_id": payment_request.transaction_id,
        "logs": logs,
        "total_logs": len(logs),
        "last_updated": datetime.now().isoformat()
    }


