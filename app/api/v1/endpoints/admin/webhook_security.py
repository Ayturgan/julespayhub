# Webhook security endpoints for admin
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.payment import Bank
from app.services.webhook_security_service import WebhookSecurityService
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import time

router = APIRouter()

# === БЕЗОПАСНОСТЬ WEBHOOK ===



@router.get("/webhook/security-guide")
async def get_webhook_security_guide():
    """
    Руководство по безопасности webhook для банков
    """
    return {
        "webhook_security_guide": {
            "overview": "QRPayHub использует HMAC-SHA256 для проверки подлинности webhook",
            "required_headers": {
                "x-signature": "HMAC подпись в формате sha256=<hex>",
                "x-timestamp": "Unix timestamp или ISO 8601 формат",
                "content-type": "application/json",
                "authorization": "Bearer <access_token>"
            },
            "signature_calculation": {
                "algorithm": "HMAC-SHA256",
                "message_format": "METHOD|PATH|BODY|TIMESTAMP",
                "example": "POST|/api/v1/payment/payment-status|{json_body}|1642248000"
            },
            "security_requirements": {
                "timestamp_tolerance": f"{WebhookSecurityService.MAX_TIMESTAMP_AGE} seconds",
                "ip_whitelist": "Configure allowed IPs in bank settings",
                "signature_verification": "All webhook must include valid signature",
                "replay_protection": "Timestamps prevent replay attacks"
            },
            "example_implementation": {
                "python": '''
import hmac
import hashlib
import time

def create_webhook_signature(secret, method, path, body):
    timestamp = str(int(time.time()))
    message = f"{method}|{path}|{body}|{timestamp}"
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}", timestamp
                ''',
                "headers_example": {
                    "Authorization": "Bearer your_access_token",
                    "X-Signature": "sha256=abc123...",
                    "X-Timestamp": "1642248000",
                    "Content-Type": "application/json",
                    "User-Agent": "YourBank/1.0"
                }
            },
            "troubleshooting": {
                "common_errors": [
                    "Invalid signature - check HMAC calculation",
                    "Timestamp too old - ensure clock synchronization",
                    "Missing headers - include all required headers",
                    "Wrong message format - verify METHOD|PATH|BODY|TIMESTAMP"
                ],
                "generate_endpoint": "/api/v1/admin/webhook/generate-signature",
                "verify_endpoint": "/api/v1/admin/webhook/verify-signature"
            }
        }
    }