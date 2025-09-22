import logging
import logging.handlers
import os
import json
import gzip
import shutil
from datetime import datetime, timedelta
from app.core.config import settings


class JsonFormatter(logging.Formatter):
    """JSON-форматер для структурированных логов."""

    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Общий контекст
        if hasattr(record, "request_id"):
            log_object["request_id"] = getattr(record, "request_id")
        if hasattr(record, "client_ip"):
            log_object["client_ip"] = getattr(record, "client_ip")
        if hasattr(record, "method"):
            log_object["method"] = getattr(record, "method")
        if hasattr(record, "path"):
            log_object["path"] = getattr(record, "path")
        if hasattr(record, "status_code"):
            log_object["status_code"] = getattr(record, "status_code")
        if hasattr(record, "duration_ms"):
            log_object["duration_ms"] = getattr(record, "duration_ms")
        if hasattr(record, "bank_code"):
            log_object["bank_code"] = getattr(record, "bank_code")
        if hasattr(record, "rate_limited"):
            log_object["rate_limited"] = getattr(record, "rate_limited")
        if hasattr(record, "user_agent"):
            log_object["user_agent"] = getattr(record, "user_agent")
        if hasattr(record, "query_params"):
            log_object["query_params"] = getattr(record, "query_params")
        if hasattr(record, "request_headers"):
            log_object["request_headers"] = getattr(record, "request_headers")
        if hasattr(record, "response_headers"):
            log_object["response_headers"] = getattr(record, "response_headers")
        if hasattr(record, "request_body_preview"):
            log_object["request_body_preview"] = getattr(record, "request_body_preview")
        if hasattr(record, "response_body_preview"):
            log_object["response_body_preview"] = getattr(record, "response_body_preview")
        if hasattr(record, "error_message") and getattr(record, "error_message"):
            log_object["error_message"] = getattr(record, "error_message")
        if hasattr(record, "error_code"):
            log_object["error_code"] = getattr(record, "error_code")
        if hasattr(record, "http_status"):
            log_object["http_status"] = getattr(record, "http_status")
        if hasattr(record, "severity"):
            log_object["severity"] = getattr(record, "severity")

        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_object, ensure_ascii=False)


def _ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def setup_logging():
    """Настройка структурированного многоуровневого логирования с ротацией."""
    log_dir = "logs"
    archive_dir = os.path.join(log_dir, "archive")
    _ensure_dir(log_dir)
    _ensure_dir(archive_dir)

    # Корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Очистка существующих обработчиков
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Форматеры
    console_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s')
    json_formatter = JsonFormatter()

    # Консоль (человекочитаемый) - только важные сообщения
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)  # Показываем только WARNING и выше
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Файл всех логов (ежедневная ротация)
    all_timed_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_all.jsonl"), when='midnight', backupCount=14, encoding='utf-8'
    )
    all_timed_handler.setLevel(logging.DEBUG)
    all_timed_handler.setFormatter(json_formatter)
    root_logger.addHandler(all_timed_handler)

    # Файл всех логов по размеру (дополнительно)
    all_size_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_all.size.jsonl"), maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    all_size_handler.setLevel(logging.DEBUG)
    all_size_handler.setFormatter(json_formatter)
    root_logger.addHandler(all_size_handler)

    # Файл ошибок (по размеру)
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_errors.jsonl"), maxBytes=5*1024*1024, backupCount=7, encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)
    root_logger.addHandler(error_handler)

    # API-логи (ежедневная ротация)
    api_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_api.jsonl"), when='midnight', backupCount=14, encoding='utf-8'
    )
    api_handler.setLevel(logging.INFO)
    api_handler.setFormatter(json_formatter)

    api_logger = logging.getLogger("api_requests")
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False
    for h in api_logger.handlers[:]:
        api_logger.removeHandler(h)
    api_logger.addHandler(api_handler)

    # QR операции
    qr_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_qr.jsonl"), maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
    )
    qr_handler.setLevel(logging.DEBUG)
    qr_handler.setFormatter(json_formatter)

    qr_logger = logging.getLogger("qr_operations")
    qr_logger.setLevel(logging.DEBUG)
    qr_logger.propagate = False
    for h in qr_logger.handlers[:]:
        qr_logger.removeHandler(h)
    qr_logger.addHandler(qr_handler)

    # Платежные операции
    payment_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_payments.jsonl"), maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    payment_handler.setLevel(logging.DEBUG)
    payment_handler.setFormatter(json_formatter)

    payment_logger = logging.getLogger("payment_operations")
    payment_logger.setLevel(logging.DEBUG)
    payment_logger.propagate = False
    for h in payment_logger.handlers[:]:
        payment_logger.removeHandler(h)
    payment_logger.addHandler(payment_handler)

    # Безопасность
    security_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "qrpayhub_security.jsonl"), maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    security_handler.setLevel(logging.INFO)
    security_handler.setFormatter(json_formatter)

    security_logger = logging.getLogger("security")
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False
    for h in security_logger.handlers[:]:
        security_logger.removeHandler(h)
    security_logger.addHandler(security_handler)

    # Применяем форматирование к uvicorn логгерам
    for uvicorn_logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.handlers = []
        uvicorn_logger.addHandler(all_timed_handler)
        uvicorn_logger.addHandler(all_size_handler)

    # Баннер запуска в консоли
    root_logger.warning("=" * 80)
    root_logger.warning("🚀 QRPayHub успешно запущен")
    root_logger.warning(f"📁 Логи сохраняются в: {os.path.abspath(log_dir)}")
    root_logger.warning(f"🕐 Запуск: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    root_logger.warning("=" * 80)

    # Архивация старых логов при старте
    archive_old_logs(log_dir, days=7)

    return root_logger


def archive_old_logs(log_dir: str = "logs", days: int = 7):
    """Архивация и очистка логов старше N дней в logs/archive.

    - Сжимает в .gz и удаляет исходные файлы
    - Сохраняет структуру JSONL
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        archive_dir = os.path.join(log_dir, "archive")
        _ensure_dir(archive_dir)

        for file_name in os.listdir(log_dir):
            if not (file_name.endswith(".log") or file_name.endswith(".jsonl") or ".jsonl." in file_name or ".log." in file_name or file_name.endswith(".size.jsonl")):
                continue

            file_path = os.path.join(log_dir, file_name)
            if not os.path.isfile(file_path):
                continue

            mtime = datetime.utcfromtimestamp(os.path.getmtime(file_path))
            if mtime > cutoff:
                continue

            gz_name = f"{file_name}.{mtime.strftime('%Y%m%d')}.gz"
            gz_path = os.path.join(archive_dir, gz_name)

            with open(file_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

            try:
                os.remove(file_path)
            except OSError:
                pass
    except Exception as arch_err:
        logging.getLogger(__name__).warning(f"Log archiving failed: {arch_err}")


def get_qr_logger():
    """Получить логгер для QR операций"""
    return logging.getLogger("qr_operations")


def get_api_logger():
    """Получить логгер для API запросов"""
    return logging.getLogger("api_requests")


def get_payment_logger():
    """Получить логгер для платежных операций"""
    return logging.getLogger("payment_operations")


def get_security_logger():
    """Получить логгер для операций безопасности"""
    return logging.getLogger("security")
