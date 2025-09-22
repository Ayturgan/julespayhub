import asyncio
import json
import smtplib
import requests
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, func
import logging
import threading
from collections import defaultdict

from app.models.payment import Base, Bank
from app.services.realtime_monitoring_service import (
    realtime_monitoring_service, MonitoringStatus, AlertSeverity
)
import time

logger = logging.getLogger(__name__)

class NotificationChannel(str, Enum):
    """Каналы уведомлений"""
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    SLACK = "slack"
    INTERNAL = "internal"  # Внутренние уведомления в админке

class AlertType(str, Enum):
    """Типы алертов"""
    BANK_DOWN = "bank_down"
    API_UNAVAILABLE = "api_unavailable"
    HIGH_ERROR_RATE = "high_error_rate"
    SLOW_RESPONSE = "slow_response"
    WEBHOOK_FAILURES = "webhook_failures"
    AUTHENTICATION_ISSUES = "auth_issues"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INTEGRATION_FAILURE = "integration_failure"
    SYSTEM_OVERLOAD = "system_overload"
    BANK_INACTIVE = "bank_inactive"
    VALIDATION_ERRORS = "validation_errors"
    PAYMENT_MISMATCH = "payment_mismatch"
    DUPLICATE_TRANSACTION_ID = "duplicate_transaction_id"
    TOKEN_REUSE_ATTEMPT = "token_reuse_attempt"
    TOKEN_EXPIRED = "token_expired"

