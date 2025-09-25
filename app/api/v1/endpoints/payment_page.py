from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional

from app.database import get_db
from app.models.unified import UnifiedPayment as PaymentRequest
from app.models.payment import Bank
from app.services.token_service import SecureTokenService
from app.services.error_handling_service import ErrorHandlingService, ErrorCode

router = APIRouter()

@router.get("/pay", response_class=HTMLResponse)
async def payment_page(
    token: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Страница обработки QR-кода для плательщиков
    """
    
    # Извлекаем UUID из токена
    token_uuid = SecureTokenService.extract_uuid_from_token(token)
    if not token_uuid:
        return create_error_page("Неверный формат токена", "Пожалуйста, проверьте правильность QR-кода")
    
    # Ищем платежный запрос
    payment_request = db.query(PaymentRequest).filter(
        PaymentRequest.token == token_uuid
    ).first()
    
    if not payment_request:
        return create_error_page("Платежный запрос не найден", "QR-код недействителен или истек")
    
    # Проверяем валидность токена
    validation_result = SecureTokenService.validate_token(token, payment_request)
    
    if not validation_result["valid"]:
        if validation_result.get("expired"):
            return create_error_page("Токен истек", "Время действия QR-кода истекло. Получите новый QR-код")
        if validation_result.get("used"):
            return create_success_page("Платеж уже выполнен", f"Платеж {payment_request.payment_reference} уже был успешно обработан")
        else:
            return create_error_page("Неверный токен", "QR-код поврежден или недействителен")
    
    # Если платеж уже оплачен
    if payment_request.is_paid:
        return create_success_page("Платеж выполнен", f"Платеж {payment_request.payment_reference} успешно выполнен")
    
    # Создаем событие в таймлайне о сканировании QR-кода
    try:
        from app.services.timeline_service import TimelineService
        TimelineService.record_event(
            db,
            payment_token=token_uuid,
            transaction_id=str(payment_request.id),
            event_type='qr_scanned',
            title='QR-код отсканирован',
            description=f"QR-код отсканирован пользователем с IP {request.client.host if request.client else 'unknown'}",
            actor='payer',
            source='web',
            status='success',
            metadata={
                "payment_request_id": payment_request.id,
                "ip_address": request.client.host if request.client else 'unknown'
            }
        )
    except Exception as e:
        # Игнорируем ошибки таймлайна, чтобы не ломать основной функционал
        pass
    
    # Создаем страницу платежа
    return create_payment_page(payment_request, token)


def create_payment_page(payment_request: PaymentRequest, token: str) -> str:
    """Простой MVP HTML без лишнего оформления."""

    amount_display = f"{payment_request.amount} {payment_request.currency}" if payment_request.amount else "Сумма укажется в приложении банка"

    return f"""
<!DOCTYPE html>
<html lang=\"ru\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>QRPayHub - Платеж</title>
    <style>
        :root {{ --bg:#0b1f16; --panel:#0f2a1d; --text:#e5f4ec; --muted:#9fb9ac; --accent:#16a34a; }}
        body {{ background: var(--bg); color: var(--text); font-family: Arial, sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; }}
        h1 {{ font-size: 18px; margin: 0 0 12px; }}
        .box {{ background: var(--panel); border: 1px solid rgba(255,255,255,.08); padding: 12px; border-radius: 10px; margin-bottom: 12px; }}
        .row {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,.06); }}
        .row:last-child {{ border-bottom: none; }}
        .label {{ color: var(--muted); }}
        .value {{ font-weight: 600; }}
        .note {{ font-size: 12px; color: var(--muted); }}
        .success {{ color: var(--accent); }}
        .error {{ color: #ef4444; }}
        a {{ color: var(--accent); text-decoration: none; }}
        .btn {{ background: var(--accent); color:#04160d; border: none; padding: 8px 12px; border-radius: 8px; cursor: pointer; font-weight: 600; }}
    </style>
    <script>
        // Простая периодическая проверка статуса платежа (опционально)
        let checks = 0; const maxChecks = 60;
        function poll() {{
            if (checks >= maxChecks) return;
            fetch('/api/v1/qr/info/{token}')
                .then(r => r.json())
                .then(d => {{ if (d.is_paid) location.reload(); }})
                .catch(() => {{}})
                .finally(() => {{ checks++; if (checks < maxChecks) setTimeout(poll, 5000); }});
        }}
        window.addEventListener('load', () => setTimeout(poll, 5000));
    </script>
</head>
<body>
    <h1>Платежная информация</h1>
    <div class=\"box\"> 
        <div class=\"row\"><span class=\"label\">Получатель:</span><span class=\"value\">{payment_request.receiver_name}</span></div>
        <div class=\"row\"><span class=\"label\">Описание:</span><span class=\"value\">{payment_request.description}</span></div>
        <div class=\"row\"><span class=\"label\">Сумма:</span><span class=\"value\">{amount_display}</span></div>
        <div class=\"row\"><span class=\"label\">Номер платежа:</span><span class=\"value\">{payment_request.payment_reference}</span></div>
    </div>
    <div class=\"box\" style=\"text-align: center; background: linear-gradient(135deg, #16a34a, #22c55e); border: 2px solid #22c55e;\">
        <h3 style=\"margin: 0 0 8px; color: #064e3b;\">💳 Оплата</h3>
        <p style=\"margin: 8px 0 0; color: #064e3b; font-size: 13px;\">Отсканируйте QR-код для оплаты</p>
    </div>
    <div class=\"box\">
        <p class=\"note\">Или откройте приложение вашего банка, отсканируйте QR и подтвердите платеж.</p>
    </div>
    <p><a href=\"/\">← На главную</a></p>
</body>
</html>
"""


def create_error_page(title: str, message: str) -> str:
    """Минималистичная ошибка (тёмнозелёный MVP)"""
    return f"""
<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Ошибка</title>
  <style>
    :root {{ --bg: #0b1f16; --panel: #0f2a1d; --text: #e5f4ec; --accent: #16a34a; --danger: #ef4444; }}
    body {{ background: var(--bg); color: var(--text); font-family: Arial, sans-serif; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:16px; }}
    .card {{ background: var(--panel); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 20px; max-width: 520px; width:100%; }}
    h1 {{ margin: 0 0 8px; font-size: 18px; color: var(--danger); }}
    p {{ margin: 0 0 12px; opacity: .9; }}
    a {{ color: var(--accent); text-decoration: none; }}
  </style>
  </head>
  <body>
    <div class=\"card\">
      <h1>{title}</h1>
      <p>{message}</p>
      <p><a href=\"/\">← На главную</a></p>
    </div>
  </body>
  </html>
"""


def create_success_page(title: str, message: str) -> str:
    """Минималистичный успех (тёмнозелёный MVP)"""
    return f"""
<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Успешно</title>
  <style>
    :root {{ --bg: #0b1f16; --panel: #0f2a1d; --text: #e5f4ec; --accent: #16a34a; }}
    body {{ background: var(--bg); color: var(--text); font-family: Arial, sans-serif; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:16px; }}
    .card {{ background: var(--panel); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 20px; max-width: 520px; width:100%; }}
    h1 {{ margin: 0 0 8px; font-size: 18px; color: var(--accent); }}
    p {{ margin: 0 0 12px; opacity: .9; }}
    a {{ color: var(--accent); text-decoration: none; }}
  </style>
  </head>
  <body>
    <div class=\"card\">
      <h1>{title}</h1>
      <p>{message}</p>
      <p><a href=\"/\">← На главную</a></p>
    </div>
  </body>
  </html>
"""

