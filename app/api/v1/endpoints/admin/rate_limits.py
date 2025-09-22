# Rate limiting management endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.rate_limit_service import RateLimitService
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

router = APIRouter()

# === УПРАВЛЕНИЕ RATE LIMITING ===

@router.get("/rate-limits")
async def get_rate_limit_stats(
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    bank_code: Optional[str] = None,
    hours: int = 24,
    db: Session = Depends(get_db)
):
    """
    Статистика rate limiting
    """
    stats = RateLimitService.get_rate_limit_stats(
        db=db,
        ip_address=ip_address,
        endpoint=endpoint,
        bank_code=bank_code,
        hours=hours
    )
    
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "bank_code": s.bank_code,
            "endpoint": s.endpoint,
            "request_count": s.request_count,
            "is_blocked": s.is_blocked,
            "blocked_until": s.blocked_until.isoformat() if s.blocked_until else None,
            "window_start": s.window_start,
            "last_request": s.last_request,
            "user_agent": s.user_agent
        }
        for s in stats
    ]

@router.post("/rate-limits/unblock")
async def unblock_ip(
    ip_address: str,
    endpoint: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Разблокировка IP адреса
    """
    count = RateLimitService.unblock_ip(db, ip_address, endpoint)
    
    return {
        "message": f"Unblocked {count} records for IP {ip_address}",
        "unblocked_count": count
    }

@router.post("/rate-limits/cleanup")
async def cleanup_rate_limits(
    days: int = 7,
    db: Session = Depends(get_db)
):
    """
    Очистка старых записей rate limiting
    """
    count = RateLimitService.cleanup_old_records(db, days)
    
    return {
        "message": f"Cleaned up {count} old rate limit records",
        "deleted_count": count
    }
