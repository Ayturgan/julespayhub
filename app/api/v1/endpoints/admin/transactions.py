# Transaction management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.unified import UnifiedPayment
from app.models.payment import TransactionRecord, PaymentLog, Bank
from app.models.merchant import QRCode
from app.services.webhook_service import WebhookService
from app.services.hybrid_logging_service import hybrid_logging_service

from sqlalchemy import and_, desc
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import json

router = APIRouter(prefix="/transactions")

@router.get("/")
async def get_transaction_history(
    transaction_id: Optional[str] = None,
    payment_token: Optional[str] = None,
    bank_code: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    История транзакций для мониторинга (используем UnifiedPayment)
    """
    query = db.query(UnifiedPayment)
    
    # Показываем все платежи (убрали ограничение на SIM_платежи)
    
    if transaction_id:
        query = query.filter(UnifiedPayment.transaction_id.contains(transaction_id))
    if payment_token:
        query = query.filter(UnifiedPayment.qr_code.has(qr_token=payment_token))
    if bank_code:
        query = query.filter(UnifiedPayment.receiver_bank_code == bank_code)
    
    payments = query.order_by(UnifiedPayment.created_at.desc()).limit(limit).all()
    
    # Получаем названия банков для всех транзакций
    transactions_data = []
    for p in payments:
        # Получаем названия банков
        sender_bank_name = "N/A"
        receiver_bank_name = "N/A"
        
        if p.payer_bank_code or p.sender_bank_code:
            bank_code = p.payer_bank_code or p.sender_bank_code
            sender_bank = db.query(Bank).filter(Bank.code == bank_code).first()
            if sender_bank:
                sender_bank_name = sender_bank.name
        
        if p.receiver_bank_code:
            receiver_bank = db.query(Bank).filter(Bank.code == p.receiver_bank_code).first()
            if receiver_bank:
                receiver_bank_name = receiver_bank.name
        
        transactions_data.append({
            "id": p.id,
            "transaction_id": p.transaction_id,
            "payment_token": p.qr_code.qr_token if p.qr_code else None,
            "amount": p.amount,
            "currency": p.currency,
            "sender_bank_code": p.payer_bank_code or p.sender_bank_code,
            "sender_bank_name": sender_bank_name,
            "receiver_bank_code": p.receiver_bank_code,
            "receiver_bank_name": receiver_bank_name,
            "status": p.status.value if p.status else "pending",
            "is_paid": p.is_paid,
            "description": p.description,
            "merchant_id": p.merchant_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None
        })
    
    return {
        "transactions": transactions_data
    }

@router.get("/recent")
async def get_recent_transactions(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Получение последних транзакций для дашборда
    """
    payments = db.query(UnifiedPayment).order_by(
        UnifiedPayment.created_at.desc()
    ).limit(limit).all()
    
    # Получаем названия банков для всех транзакций
    transactions_data = []
    for p in payments:
        # Получаем названия банков
        sender_bank_name = "N/A"
        receiver_bank_name = "N/A"
        
        if p.payer_bank_code or p.sender_bank_code:
            bank_code = p.payer_bank_code or p.sender_bank_code
            sender_bank = db.query(Bank).filter(Bank.code == bank_code).first()
            if sender_bank:
                sender_bank_name = sender_bank.name
        
        if p.receiver_bank_code:
            receiver_bank = db.query(Bank).filter(Bank.code == p.receiver_bank_code).first()
            if receiver_bank:
                receiver_bank_name = receiver_bank.name
        
        transactions_data.append({
            "id": p.id,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status.value if p.status else "pending",
            "sender_bank_code": p.payer_bank_code or p.sender_bank_code,
            "sender_bank_name": sender_bank_name,
            "receiver_bank_code": p.receiver_bank_code,
            "receiver_bank_name": receiver_bank_name,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "is_paid": p.is_paid
        })
    
    return transactions_data

@router.get("/{transaction_id}/timeline")
async def get_transaction_timeline(
    transaction_id: str,
    db: Session = Depends(get_db)
):
    """
    Детальный таймлайн транзакции с техническими деталями
    """
    from app.models.payment import PaymentLog
    from app.models.merchant import QRCode
    from app.models.timeline import TimelineEvent
    from sqlalchemy import and_
    import json
    
    print(f"🔍 Поиск транзакции: {transaction_id}")
    print(f"🔍 ТЕСТ - Эндпоинт работает!")

    # Ищем платежный запрос по ID, payment_reference или token (только SIM_платежи)
    print(f"🔍 Поиск по ID: {transaction_id}")
    payment_request = db.query(UnifiedPayment).filter(
        UnifiedPayment.transaction_id.like('SIM_%')  # Показываем только SIM_платежи
    ).filter(UnifiedPayment.id == transaction_id).first()
    if payment_request:
        print(f"✅ Найдена по ID: {payment_request.id}")
    
    if not payment_request:
        print(f"🔍 Поиск по payment_reference: {transaction_id}")
        payment_request = db.query(UnifiedPayment).filter(
            UnifiedPayment.transaction_id.like('SIM_%')  # Показываем только SIM_платежи
        ).filter(UnifiedPayment.payment_reference == transaction_id).first()
        if payment_request:
            print(f"✅ Найдена по payment_reference: {payment_request.id}")
    
    if not payment_request:
        print(f"🔍 Поиск по token: {transaction_id}")
        payment_request = db.query(UnifiedPayment).filter(
            UnifiedPayment.transaction_id.like('SIM_%')  # Показываем только SIM_платежи
        ).filter(UnifiedPayment.qr_code.has(qr_token=transaction_id)).first()
        if payment_request:
            print(f"✅ Найдена по token: {payment_request.id}")
    
    if not payment_request:
        # Попробуем найти по числовому ID
        try:
            print(f"🔍 Попытка конвертации в число: {transaction_id}")
            payment_request = db.query(UnifiedPayment).filter(
                UnifiedPayment.transaction_id.like('SIM_%')  # Показываем только SIM_платежи
            ).filter(UnifiedPayment.id == int(transaction_id)).first()
            if payment_request:
                print(f"✅ Найдена по числовому ID: {payment_request.id}")
        except (ValueError, TypeError) as e:
            print(f"❌ Ошибка конвертации в число: {e}")
    
    if not payment_request:
        # Попробуем извлечь ID из формата PAY20240101075
        try:
            if transaction_id.startswith('PAY'):
                print(f"🔍 Извлечение ID из формата PAY: {transaction_id}")
                # Извлекаем ID из формата PAY20240101075
                # Формат: PAY + год(4) + месяц(2) + день(2) + ID(3)
                id_part = transaction_id[11:]  # Берем последние 3 символа
                # Убираем ведущие нули
                payment_id = int(id_part.lstrip('0') or '0')
                print(f"🔍 Извлечен ID из {transaction_id}: {payment_id}")
                payment_request = db.query(UnifiedPayment).filter(
                    UnifiedPayment.transaction_id.like('SIM_%')  # Показываем только SIM_платежи
                ).filter(UnifiedPayment.id == payment_id).first()
                if payment_request:
                    print(f"✅ Найдена транзакция по извлеченному ID: {payment_request.id}")
        except (ValueError, TypeError, IndexError) as e:
            print(f"❌ Ошибка извлечения ID: {e}")
            pass
    
    if not payment_request:
        print(f"❌ Транзакция не найдена: {transaction_id}")
        raise HTTPException(status_code=404, detail="Transaction not found")

    print(f"✅ Транзакция найдена: ID={payment_request.id}, Token={payment_request.transaction_id}")
    token_uuid = payment_request.qr_code.qr_token if payment_request.qr_code else None
    qrcode = db.query(QRCode).filter(QRCode.qr_token == token_uuid).first()

    # Чтение событий из единой таблицы
    try:
        # Формируем правильный transaction_id для поиска
        expected_transaction_id = f"PAY{2024:04d}{1:02d}{1:02d}{payment_request.id:03d}"
        
        print(f"🔍 Поиск событий:")
        print(f"  transaction_id: {transaction_id}")
        print(f"  expected_transaction_id: {expected_transaction_id}")
        print(f"  token_uuid: {token_uuid}")
        
        events = db.query(TimelineEvent).filter(
            (TimelineEvent.transaction_id == transaction_id) | 
            (TimelineEvent.transaction_id == expected_transaction_id) |
            (TimelineEvent.payment_token == token_uuid)
        ).order_by(TimelineEvent.timestamp_utc.asc(), TimelineEvent.id.asc()).all()
        
        print(f"✅ Найдено событий: {len(events)}")
        for i, event in enumerate(events):
            print(f"  {i+1}. ID: {event.id}, Type: {event.event_type}, Title: {event.title}")
            
    except Exception as e:
        print(f"❌ Ошибка при поиске событий: {e}")
        # Если TimelineEvent не существует, создаем пустой список
        events = []

    # Создаем базовый таймлайн из событий
    timeline = []
    print(f"📝 Формирование таймлайна из {len(events)} событий:")
    for e in events:
        try:
            timeline_entry = {
                "timestamp": e.timestamp_utc,
                "title": e.title,
                "description": e.description,
                "event_type": getattr(e, 'event_type', 'unknown'),
                "status": getattr(e, 'status', 'info')
            }
            timeline.append(timeline_entry)
            print(f"  ✅ Добавлено: {e.title}")
        except Exception as e:
            print(f"  ❌ Ошибка добавления события: {e}")
            continue
    
    print(f"📊 Итого в таймлайне: {len(timeline)} событий")

    # Убираем дублирующее событие "Создание платежного запроса", так как оно уже записывается в симуляции
    # if payment_request.created_at:
    #     timeline.append({
    #         "timestamp": payment_request.created_at,
    #         "title": "Создание платежного запроса",
    #         "description": f"Создан платеж на сумму {payment_request.amount} {payment_request.currency}",
    #         "event_type": "payment_created",
    #         "status": "success"
    #     })

    # Убираем дублирование события "Платеж завершен", так как оно уже записывается в симуляции
    # if payment_request.paid_at:
    #     timeline.append({
    #         "timestamp": payment_request.paid_at,
    #         "title": "Платеж завершен",
    #         "description": f"Платеж успешно завершен",
    #         "event_type": "payment_completed",
    #         "status": "success"
    #     })

    # Сортируем по времени
    timeline.sort(key=lambda x: x["timestamp"])

    # Технические детали (берём последние связанные логи по токену)
    try:
        logs = db.query(PaymentLog).filter(
            PaymentLog.token.contains(token_uuid)
        ).order_by(PaymentLog.created_at.asc()).all()

        tech_logs = []
        for l in logs:
            try:
                tech_logs.append({
                    "created_at": l.created_at,
                    "request_type": getattr(l, 'request_type', 'unknown'),
                    "http_method": getattr(l, 'http_method', 'GET'),
                    "endpoint": getattr(l, 'endpoint', ''),
                    "status": getattr(l, 'response_status', 200),
                    "request_headers": getattr(l, 'request_headers', ''),
                    "request_body": getattr(l, 'request_body', ''),
                    "response_body": getattr(l, 'response_body', ''),
                    "error": getattr(l, 'error_message', ''),
                    "bank_code": getattr(l, 'bank_code', '')
                })
            except:
                continue
    except:
        tech_logs = []

    # Получаем названия банков
    sender_bank_name = "N/A"
    receiver_bank_name = "N/A"
    
    if payment_request.payer_bank_code or payment_request.sender_bank_code:
        bank_code = payment_request.payer_bank_code or payment_request.sender_bank_code
        sender_bank = db.query(Bank).filter(Bank.code == bank_code).first()
        if sender_bank:
            sender_bank_name = sender_bank.name
    
    if payment_request.receiver_bank_code:
        receiver_bank = db.query(Bank).filter(Bank.code == payment_request.receiver_bank_code).first()
        if receiver_bank:
            receiver_bank_name = receiver_bank.name

    return {
        "transaction": {
            "transaction_id": payment_request.transaction_id,
            "payment_token": token_uuid,
            "amount": payment_request.amount,
            "status": payment_request.status.value if payment_request.status else "pending",
            "bank_code": payment_request.receiver_bank_code,
            "processed_at": payment_request.paid_at
        },
        "payment_request": {
            "reference": payment_request.payment_reference,
            "created_at": payment_request.created_at,
            "receiver_name": payment_request.receiver_name,
            "amount": payment_request.amount,
            "currency": payment_request.currency,
            "description": payment_request.description,
            "sender_bank_code": payment_request.payer_bank_code or payment_request.sender_bank_code,
            "sender_bank_name": sender_bank_name,
            "receiver_bank_code": payment_request.receiver_bank_code,
            "receiver_bank_name": receiver_bank_name,
            "receiver_account": payment_request.receiver_account,
            "payer_phone": payment_request.payer_phone,
            "expires_at": payment_request.expires_at,
            "is_paid": payment_request.is_paid
        },
        "timeline": timeline,
        "technical": {
            "logs": tech_logs,
            "webhook": None,
            "billing": None
        }
    }






@router.post("/transactions/{transaction_id}/cancel")
async def cancel_transaction(
    transaction_id: str, 
    db: Session = Depends(get_db),
    current_admin = None
):
    """Отмена транзакции"""
    # Ищем транзакцию по ID или payment_reference (только SIM_платежи)
    payment = db.query(UnifiedPayment).filter(
        UnifiedPayment.transaction_id.like('SIM_%'),  # Показываем только SIM_платежи
        (UnifiedPayment.id == transaction_id) |
        (UnifiedPayment.payment_reference == transaction_id) |
        (UnifiedPayment.qr_code.has(qr_token=transaction_id))
    ).first()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    # Проверяем, можно ли отменить транзакцию
    if payment.status not in ['pending', 'preparing', 'prepared']:
        raise HTTPException(
            status_code=400, 
            detail=f"Нельзя отменить транзакцию в статусе {payment.status}"
        )
    
    # Отменяем транзакцию
    payment.status = 'aborted'
    payment.updated_at = datetime.now()
    
    try:
        db.commit()
        
        # Логируем отмену
        hybrid_logging_service.log_admin_action(
            db=db,
            action="cancel_transaction",
            target=transaction_id,
            details={
                "transaction_id": transaction_id,
                "payment_reference": payment.payment_reference,
                "amount": payment.amount,
                "previous_status": payment.status
            },
            actor_id=current_admin.get('username') if current_admin else None
        )
        
        return {"message": "Транзакция отменена", "transaction_id": transaction_id}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка отмены транзакции: {str(e)}")