class AlertStatus(str, Enum):
    """Статусы алертов"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"

# Модель для хранения алертов в БД
class BankAlert(Base):
    __tablename__ = "bank_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(String(100), unique=True, index=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    bank_code = Column(String(10), nullable=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # JSON
    status = Column(String(20), default=AlertStatus.PENDING.value)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    notification_channels = Column(Text, nullable=True)  # JSON список каналов
    retry_count = Column(Integer, default=0)
    last_retry_at = Column(DateTime(timezone=True), nullable=True)

# Модель для настроек уведомлений
class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    bank_code = Column(String(10), nullable=True)  # Null = глобальные настройки
    alert_type = Column(String(50), nullable=False)
    channels = Column(Text, nullable=False)  # JSON список каналов
    recipients = Column(Text, nullable=False)  # JSON список получателей
    is_enabled = Column(Boolean, default=True)
    cooldown_minutes = Column(Integer, default=60)  # Минуты между повторными алертами
    escalation_minutes = Column(Integer, default=0)  # Минуты до эскалации
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

@dataclass
class NotificationRecipient:
    """Получатель уведомления"""
    channel: NotificationChannel
    address: str  # email, phone, webhook_url, chat_id
    name: Optional[str] = None
    is_active: bool = True

@dataclass
class AlertConfiguration:
    """Конфигурация алерта"""
    alert_type: AlertType
    channels: List[NotificationChannel]
    recipients: List[NotificationRecipient]
    cooldown_minutes: int = 60
    escalation_minutes: int = 0
    is_enabled: bool = True

class BankAlertsService:
    """Сервис уведомлений при проблемах с банками"""
    
    def __init__(self):
        self._alert_configs: Dict[str, Dict[AlertType, AlertConfiguration]] = {}
        self._sent_alerts: Dict[str, datetime] = {}  # Для cooldown
        self._processing_thread: Optional[threading.Thread] = None
        self._stop_processing = threading.Event()
        self._alert_queue: asyncio.Queue = None
        self._lock = threading.Lock()
        
        # Настройки по умолчанию для SMTP
        self.smtp_settings = {
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "",
            "password": "",
            "use_tls": True
        }
        
        # Настройки для Telegram
        self.telegram_settings = {
            "bot_token": "",
            "enabled": False
        }
        
        # Настройки для SMS (можно интегрировать с Twilio, SMS.ru и т.д.)
        self.sms_settings = {
            "provider": "sms_ru",
            "api_key": "",
            "enabled": False
        }
        
        # Подписываемся на события мониторинга
        realtime_monitoring_service.subscribe_to_updates(self._handle_monitoring_update)
    
    def start_processing(self):
        """Запуск обработки алертов в фоновом режиме"""
        if self._processing_thread and self._processing_thread.is_alive():
            logger.warning("🚨 Система алертов уже запущена")
            return
        
        self._stop_processing.clear()
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            daemon=True
        )
        self._processing_thread.start()
        logger.warning("🚨 Система алертов запущена")
    
    def stop_processing(self):
        """Остановка обработки алертов"""
        self._stop_processing.set()
        if self._processing_thread:
            self._processing_thread.join(timeout=5)
        logger.warning("🚨 Система алертов остановлена")
    
    def _processing_loop(self):
        """Основной цикл обработки алертов"""
        while not self._stop_processing.is_set():
            try:
                # Обрабатываем алерты каждые 30 секунд
                self._process_pending_alerts()
                self._retry_failed_alerts()
                self._check_escalations()
                
                # Ждем 30 секунд или до остановки
                self._stop_processing.wait(30)
                
            except Exception as e:
                logger.error(f"Error in alerts processing loop: {e}")
                self._stop_processing.wait(10)
    
    def _handle_monitoring_update(self, update_data: Dict[str, Any]):
        """Обработка обновлений мониторинга"""
        try:
            metrics = update_data.get("metrics", {})
            alerts = update_data.get("alerts", [])
            
            # Обрабатываем новые алерты из мониторинга
            for alert in alerts:
                if not alert.get("acknowledged", False):
                    self._create_alert_from_monitoring(alert)
            
            # Проверяем метрики банков на проблемы
            bank_metrics = metrics.get("bank_metrics", {})
            for bank_code, bank_data in bank_metrics.items():
                self._check_bank_health(bank_code, bank_data)
                
        except Exception as e:
            logger.error(f"Error handling monitoring update: {e}")
    
    def _create_alert_from_monitoring(self, monitoring_alert: Dict[str, Any]):
        """Создание алерта на основе данных мониторинга"""
        try:
            severity = monitoring_alert.get("severity", "info")
            bank_code = monitoring_alert.get("metadata", {}).get("bank_code")
            
            # Определяем тип алерта
            alert_type = self._determine_alert_type(monitoring_alert)
            
            # Создаем алерт
            self.create_alert(
                alert_type=alert_type,
                severity=AlertSeverity(severity),
                bank_code=bank_code,
                title=monitoring_alert.get("title", "Unknown Alert"),
                message=monitoring_alert.get("message", ""),
                details=monitoring_alert.get("metadata", {})
            )
            
        except Exception as e:
            logger.error(f"Error creating alert from monitoring: {e}")
    
    def _determine_alert_type(self, monitoring_alert: Dict[str, Any]) -> AlertType:
        """Определение типа алерта на основе данных мониторинга"""
        title = monitoring_alert.get("title", "").lower()
        message = monitoring_alert.get("message", "").lower()
        
        if "unavailable" in title or "timeout" in title or "unavailable" in message or "timeout" in message:
            return AlertType.API_UNAVAILABLE
        if "error rate" in title or "error rate" in message:
            return AlertType.HIGH_ERROR_RATE
        elif "response time" in title or "slow" in message:
            return AlertType.SLOW_RESPONSE
        elif "webhook" in title or "webhook" in message:
            return AlertType.WEBHOOK_FAILURES
        elif "authentication" in title or "auth" in message:
            return AlertType.AUTHENTICATION_ISSUES
        elif "rate limit" in title or "rate limit" in message:
            return AlertType.RATE_LIMIT_EXCEEDED
        elif "inactive" in title or "inactive" in message:
            return AlertType.BANK_INACTIVE
        else:
            return AlertType.INTEGRATION_FAILURE
    
    def _check_bank_health(self, bank_code: str, bank_metrics: Dict[str, Any]):
        """Проверка здоровья банка и создание алертов при необходимости"""
        try:
            status = bank_metrics.get("status", "unknown")
            
            # Проверяем статус банка
            if status == MonitoringStatus.CRITICAL.value:
                self._create_bank_critical_alert(bank_code, bank_metrics)
            elif status == MonitoringStatus.ERROR.value:
                self._create_bank_error_alert(bank_code, bank_metrics)
            
            # Проверяем специфичные проблемы
            error_rate = bank_metrics.get("error_rate_1h", 0)
            if error_rate > 15:  # 15% ошибок
                self.create_alert(
                    alert_type=AlertType.HIGH_ERROR_RATE,
                    severity=AlertSeverity.ERROR,
                    bank_code=bank_code,
                    title=f"High Error Rate: {bank_code}",
                    message=f"Bank {bank_code} has {error_rate:.1f}% error rate in the last hour",
                    details={"error_rate": error_rate, "threshold": 15}
                )
            
            # Проверяем время ответа
            response_time = bank_metrics.get("avg_response_time_ms", 0)
            if response_time > 10000:  # 10 секунд
                self.create_alert(
                    alert_type=AlertType.SLOW_RESPONSE,
                    severity=AlertSeverity.WARNING,
                    bank_code=bank_code,
                    title=f"Slow Response Time: {bank_code}",
                    message=f"Bank {bank_code} has average response time of {response_time:.0f}ms",
                    details={"response_time_ms": response_time, "threshold_ms": 10000}
                )
            
            # Проверяем webhook failures
            webhook_failures = bank_metrics.get("webhook_failures_1h", 0)
            if webhook_failures > 5:
                self.create_alert(
                    alert_type=AlertType.WEBHOOK_FAILURES,
                    severity=AlertSeverity.ERROR,
                    bank_code=bank_code,
                    title=f"Webhook Failures: {bank_code}",
                    message=f"Bank {bank_code} has {webhook_failures} webhook failures in the last hour",
                    details={"webhook_failures": webhook_failures, "threshold": 5}
                )
                
        except Exception as e:
            logger.error(f"Error checking bank health for {bank_code}: {e}")
    
    def _create_bank_critical_alert(self, bank_code: str, metrics: Dict[str, Any]):
        """Создание критического алерта для банка"""
        self.create_alert(
            alert_type=AlertType.BANK_DOWN,
            severity=AlertSeverity.CRITICAL,
            bank_code=bank_code,
            title=f"Bank Critical Status: {bank_code}",
            message=f"Bank {bank_code} is in critical state and may be down",
            details=metrics
        )
    
    def _create_bank_error_alert(self, bank_code: str, metrics: Dict[str, Any]):
        """Создание алерта об ошибках банка"""
        self.create_alert(
            alert_type=AlertType.INTEGRATION_FAILURE,
            severity=AlertSeverity.ERROR,
            bank_code=bank_code,
            title=f"Bank Integration Issues: {bank_code}",
            message=f"Bank {bank_code} has integration issues",
            details=metrics
        )
    
    def create_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        bank_code: Optional[str],
        title: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Создание нового алерта"""
        
        # Генерируем уникальный ID алерта
        alert_id = f"{alert_type.value}_{bank_code or 'system'}_{int(time.time())}"
        
        # Проверяем cooldown
        cooldown_key = f"{alert_type.value}_{bank_code or 'system'}"
        if self._is_in_cooldown(cooldown_key):
            logger.debug(f"Alert {alert_id} skipped due to cooldown")
            return alert_id
        
        # Сохраняем алерт в БД
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                alert = BankAlert(
                    alert_id=alert_id,
                    alert_type=alert_type.value,
                    severity=severity.value,
                    bank_code=bank_code,
                    title=title,
                    message=message,
                    details=json.dumps(details) if details else None,
                    status=AlertStatus.PENDING.value
                )
                
                db.add(alert)
                db.commit()
                
                logger.info(f"Created alert {alert_id}: {title}")
                
                # Обновляем cooldown
                with self._lock:
                    self._sent_alerts[cooldown_key] = datetime.now()
                
                return alert_id
                
        except Exception as e:
            logger.error(f"Failed to create alert {alert_id}: {e}")
            return alert_id
    
    def _is_in_cooldown(self, cooldown_key: str) -> bool:
        """Проверка cooldown для алерта"""
        with self._lock:
            last_sent = self._sent_alerts.get(cooldown_key)
            if last_sent:
                # По умолчанию 60 минут cooldown
                cooldown_minutes = 60
                if datetime.now() - last_sent < timedelta(minutes=cooldown_minutes):
                    return True
        return False
    
    def _process_pending_alerts(self):
        """Обработка отложенных алертов"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                # Получаем все отложенные алерты
                pending_alerts = db.query(BankAlert).filter(
                    BankAlert.status == AlertStatus.PENDING.value
                ).limit(50).all()
                
                for alert in pending_alerts:
                    try:
                        success = self._send_alert(alert)
                        
                        if success:
                            alert.status = AlertStatus.SENT.value
                            alert.sent_at = datetime.now()
                        else:
                            alert.status = AlertStatus.FAILED.value
                            alert.retry_count += 1
                            alert.last_retry_at = datetime.now()
                        
                        db.commit()
                        
                    except Exception as e:
                        logger.error(f"Error processing alert {alert.alert_id}: {e}")
                        alert.status = AlertStatus.FAILED.value
                        alert.retry_count += 1
                        alert.last_retry_at = datetime.now()
                        db.commit()
                        
        except Exception as e:
            logger.error(f"Error processing pending alerts: {e}")
    
    def _send_alert(self, alert: BankAlert) -> bool:
        """Отправка алерта по настроенным каналам"""
        try:
            # Получаем конфигурацию уведомлений
            config = self._get_alert_configuration(alert.bank_code, AlertType(alert.alert_type))
            
            if not config or not config.is_enabled:
                logger.debug(f"Alert {alert.alert_id} disabled or no config")
                return True  # Считаем успешным, если отключено
            
            success = True
            
            # Отправляем по всем каналам
            for recipient in config.recipients:
                try:
                    channel_success = self._send_to_channel(alert, recipient)
                    if not channel_success:
                        success = False
                except Exception as e:
                    logger.error(f"Error sending alert {alert.alert_id} to {recipient.channel.value}: {e}")
                    success = False
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending alert {alert.alert_id}: {e}")
            return False
    
    def _send_to_channel(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Отправка алерта по конкретному каналу"""
        
        if not recipient.is_active:
            return True
        
        try:
            if recipient.channel == NotificationChannel.EMAIL:
                return self._send_email(alert, recipient)
            elif recipient.channel == NotificationChannel.SMS:
                return self._send_sms(alert, recipient)
            elif recipient.channel == NotificationChannel.WEBHOOK:
                return self._send_webhook(alert, recipient)
            elif recipient.channel == NotificationChannel.TELEGRAM:
                return self._send_telegram(alert, recipient)
            elif recipient.channel == NotificationChannel.INTERNAL:
                return self._send_internal(alert, recipient)
            else:
                logger.warning(f"Unsupported notification channel: {recipient.channel}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending to channel {recipient.channel}: {e}")
            return False
    
    def _send_email(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Отправка email уведомления"""
        try:
            if not self.smtp_settings.get("username") or not self.smtp_settings.get("password"):
                logger.warning("SMTP settings not configured")
                return False
            
            # Создаем сообщение
            msg = MIMEMultipart()
            msg['From'] = self.smtp_settings["username"]
            msg['To'] = recipient.address
            msg['Subject'] = f"[QRPayHub Alert] {alert.title}"
            
            # Формируем тело письма
            body = self._format_alert_message(alert, "email")
            msg.attach(MIMEText(body, 'html'))
            
            # Отправляем
            with smtplib.SMTP(self.smtp_settings["host"], self.smtp_settings["port"]) as server:
                if self.smtp_settings.get("use_tls", True):
                    server.starttls()
                server.login(self.smtp_settings["username"], self.smtp_settings["password"])
                server.send_message(msg)
            
            logger.info(f"Email alert sent to {recipient.address}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False
    
    def _send_sms(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Отправка SMS уведомления"""
        try:
            if not self.sms_settings.get("enabled") or not self.sms_settings.get("api_key"):
                logger.warning("SMS settings not configured")
                return False
            
            # Формируем короткое сообщение для SMS
            message = f"QRPayHub Alert: {alert.title}. {alert.message[:100]}..."
            
            # Отправляем через SMS.ru (пример)
            if self.sms_settings["provider"] == "sms_ru":
                response = requests.post(
                    "https://sms.ru/sms/send",
                    data={
                        "api_id": self.sms_settings["api_key"],
                        "to": recipient.address,
                        "msg": message,
                        "json": 1
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "OK":
                        logger.info(f"SMS alert sent to {recipient.address}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to send SMS alert: {e}")
            return False
    
    def _send_webhook(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Отправка webhook уведомления"""
        try:
            payload = {
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "bank_code": alert.bank_code,
                "title": alert.title,
                "message": alert.message,
                "details": json.loads(alert.details) if alert.details else {},
                "created_at": alert.created_at.isoformat(),
                "timestamp": datetime.now().isoformat()
            }
            
            response = requests.post(
                recipient.address,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code in [200, 201, 202]:
                logger.info(f"Webhook alert sent to {recipient.address}")
                return True
            else:
                logger.warning(f"Webhook returned status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
            return False
    
    def _send_telegram(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Отправка Telegram уведомления"""
        try:
            if not self.telegram_settings.get("enabled") or not self.telegram_settings.get("bot_token"):
                logger.warning("Telegram settings not configured")
                return False
            
            # Формируем сообщение для Telegram
            message = self._format_alert_message(alert, "telegram")
            
            # Отправляем через Telegram Bot API
            response = requests.post(
                f"https://api.telegram.org/bot{self.telegram_settings['bot_token']}/sendMessage",
                json={
                    "chat_id": recipient.address,
                    "text": message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Telegram alert sent to {recipient.address}")
                return True
            else:
                logger.warning(f"Telegram API returned status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False
    
    def _send_internal(self, alert: BankAlert, recipient: NotificationRecipient) -> bool:
        """Внутреннее уведомление (в админке)"""
        try:
            # Просто помечаем как отправленное - уведомление будет видно в админке
            logger.info(f"Internal alert created: {alert.alert_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create internal alert: {e}")
            return False
    
    def _format_alert_message(self, alert: BankAlert, format_type: str) -> str:
        """Форматирование сообщения алерта для разных каналов"""
        
        if format_type == "email":
            return f"""
            <html>
            <body>
                <h2>🚨 QRPayHub Alert</h2>
                <p><strong>Alert Type:</strong> {alert.alert_type}</p>
                <p><strong>Severity:</strong> {alert.severity}</p>
                <p><strong>Bank:</strong> {alert.bank_code or 'System'}</p>
                <p><strong>Title:</strong> {alert.title}</p>
                <p><strong>Message:</strong> {alert.message}</p>
                <p><strong>Time:</strong> {alert.created_at}</p>
                
                {f'<p><strong>Details:</strong><br><pre>{alert.details}</pre></p>' if alert.details else ''}
                
                <hr>
                <p><small>QRPayHub Monitoring System</small></p>
            </body>
            </html>
            """
        
        elif format_type == "telegram":
            severity_emoji = {
                "INFO": "ℹ️",
                "WARNING": "⚠️",
                "ERROR": "❌",
                "CRITICAL": "🚨"
            }
            
            emoji = severity_emoji.get(alert.severity.upper(), "📢")
            
            return f"""
{emoji} <b>QRPayHub Alert</b>

<b>Type:</b> {alert.alert_type}
<b>Severity:</b> {alert.severity}
<b>Bank:</b> {alert.bank_code or 'System'}
<b>Title:</b> {alert.title}

<b>Message:</b>
{alert.message}

<b>Time:</b> {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}
            """.strip()
        
        else:  # Plain text
            return f"""
QRPayHub Alert

Type: {alert.alert_type}
Severity: {alert.severity}
Bank: {alert.bank_code or 'System'}
Title: {alert.title}

Message:
{alert.message}

Time: {alert.created_at}
            """.strip()
    
    def _get_alert_configuration(self, bank_code: Optional[str], alert_type: AlertType) -> Optional[AlertConfiguration]:
        """Получение конфигурации алерта"""
        # Пытаемся найти конфигурацию для конкретного банка
        if bank_code and bank_code in self._alert_configs:
            config = self._alert_configs[bank_code].get(alert_type)
            if config:
                return config
        
        # Используем глобальную конфигурацию
        global_config = self._alert_configs.get("global", {}).get(alert_type)
        if global_config:
            return global_config
        
        # Возвращаем конфигурацию по умолчанию
        return self._get_default_configuration(alert_type)
    
    def _get_default_configuration(self, alert_type: AlertType) -> AlertConfiguration:
        """Получение конфигурации по умолчанию"""
        
        # Базовые получатели (можно настроить через админку)
        default_recipients = [
            NotificationRecipient(
                channel=NotificationChannel.INTERNAL,
                address="admin",
                name="Admin Panel"
            )
        ]
        
        return AlertConfiguration(
            alert_type=alert_type,
            channels=[NotificationChannel.INTERNAL],
            recipients=default_recipients,
            cooldown_minutes=60,
            escalation_minutes=0,
            is_enabled=True
        )
    
    def configure_alert(
        self,
        bank_code: Optional[str],
        alert_type: AlertType,
        channels: List[NotificationChannel],
        recipients: List[NotificationRecipient],
        cooldown_minutes: int = 60,
        escalation_minutes: int = 0,
        is_enabled: bool = True
    ):
        """Настройка алерта"""
        
        config = AlertConfiguration(
            alert_type=alert_type,
            channels=channels,
            recipients=recipients,
            cooldown_minutes=cooldown_minutes,
            escalation_minutes=escalation_minutes,
            is_enabled=is_enabled
        )
        
        key = bank_code or "global"
        
        if key not in self._alert_configs:
            self._alert_configs[key] = {}
        
        self._alert_configs[key][alert_type] = config
        
        logger.info(f"Configured alert {alert_type.value} for {key}")
    
    def _retry_failed_alerts(self):
        """Повторная отправка неудачных алертов"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                # Получаем неудачные алерты для повтора (не более 3 попыток)
                failed_alerts = db.query(BankAlert).filter(
                    BankAlert.status == AlertStatus.FAILED.value,
                    BankAlert.retry_count < 3,
                    BankAlert.last_retry_at < datetime.now() - timedelta(minutes=30)
                ).limit(20).all()
                
                for alert in failed_alerts:
                    try:
                        success = self._send_alert(alert)
                        
                        if success:
                            alert.status = AlertStatus.SENT.value
                            alert.sent_at = datetime.now()
                        else:
                            alert.retry_count += 1
                            alert.last_retry_at = datetime.now()
                        
                        db.commit()
                        
                    except Exception as e:
                        logger.error(f"Error retrying alert {alert.alert_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Error retrying failed alerts: {e}")
    
    def _check_escalations(self):
        """Проверка эскалации алертов"""
        # TODO: Реализация эскалации алертов при необходимости
        pass
    
    def get_recent_alerts(self, limit: int = 50, bank_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получение недавних алертов"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                query = db.query(BankAlert)
                
                if bank_code:
                    query = query.filter(BankAlert.bank_code == bank_code)
                
                alerts = query.order_by(BankAlert.created_at.desc()).limit(limit).all()
                
                return [
                    {
                        "alert_id": alert.alert_id,
                        "alert_type": alert.alert_type,
                        "severity": alert.severity,
                        "bank_code": alert.bank_code,
                        "title": alert.title,
                        "message": alert.message,
                        "details": (json.loads(alert.details) if alert.details else None),
                        "status": alert.status,
                        "created_at": alert.created_at.isoformat(),
                        "sent_at": alert.sent_at.isoformat() if alert.sent_at else None,
                        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                        "retry_count": alert.retry_count
                    }
                    for alert in alerts
                ]
                
        except Exception as e:
            logger.error(f"Error getting recent alerts: {e}")
            return []

    def get_alert_by_id(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Получение алерта по идентификатору"""
        try:
            from app.database import SessionLocal
            with SessionLocal() as db:
                alert = db.query(BankAlert).filter(BankAlert.alert_id == alert_id).first()
                if not alert:
                    return None
                return {
                    "alert_id": alert.alert_id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "bank_code": alert.bank_code,
                    "title": alert.title,
                    "message": alert.message,
                    "details": (json.loads(alert.details) if alert.details else None),
                    "status": alert.status,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                    "sent_at": alert.sent_at.isoformat() if alert.sent_at else None,
                    "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                    "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                    "retry_count": alert.retry_count,
                }
        except Exception as e:
            logger.error(f"Error getting alert by id {alert_id}: {e}")
            return None
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Подтверждение алерта"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                alert = db.query(BankAlert).filter(BankAlert.alert_id == alert_id).first()
                
                if alert:
                    alert.status = AlertStatus.ACKNOWLEDGED.value
                    alert.acknowledged_at = datetime.now()
                    db.commit()
                    
                    logger.info(f"Alert {alert_id} acknowledged")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error acknowledging alert {alert_id}: {e}")
            return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Разрешение алерта"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                alert = db.query(BankAlert).filter(BankAlert.alert_id == alert_id).first()
                
                if alert:
                    alert.status = AlertStatus.RESOLVED.value
                    alert.resolved_at = datetime.now()
                    db.commit()
                    
                    logger.info(f"Alert {alert_id} resolved")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error resolving alert {alert_id}: {e}")
            return False
    
    def get_alert_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Получение статистики алертов"""
        try:
            from app.database import SessionLocal
            
            with SessionLocal() as db:
                since = datetime.now() - timedelta(hours=hours)
                
                # Общая статистика
                total_alerts = db.query(BankAlert).filter(BankAlert.created_at >= since).count()
                
                # По типам
                alert_types = db.query(
                    BankAlert.alert_type,
                    func.count(BankAlert.id)
                ).filter(
                    BankAlert.created_at >= since
                ).group_by(BankAlert.alert_type).all()
                
                # По банкам
                bank_alerts = db.query(
                    BankAlert.bank_code,
                    func.count(BankAlert.id)
                ).filter(
                    BankAlert.created_at >= since,
                    BankAlert.bank_code.isnot(None)
                ).group_by(BankAlert.bank_code).all()
                
                # По статусам
                status_counts = db.query(
                    BankAlert.status,
                    func.count(BankAlert.id)
                ).filter(
                    BankAlert.created_at >= since
                ).group_by(BankAlert.status).all()
                
                return {
                    "period_hours": hours,
                    "total_alerts": total_alerts,
                    "alert_types": [{"type": t[0], "count": t[1]} for t in alert_types],
                    "bank_alerts": [{"bank_code": b[0], "count": b[1]} for b in bank_alerts],
                    "status_counts": [{"status": s[0], "count": s[1]} for s in status_counts]
                }
                
        except Exception as e:
            logger.error(f"Error getting alert statistics: {e}")
            return {"error": str(e)}

# Глобальный экземпляр сервиса алертов
bank_alerts_service = BankAlertsService()
