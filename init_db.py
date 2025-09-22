#!/usr/bin/env python3
"""
Скрипт инициализации базы данных QRPayHub
Создает таблицы и (опционально) добавляет тестовые данные

Опции:
  --reset        Полное пересоздание БД (для SQLite удаляет файл, для других БД — drop всех таблиц)
  --no-seed      Не создавать тестовые данные (только структуры)
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app.database import engine, Base
from app.models.payment import (
    Bank, PaymentRequest, PaymentLog, TransactionStatus, TwoPhaseOperation,
    TransactionRecord, BillingRecord, RateLimitRecord
)
from app.models.merchant import Merchant, QRCode, MerchantPayment, MerchantSettings, TradingPoint
from app.models.admin import Admin
from app.models.audit import AuditLog
from app.models.timeline import TimelineEvent
from app.models.settings import SystemSetting

from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone, timedelta
import secrets
import hashlib
import argparse
from app.core.config import settings, get_base_url
import bcrypt

def create_tables():
    """Создание всех таблиц"""
    print("🗄️ Создание таблиц базы данных...")
    Base.metadata.create_all(bind=engine)
    print("✅ Таблицы созданы успешно!")

def reset_database():
    """Полный reset БД: для SQLite удаляет файл, для остальных — drop_all"""
    print("🧹 Сброс базы данных...")
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        try:
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"  ✅ Удален файл БД: {db_path}")
            else:
                print(f"  ℹ️ Файл БД не найден: {db_path} — продолжу")
        except Exception as e:
            print(f"  ❌ Не удалось удалить файл БД: {e}")
            print("  ↳ Попробую выполнить drop_all()")
            Base.metadata.drop_all(bind=engine)
            print("  ✅ Выполнен drop_all()")
    else:
        Base.metadata.drop_all(bind=engine)
        print("  ✅ Выполнен drop_all() для всех таблиц")

def create_test_banks(session):
    """Создание тестовых банков"""
    print("🏦 Создание тестовых банков...")
    
    banks = [
        {
            "code": "CBKG",
            "name": "Центральный Банк Кыргызской Республики",
            "bik": "440014001",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["192.168.1.100", "10.0.0.50", "172.16.0.10", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": true, "min_amount": 1.0, "max_amount": 1000000.0, "require_inn": false}'
        },
        {
            "code": "OPTIMA",
            "name": "ОАО \"Оптима Банк\"",
            "bik": "440014002",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["203.0.113.10", "203.0.113.11", "203.0.113.12", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": true, "min_amount": 10.0, "max_amount": 500000.0, "require_inn": true}'
        },
        {
            "code": "KYRGYZ",
            "name": "ОАО \"Кыргызский Банк\"",
            "bik": "440014003",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["198.51.100.20", "198.51.100.21", "198.51.100.22", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": false, "min_amount": 5.0, "max_amount": 750000.0, "require_inn": false}'
        },
        {
            "code": "DEMO",
            "name": "Демо Банк (для тестирования)",
            "bik": "999999999",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["127.0.0.1", "::1", "192.168.0.1"]',
            "validation_rules": '{"require_phone": false, "min_amount": 1.0, "max_amount": 100000.0, "require_inn": false}'
        },
        {
            "code": "BAKAI",
            "name": "ОАО \"Бакай Банк\"",
            "bik": "440014004",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["45.67.89.10", "45.67.89.11", "45.67.89.12", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": true, "min_amount": 5.0, "max_amount": 300000.0, "require_inn": true}'
        },
        {
            "code": "RSK",
            "name": "ОАО \"РСК Банк\"",
            "bik": "440014005",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["67.89.123.10", "67.89.123.11", "67.89.123.12", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": true, "min_amount": 1.0, "max_amount": 1000000.0, "require_inn": false}'
        },
        {
            "code": "KICB",
            "name": "ОАО \"КИКБ\"",
            "bik": "440014006",
            "webhook_url": f"{get_base_url()}/simulation/bank-api",
            "allowed_ips": '["89.123.45.10", "89.123.45.11", "89.123.45.12", "127.0.0.1", "::1"]',
            "validation_rules": '{"require_phone": true, "min_amount": 10.0, "max_amount": 500000.0, "require_inn": true}'
        }
    ]
    
    created_banks = []
    for bank_data in banks:
        bank = Bank(
            code=bank_data["code"],
            name=bank_data["name"],
            bik=bank_data["bik"],
            access_token=f"{bank_data['code'].lower()}_" + secrets.token_urlsafe(32),
            hmac_secret=secrets.token_urlsafe(32),
            webhook_url=bank_data["webhook_url"],
            allowed_ips=bank_data["allowed_ips"],
            validation_rules=bank_data["validation_rules"],
            is_active=True
        )
        session.add(bank)
        created_banks.append(bank)
        print(f"  ✅ {bank.name} ({bank.code})")
        print(f"     Token: {bank.access_token[:20]}...")
    
    session.commit()
    print("🏦 Банки созданы успешно!")
    return created_banks

def create_test_merchants(session):
    """Создание тестовых продавцов"""
    print("🏪 Создание тестовых продавцов...")
    
    default_password = "merchant123"
    salt = bcrypt.gensalt()
    default_hashed_password = bcrypt.hashpw(default_password.encode("utf-8"), salt).decode("utf-8")

    merchants = [
        {
            "name": "ИП Иванов Иван Иванович",
            "legal_name": "Индивидуальный предприниматель Иванов Иван Иванович",
            "inn": "16645678901234",
            "email": "ivanov@example.com",
            "phone": "+996700123456",
            "address": "г. Бишкек, ул. Чуй, д. 123, кв. 45",
            "bank_account": "1234567890123456",
            "bank_name": "ОАО \"Оптима Банк\"",
            "bank_bik": "123456789",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ООО \"Тест Компани\"",
            "legal_name": "Общество с ограниченной ответственностью \"Тест Компани\"",
            "inn": "12345678901234",
            "kpp": "123456789",
            "email": "company@example.com",
            "phone": "+996700654321",
            "address": "г. Бишкек, ул. Советская, д. 10, офис 15",
            "bank_account": "9876543210987654",
            "bank_name": "ОАО \"Кыргызский Банк\"",
            "bank_bik": "987654321",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Петрова Анна Сергеевна",
            "legal_name": "Индивидуальный предприниматель Петрова Анна Сергеевна",
            "inn": "23456789012345",
            "email": "petrova@example.com",
            "phone": "+996700111222",
            "address": "г. Ош, ул. Ленина, д. 45, кв. 12",
            "bank_account": "1111222233334444",
            "bank_name": "ОАО \"Бакай Банк\"",
            "bank_bik": "111222333",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ООО \"Современные Технологии\"",
            "legal_name": "Общество с ограниченной ответственностью \"Современные Технологии\"",
            "inn": "3456789012",
            "kpp": "345678901",
            "email": "tech@example.com",
            "phone": "+996700333444",
            "address": "г. Бишкек, ул. Токтогула, д. 78, офис 23",
            "bank_account": "3333444455556666",
            "bank_name": "ОАО \"РСК Банк\"",
            "bank_bik": "333444555",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Сидоров Михаил Петрович",
            "legal_name": "Индивидуальный предприниматель Сидоров Михаил Петрович",
            "inn": "456789012345",
            "email": "sidorov@example.com",
            "phone": "+996700555666",
            "address": "г. Бишкек, ул. Московская, д. 156, кв. 8",
            "bank_account": "5555666677778888",
            "bank_name": "ОАО \"КИКБ\"",
            "bank_bik": "555666777",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ООО \"Экспресс Доставка\"",
            "legal_name": "Общество с ограниченной ответственностью \"Экспресс Доставка\"",
            "inn": "5678901234",
            "kpp": "567890123",
            "email": "delivery@example.com",
            "phone": "+996700777888",
            "address": "г. Бишкек, ул. Манаса, д. 34, офис 7",
            "bank_account": "7777888899990000",
            "bank_name": "ОАО \"Оптима Банк\"",
            "bank_bik": "777888999",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Козлова Елена Владимировна",
            "legal_name": "Индивидуальный предприниматель Козлова Елена Владимировна",
            "inn": "678901234567",
            "email": "kozlova@example.com",
            "phone": "+996700999000",
            "address": "г. Бишкек, ул. Ахунбаева, д. 89, кв. 34",
            "bank_account": "9999000011112222",
            "bank_name": "ОАО \"Кыргызский Банк\"",
            "bank_bik": "999000111",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ООО \"Здоровое Питание\"",
            "legal_name": "Общество с ограниченной ответственностью \"Здоровое Питание\"",
            "inn": "7890123456",
            "kpp": "789012345",
            "email": "healthy@example.com",
            "phone": "+996700222333",
            "address": "г. Бишкек, ул. Ибраимова, д. 67, офис 12",
            "bank_account": "2222333344445555",
            "bank_name": "ОАО \"Бакай Банк\"",
            "bank_bik": "222333444",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Морозов Дмитрий Александрович",
            "legal_name": "Индивидуальный предприниматель Морозов Дмитрий Александрович",
            "inn": "890123456789",
            "email": "morozov@example.com",
            "phone": "+996700444555",
            "address": "г. Бишкек, ул. Киевская, д. 23, кв. 56",
            "bank_account": "4444555566667777",
            "bank_name": "ОАО \"РСК Банк\"",
            "bank_bik": "444555666",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ООО \"Авто Сервис\"",
            "legal_name": "Общество с ограниченной ответственностью \"Авто Сервис\"",
            "inn": "9012345678",
            "kpp": "901234567",
            "email": "autoservice@example.com",
            "phone": "+996700666777",
            "address": "г. Бишкек, ул. Байтик Баатыра, д. 45, офис 3",
            "bank_account": "6666777788889999",
            "bank_name": "ОАО \"КИКБ\"",
            "bank_bik": "666777888",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": default_hashed_password,
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Админ Админович",
            "legal_name": "Индивидуальный предприниматель Админ Админович",
            "inn": "000000000000",
            "email": "admin@gmail.com",
            "phone": "+996700000000",
            "address": "г. Бишкек, ул. Админская, д. 1, кв. 1",
            "bank_account": "0000000000000000",
            "bank_name": "ОАО \"Демо Банк\"",
            "bank_bik": "000000000",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Тест Пользователь 1",
            "legal_name": "Индивидуальный предприниматель Тест Пользователь 1",
            "inn": "111111111111",
            "email": "test1@example.com",
            "phone": "+996700111111",
            "address": "г. Бишкек, ул. Тестовая, д. 1, кв. 1",
            "bank_account": "1111111111111111",
            "bank_name": "ОАО \"Демо Банк\"",
            "bank_bik": "111111111",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": bcrypt.hashpw("test123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        },
        {
            "name": "ИП Тест Пользователь 2",
            "legal_name": "Индивидуальный предприниматель Тест Пользователь 2",
            "inn": "222222222222",
            "email": "test2@example.com",
            "phone": "+996700222222",
            "address": "г. Бишкек, ул. Тестовая, д. 2, кв. 2",
            "bank_account": "2222222222222222",
            "bank_name": "ОАО \"Демо Банк\"",
            "bank_bik": "222222222",
            "api_key": "merchant_" + secrets.token_urlsafe(32),
            "api_secret": secrets.token_urlsafe(32),
            "hashed_password": bcrypt.hashpw("test456".encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
            "is_verified": True,
            "verification_date": datetime.now(timezone.utc)
        }
    ]
    
    created_merchants = []
    for merchant_data in merchants:
        merchant = Merchant(**merchant_data)
        session.add(merchant)
        created_merchants.append(merchant)
        
        # Определяем пароль для вывода
        if merchant.email == "admin@gmail.com":
            password = "admin123"
        elif merchant.email == "test1@example.com":
            password = "test123"
        elif merchant.email == "test2@example.com":
            password = "test456"
        else:
            password = default_password
            
        print(f"  ✅ {merchant.name} (email: {merchant.email}, пароль: {password})")
    
    session.commit()
    print("🏪 Продавцы созданы успешно!")
    return created_merchants

def create_test_payments(session):
    """Создание тестовых платежей с разными статусами двухфазных транзакций"""
    print("💳 Создание тестовых платежей...")
    
    # Получаем банки и продавцов
    banks = session.query(Bank).all()
    merchants = session.query(Merchant).all()
    
    now = datetime.now(timezone.utc)
    
    # Создаем больше платежей для тестирования графиков
    test_payments = []
    
    # Базовые платежи для демонстрации разных статусов
    base_payments = [
        # Обычный ожидающий платеж
        {
            "token": secrets.token_urlsafe(32),
            "payment_reference": "PAY240101001",
            "receiver_account": "1234567890123456",
            "receiver_bank_code": banks[0].code if banks else "CBKG",
            "receiver_name": "ИП Иванов И.И.",
            "description": "Оплата товаров",
            "amount": 2500.0,
            "currency": "KGS",
            "status": TransactionStatus.PENDING,
            "expires_at": now + timedelta(days=1),
            "merchant_id": merchants[0].id if merchants else None
        },
        # Завершенная двухфазная транзакция
        {
            "token": secrets.token_urlsafe(32),
            "payment_reference": "PAY240101002",
            "receiver_account": "9876543210987654",
            "receiver_bank_code": banks[1].code if len(banks) > 1 else "OPTIMA",
            "receiver_name": "ООО Тест Компани",
            "description": "Оплата услуг",
            "amount": 5000.0,
            "currency": "KGS",
            "status": TransactionStatus.COMPLETED,
            "sender_bank_code": banks[2].code if len(banks) > 2 else "KYRGYZ",
            "transaction_id": "2PC_" + secrets.token_urlsafe(16),
            "payer_phone": "+996700123456",
            "paid_amount": 5000.0,
            "is_paid": True,
            "paid_at": now - timedelta(hours=2),
            "prepare_started_at": now - timedelta(hours=2, minutes=5),
            "prepare_completed_at": now - timedelta(hours=2, minutes=4),
            "commit_started_at": now - timedelta(hours=2, minutes=3),
            "commit_completed_at": now - timedelta(hours=2),
            "expires_at": now + timedelta(days=1),
            "merchant_id": merchants[1].id if len(merchants) > 1 else None,
            "sender_prepare_result": '{"status": "prepared", "reserved_amount": 5000.0, "reservation_id": "RES123"}',
            "receiver_prepare_result": '{"status": "prepared", "message": "Ready to receive"}',
            "two_phase_metadata": '{"timeout_seconds": 300, "started_at": "' + (now - timedelta(hours=2, minutes=5)).isoformat() + '"}'
        },
        # Отмененная транзакция
        {
            "token": secrets.token_urlsafe(32),
            "payment_reference": "PAY240101003",
            "receiver_account": "5555666677778888",
            "receiver_bank_code": banks[0].code if banks else "CBKG",
            "receiver_name": "ИП Петров П.П.",
            "description": "Отмененный платеж",
            "amount": 1500.0,
            "currency": "KGS",
            "status": TransactionStatus.ABORTED,
            "sender_bank_code": banks[1].code if len(banks) > 1 else "OPTIMA",
            "transaction_id": "2PC_" + secrets.token_urlsafe(16),
            "payer_phone": "+996700654321",
            "prepare_started_at": now - timedelta(hours=1, minutes=10),
            "prepare_completed_at": now - timedelta(hours=1, minutes=9),
            "abort_started_at": now - timedelta(hours=1, minutes=8),
            "abort_completed_at": now - timedelta(hours=1, minutes=7),
            "expires_at": now + timedelta(days=1),
            "sender_prepare_result": '{"status": "prepared", "reserved_amount": 1500.0, "reservation_id": "RES456"}',
            "receiver_prepare_result": '{"status": "aborted", "error_code": "ACCOUNT_BLOCKED", "error_details": {"reason": "Account temporarily blocked"}}',
            "two_phase_metadata": '{"abort_reason": "Receiver bank rejected transaction", "timeout_seconds": 300}'
        },
        # Транзакция в процессе подготовки
        {
            "token": secrets.token_urlsafe(32),
            "payment_reference": "PAY240101004",
            "receiver_account": "1111222233334444",
            "receiver_bank_code": banks[2].code if len(banks) > 2 else "KYRGYZ",
            "receiver_name": "ООО \"Быстрые Покупки\"",
            "description": "Платеж в процессе обработки",
            "amount": 3750.0,
            "currency": "KGS",
            "status": TransactionStatus.PREPARING,
            "sender_bank_code": banks[0].code if banks else "CBKG",
            "transaction_id": "2PC_" + secrets.token_urlsafe(16),
            "payer_phone": "+996700987654",
            "prepare_started_at": now - timedelta(minutes=2),
            "expires_at": now + timedelta(days=1),
            "two_phase_metadata": '{"timeout_seconds": 300, "started_at": "' + (now - timedelta(minutes=2)).isoformat() + '"}'
        }
    ]
    
    test_payments.extend(base_payments)
    
    # Создаем дополнительные завершенные платежи для тестирования графиков
    print("  📊 Создание дополнительных завершенных платежей для графиков...")
    
    for i in range(50):  # 50 дополнительных завершенных платежей
        # Распределяем по времени за последние 24 часа
        hours_ago = i % 24
        minutes_ago = (i * 7) % 60  # Разные минуты для разнообразия
        
        payment_time = now - timedelta(hours=hours_ago, minutes=minutes_ago)
        
        # Выбираем случайные банки и продавцов
        bank = banks[i % len(banks)] if banks else None
        merchant = merchants[i % len(merchants)] if merchants else None
        
        # Разные суммы для разнообразия
        amount = round(100.0 + (i * 50) + (i % 10) * 25, 2)
        
        payment_data = {
            "token": secrets.token_urlsafe(32),
            "payment_reference": f"PAY240101{100 + i:03d}",
            "receiver_account": f"{1000000000000000 + i}",
            "receiver_bank_code": bank.code if bank else "DEMO",
            "receiver_name": f"Получатель {i + 1}",
            "description": f"Платеж #{i + 1}",
            "amount": amount,
            "currency": "KGS",
            "status": TransactionStatus.COMPLETED,
            "sender_bank_code": banks[(i + 1) % len(banks)].code if len(banks) > 1 else "DEMO",
            "transaction_id": f"2PC_{secrets.token_urlsafe(16)}",
            "payer_phone": f"+996700{100000 + i}",
            "paid_amount": amount,
            "is_paid": True,
            "paid_at": payment_time,
            "prepare_started_at": payment_time - timedelta(minutes=2),
            "prepare_completed_at": payment_time - timedelta(minutes=1, seconds=30),
            "commit_started_at": payment_time - timedelta(minutes=1),
            "commit_completed_at": payment_time,
            "expires_at": payment_time + timedelta(days=1),
            "merchant_id": merchant.id if merchant else None,
            "sender_prepare_result": f'{{"status": "prepared", "reserved_amount": {amount}, "reservation_id": "RES{i:03d}"}}',
            "receiver_prepare_result": '{"status": "prepared", "message": "Ready to receive"}',
            "two_phase_metadata": f'{{"timeout_seconds": 300, "started_at": "{(payment_time - timedelta(minutes=2)).isoformat()}"}}'
        }
        
        test_payments.append(payment_data)
    
    print(f"  ✅ Создано {len(test_payments)} платежей (включая {len(base_payments)} базовых и {len(test_payments) - len(base_payments)} дополнительных)")
    
    created_payments = []
    for payment_data in test_payments:
        payment = PaymentRequest(**payment_data)
        session.add(payment)
        created_payments.append(payment)
        print(f"  ✅ Платеж {payment.payment_reference} - {payment.amount} {payment.currency} ({payment.status.value})")
    
    session.commit()
    print("💳 Платежи созданы успешно!")
    
    # Создаем 10 специальных платежей для админа (admin@gmail.com)
    print("  👤 Создание 10 платежей для админа...")
    admin_merchant = session.query(Merchant).filter(Merchant.email == "admin@gmail.com").first()
    
    if admin_merchant:
        admin_payments = []
        for i in range(10):
            # Разные суммы для разнообразия
            amount = round(500.0 + (i * 200) + (i % 5) * 100, 2)
            payment_time = now - timedelta(hours=i * 2, minutes=i * 15)
            
            payment_data = {
                "token": secrets.token_urlsafe(32),
                "payment_reference": f"ADMIN{i+1:03d}",
                "receiver_account": admin_merchant.bank_account,
                "receiver_bank_code": "DEMO",  # Используем демо банк
                "receiver_name": admin_merchant.name,
                "description": f"Платеж админа #{i + 1}",
                "amount": amount,
                "currency": "KGS",
                "status": TransactionStatus.COMPLETED,
                "sender_bank_code": "CBKG",
                "transaction_id": f"2PC_ADMIN_{secrets.token_urlsafe(16)}",
                "payer_phone": f"+996700{100000 + i}",
                "paid_amount": amount,
                "is_paid": True,
                "paid_at": payment_time,
                "prepare_started_at": payment_time - timedelta(minutes=2),
                "prepare_completed_at": payment_time - timedelta(minutes=1, seconds=30),
                "commit_started_at": payment_time - timedelta(minutes=1),
                "commit_completed_at": payment_time,
                "expires_at": payment_time + timedelta(days=1),
                "merchant_id": admin_merchant.id,
                "sender_prepare_result": f'{{"status": "prepared", "reserved_amount": {amount}, "reservation_id": "ADMIN_RES{i:03d}"}}',
                "receiver_prepare_result": '{"status": "prepared", "message": "Ready to receive"}',
                "two_phase_metadata": f'{{"timeout_seconds": 300, "started_at": "{(payment_time - timedelta(minutes=2)).isoformat()}"}}'
            }
            
            payment = PaymentRequest(**payment_data)
            session.add(payment)
            admin_payments.append(payment)
            print(f"  ✅ Платеж админа {payment.payment_reference} - {payment.amount} {payment.currency}")
        
        session.commit()
        print(f"  👤 Создано {len(admin_payments)} платежей для админа")
    else:
        print("  ⚠️ Админ не найден, платежи не созданы")
    
    return created_payments

def create_test_merchant_qr_codes(session):
    """Создание тестовых QR-кодов для продавцов"""
    print("📱 Создание тестовых QR-кодов для продавцов...")
    
    merchants = session.query(Merchant).all()
    
    if not merchants:
        print("⚠️ Нет продавцов для создания QR-кодов")
        return []
    
    qr_codes = []
    for merchant in merchants:
        # Пропускаем новых тестовых пользователей
        if merchant.email in ["test1@example.com", "test2@example.com"]:
            print(f"  ⏭️ Пропускаем QR-коды для {merchant.name} (тестовый пользователь)")
            continue
            
        # Создаем несколько QR-кодов для каждого продавца
        for i in range(3):
            qr_code = QRCode(
                merchant_id=merchant.id,
                name=f"QR-код {i+1} - {merchant.name}",
                description=f"Тестовый QR-код для {merchant.name}",
                amount=1000.0 + (i * 500),
                currency="KGS",
                qr_token=secrets.token_urlsafe(32),
                qr_url=f"{settings.BASE_URL}/pay?token={secrets.token_urlsafe(32)}",
                expires_at=datetime.now(timezone.utc).replace(tzinfo=timezone.utc) + timedelta(days=30),
                max_uses=1,  # Одноразовые QR-коды
                current_uses=0,  # Еще не использованы
                is_active=True
            )
            session.add(qr_code)
            qr_codes.append(qr_code)
            print(f"  ✅ QR-код для {merchant.name} - {qr_code.amount} {qr_code.currency}")
    
    session.commit()
    print("📱 QR-коды созданы успешно!")
    
    # Создаем дополнительные QR-коды для админа
    print("  👤 Создание QR-кодов для админа...")
    admin_merchant = session.query(Merchant).filter(Merchant.email == "admin@gmail.com").first()
    
    if admin_merchant:
        admin_qr_codes = []
        for i in range(5):  # 5 QR-кодов для админа
            qr_code = QRCode(
                merchant_id=admin_merchant.id,
                name=f"QR-код админа {i+1}",
                description=f"Специальный QR-код для админа #{i + 1}",
                amount=1000.0 + (i * 500),
                currency="KGS",
                qr_token=secrets.token_urlsafe(32),
                qr_url=f"{settings.BASE_URL}/pay?token={secrets.token_urlsafe(32)}",
                expires_at=datetime.now(timezone.utc).replace(tzinfo=timezone.utc) + timedelta(days=30),
                max_uses=1,  # Одноразовые QR-коды
                current_uses=0,  # Еще не использованы
                is_active=True
            )
            session.add(qr_code)
            admin_qr_codes.append(qr_code)
            print(f"  ✅ QR-код админа #{i+1} - {qr_code.amount} {qr_code.currency}")
        
        session.commit()
        print(f"  👤 Создано {len(admin_qr_codes)} QR-кодов для админа")
    else:
        print("  ⚠️ Админ не найден, QR-коды не созданы")
    
    return qr_codes

def create_test_merchant_payments(session):
    """Создание тестовых платежей продавцов"""
    print("💰 Создание тестовых платежей продавцов...")
    
    merchants = session.query(Merchant).all()
    qr_codes = session.query(QRCode).all()
    banks = session.query(Bank).all()
    
    if not merchants:
        print("⚠️ Нет продавцов для создания платежей")
        return []
    
    merchant_payments = []
    now = datetime.now(timezone.utc)
    
    # Создаем платежи для каждого продавца
    for merchant in merchants:
        # Пропускаем новых тестовых пользователей
        if merchant.email in ["test1@example.com", "test2@example.com"]:
            print(f"  ⏭️ Пропускаем платежи для {merchant.name} (тестовый пользователь)")
            continue
            
        print(f"  📊 Создание платежей для {merchant.name}...")
        
        # Создаем 10 платежей для каждого продавца
        for i in range(10):
            # Распределяем платежи по времени за последние 7 дней
            if i < 3:  # Платежи за сегодня
                payment_time = now - timedelta(hours=i*3)
            elif i < 6:  # Платежи за вчера  
                payment_time = now - timedelta(days=1, hours=(i-3)*4)
            elif i < 8:  # Платежи за позавчера
                payment_time = now - timedelta(days=2, hours=(i-6)*5)
            else:  # Платежи за 3 дня назад
                payment_time = now - timedelta(days=3, hours=(i-8)*6)
            
            # 80% успешных платежей (8 из 10)
            is_successful = i < 8  # Первые 8 платежей успешные
            
            # Выбираем случайный банк
            bank = banks[i % len(banks)] if banks else None
            
            payment = MerchantPayment(
                merchant_id=merchant.id,
                qr_code_id=qr_codes[i % len(qr_codes)].id if qr_codes else None,
                outlet_id=None,
                amount=round(100.0 + (i * 150) + (merchant.id * 50), 2),  # Разные суммы
                currency="KGS",
                status="completed" if is_successful else "failed",
                payer_phone=f"+996700{123456 + (merchant.id * 10) + i}",
                payer_bank_code=bank.code if bank else "DEMO",
                transaction_id=f"TX{merchant.id:03d}{i+1:03d}",
                paid_at=payment_time if is_successful else None,
                created_at=payment_time
            )
            session.add(payment)
            merchant_payments.append(payment)
            
            status_emoji = "✅" if is_successful else "❌"
            print(f"    {status_emoji} Платеж {payment.transaction_id} - {payment.amount} {payment.currency} ({payment.status})")
    
    session.commit()
    print(f"💰 Создано {len(merchant_payments)} платежей продавцов!")
    print(f"   ✅ Успешных: {len([p for p in merchant_payments if p.status == 'completed'])}")
    print(f"   ❌ Неудачных: {len([p for p in merchant_payments if p.status == 'failed'])}")
    return merchant_payments

def create_test_merchant_settings(session):
    """Создание тестовых настроек для продавцов"""
    print("⚙️ Создание тестовых настроек для продавцов...")
    
    merchants = session.query(Merchant).all()
    
    if not merchants:
        print("⚠️ Нет продавцов для создания настроек")
        return []
    
    settings = []
    for merchant in merchants:
        # Пропускаем новых тестовых пользователей
        if merchant.email in ["test1@example.com", "test2@example.com"]:
            print(f"  ⏭️ Пропускаем настройки для {merchant.name} (тестовый пользователь)")
            continue
            
        setting = MerchantSettings(
            merchant_id=merchant.id,
            email_notifications=True,
            sms_notifications=False,
            webhook_url="https://example.com/webhook",
            qr_code_expiry_hours=720,  # 30 дней * 24 часа
            auto_generate_qr_images=True,
            daily_reports=False,
            weekly_reports=True,
            monthly_reports=True,
            require_webhook_signature=True
        )
        session.add(setting)
        settings.append(setting)
        print(f"  ✅ Настройки для {merchant.name}")
    
    session.commit()
    print("⚙️ Настройки созданы успешно!")
    return settings

def create_test_admins(session):
    """Создание тестовых администраторов"""
    print("👨‍💼 Создание тестовых администраторов...")
    
    admins = [
        {
            "username": "admin",
            "email": "admin@qrpayhub.com",
            "full_name": "Главный Администратор",
            "role": "super_admin"
        },
        {
            "username": "manager",
            "email": "manager@qrpayhub.com",
            "full_name": "Менеджер Системы",
            "role": "admin"
        },
        {
            "username": "support",
            "email": "support@qrpayhub.com",
            "full_name": "Специалист Поддержки",
            "role": "admin"
        }
    ]
    
    created_admins = []
    for admin_data in admins:
        admin = Admin(
            username=admin_data["username"],
            email=admin_data["email"],
            full_name=admin_data["full_name"],
            role=admin_data["role"]
        )
        # Устанавливаем пароль (в продакшене использовать более сложные пароли)
        admin.set_password("admin123")
        
        # Для первого админа добавляем полный профиль с банковскими реквизитами
        if admin_data["username"] == "admin":
            admin.phone = "+996700111222"
            admin.organization_name = "QRPayHub Администрация"
            admin.inn = "12345678901234"
            admin.bank_account = "1234567890123456789"
            admin.bank_name = "Оптима Банк"
            admin.bank_bik = "123456"
            admin.bank_code = "OPTIMA"
            admin.address = "г. Бишкек, ул. Чуй, 123"
            admin.qr_settings = {
                "default_currency": "KGS",
                "default_expires_hours": 24,
                "allow_variable_amount": True,
                "max_amount": 100000.0
            }
            print(f"  ✅ {admin.full_name} ({admin.username}) - пароль: admin123 [С ПРОФИЛЕМ]")
        else:
            print(f"  ✅ {admin.full_name} ({admin.username}) - пароль: admin123")
        
        session.add(admin)
        created_admins.append(admin)
    
    session.commit()
    print("👨‍💼 Администраторы созданы успешно!")
    return created_admins



def create_two_phase_operations(session):
    """Создание тестовых логов двухфазных операций"""
    print("🔄 Создание логов двухфазных операций...")
    
    # Получаем завершенные платежи
    completed_payments = session.query(PaymentRequest).filter(
        PaymentRequest.status == TransactionStatus.COMPLETED
    ).all()
    
    aborted_payments = session.query(PaymentRequest).filter(
        PaymentRequest.status == TransactionStatus.ABORTED
    ).all()
    
    now = datetime.now(timezone.utc)
    
    operations = []
    
    # Логи для завершенных транзакций
    for payment in completed_payments:
        if payment.transaction_id:
            # Prepare операции
            for bank_role, bank_code in [("sender", payment.sender_bank_code), ("receiver", payment.receiver_bank_code)]:
                if bank_code:
                    # Request
                    op_request = TwoPhaseOperation(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        phase="prepare",
                        operation_type="request",
                        bank_code=bank_code,
                        bank_role=bank_role,
                        request_data='{"transaction_id": "' + payment.transaction_id + '", "amount": ' + str(payment.amount) + ', "bank_role": "' + bank_role + '"}',
                        response_data='{"status": "prepared", "reservation_id": "RES' + secrets.token_hex(4) + '"}',
                        response_status="prepared",
                        started_at=payment.prepare_started_at or (now - timedelta(hours=2, minutes=5)),
                        completed_at=payment.prepare_completed_at or (now - timedelta(hours=2, minutes=4)),
                        duration_ms=60000
                    )
                    operations.append(op_request)
                    
                    # Commit операции
                    op_commit = TwoPhaseOperation(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        phase="commit",
                        operation_type="request",
                        bank_code=bank_code,
                        bank_role=bank_role,
                        request_data='{"transaction_id": "' + payment.transaction_id + '", "bank_role": "' + bank_role + '"}',
                        response_data='{"status": "committed", "actual_amount": ' + str(payment.paid_amount or payment.amount) + '}',
                        response_status="committed",
                        started_at=payment.commit_started_at or (now - timedelta(hours=2, minutes=3)),
                        completed_at=payment.commit_completed_at or (now - timedelta(hours=2)),
                        duration_ms=45000
                    )
                    operations.append(op_commit)
    
    # Логи для отмененных транзакций
    for payment in aborted_payments:
        if payment.transaction_id:
            # Prepare и Abort операции
            for bank_role, bank_code in [("sender", payment.sender_bank_code), ("receiver", payment.receiver_bank_code)]:
                if bank_code:
                    # Prepare request
                    op_prepare = TwoPhaseOperation(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        phase="prepare",
                        operation_type="request",
                        bank_code=bank_code,
                        bank_role=bank_role,
                        request_data='{"transaction_id": "' + payment.transaction_id + '", "amount": ' + str(payment.amount) + ', "bank_role": "' + bank_role + '"}',
                        response_data='{"status": "aborted" if bank_role == "receiver" else "prepared", "error_code": "ACCOUNT_BLOCKED"}' if bank_role == "receiver" else '{"status": "prepared", "reservation_id": "RES' + secrets.token_hex(4) + '"}',
                        response_status="aborted" if bank_role == "receiver" else "prepared",
                        started_at=payment.prepare_started_at or (now - timedelta(hours=1, minutes=10)),
                        completed_at=payment.prepare_completed_at or (now - timedelta(hours=1, minutes=9)),
                        duration_ms=30000,
                        error_message="Account blocked" if bank_role == "receiver" else None
                    )
                    operations.append(op_prepare)
                    
                    # Abort операции
                    op_abort = TwoPhaseOperation(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        phase="abort",
                        operation_type="request",
                        bank_code=bank_code,
                        bank_role=bank_role,
                        request_data='{"transaction_id": "' + payment.transaction_id + '", "abort_reason": "Transaction preparation failed"}',
                        response_data='{"status": "aborted", "released_amount": ' + str(payment.amount) + '}',
                        response_status="aborted",
                        started_at=payment.abort_started_at or (now - timedelta(hours=1, minutes=8)),
                        completed_at=payment.abort_completed_at or (now - timedelta(hours=1, minutes=7)),
                        duration_ms=15000
                    )
                    operations.append(op_abort)
    
    # Добавляем все операции в сессию
    for operation in operations:
        session.add(operation)
        
    session.commit()
    print(f"🔄 Создано {len(operations)} логов двухфазных операций!")
    return operations

def create_system_settings(session):
    """Создание системных настроек"""
    print("⚙️ Создание системных настроек...")
    
    # Получаем базовый домен для настроек
    try:
        base_url = get_base_url()
        if base_url:
            base_domain = base_url.replace("https://", "").replace("http://", "")
        else:
            base_domain = "localhost:8000"  # Fallback для относительных путей
    except Exception:
        base_domain = "localhost:8000"  # Fallback
    
    settings = [
        {
            "key": "qr_security",
            "value_json": f'{{"max_qr_lifetime_minutes": 60, "min_qr_lifetime_minutes": 5, "allowed_domains": ["localhost:8000", "qrpayhub.local", "{base_domain}"], "default_expires_minutes": 10}}'
        },
        {
            "key": "two_phase_config",
            "value_json": '{"prepare_timeout": 300, "commit_timeout": 180, "abort_timeout": 120, "max_recovery_attempts": 3, "check_interval": 60}'
        },
        {
            "key": "monitoring_config",
            "value_json": '{"alert_thresholds": {"error_rate": 0.1, "response_time": 5000}, "retention_days": 30, "enable_realtime": true}'
        },
        {
            "key": "payment_limits",
            "value_json": '{"min_amount": 1.0, "max_amount": 1000000.0, "daily_limit": 5000000.0, "currency": "KGS"}'
        }
    ]
    
    for setting_data in settings:
        setting = SystemSetting(**setting_data)
        session.add(setting)
        print(f"  ✅ Настройка: {setting.key}")
    
    session.commit()
    print("⚙️ Системные настройки созданы!")

def create_trading_points(session):
    """Создание торговых точек"""
    print("🏪 Создание торговых точек...")
    
    merchants = session.query(Merchant).all()
    
    if not merchants:
        print("⚠️ Нет продавцов для создания торговых точек")
        return []
    
    trading_points = []
    for merchant in merchants:
        # Пропускаем новых тестовых пользователей
        if merchant.email in ["test1@example.com", "test2@example.com"]:
            print(f"  ⏭️ Пропускаем торговые точки для {merchant.name} (тестовый пользователь)")
            continue
            
        # Создаем несколько торговых точек для каждого продавца
        for i in range(2):
            point = TradingPoint(
                merchant_id=merchant.id,
                name=f"Точка {i+1} - {merchant.name}",
                address=f"г. Бишкек, ул. Торговая, д. {i+1}0",
                description=f"Тестовая торговая точка {i+1} для {merchant.name}",
                status="ACTIVE"
            )
            session.add(point)
            trading_points.append(point)
            print(f"  ✅ Торговая точка: {point.name}")
    
    session.commit()
    print("🏪 Торговые точки созданы!")
    return trading_points

def create_sample_timeline_events(session):
    """Создание примеров событий таймлайна"""
    print("📅 Создание событий таймлайна...")
    
    # Получаем платежи для которых создадим события
    payments = session.query(PaymentRequest).limit(3).all()
    now = datetime.now(timezone.utc)
    
    events = []
    for i, payment in enumerate(payments):
        # Создание QR
        event1 = TimelineEvent(
            payment_token=payment.token,
            event_type='qr_created',
            title='QR-код создан',
            description=f'Создан QR-код для платежа {payment.payment_reference}',
            actor='merchant',
            source='api',
            status='success',
            timestamp_utc=payment.created_at,
            metadata_json='{"amount": ' + str(payment.amount) + ', "currency": "' + payment.currency + '"}'
        )
        events.append(event1)
        
        # Запрос информации (если не в PENDING)
        if payment.status != TransactionStatus.PENDING:
            event2 = TimelineEvent(
                payment_token=payment.token,
                event_type='info_requested',
                title='Банк запросил информацию',
                description=f'Банк {payment.receiver_bank_code} запросил данные платежа',
                actor='bank',
                source='api',
                status='info',
                timestamp_utc=payment.created_at + timedelta(minutes=5 + i),
                metadata_json='{"bank_code": "' + payment.receiver_bank_code + '"}'
            )
            events.append(event2)
        
        # Если транзакция завершена или отменена
        if payment.status in [TransactionStatus.COMPLETED, TransactionStatus.ABORTED]:
            if payment.transaction_id:
                event3 = TimelineEvent(
                    payment_token=payment.token,
                    transaction_id=payment.transaction_id,
                    event_type='two_phase_started',
                    title='Двухфазная транзакция запущена',
                    description=f'Начата обработка транзакции {payment.transaction_id}',
                    actor='system',
                    source='two_phase_commit',
                    status='info',
                    timestamp_utc=payment.prepare_started_at or (payment.created_at + timedelta(minutes=10 + i))
                )
                events.append(event3)
                
                if payment.status == TransactionStatus.COMPLETED:
                    event4 = TimelineEvent(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        event_type='transaction_completed',
                        title='Транзакция завершена',
                        description=f'Платеж на сумму {payment.paid_amount} {payment.currency} успешно обработан',
                        actor='system',
                        source='two_phase_commit',
                        status='success',
                        timestamp_utc=payment.commit_completed_at or (payment.created_at + timedelta(minutes=15 + i))
                    )
                    events.append(event4)
                elif payment.status == TransactionStatus.ABORTED:
                    event4 = TimelineEvent(
                        payment_token=payment.token,
                        transaction_id=payment.transaction_id,
                        event_type='transaction_aborted',
                        title='Транзакция отменена',
                        description=f'Транзакция {payment.transaction_id} была отменена',
                        actor='system',
                        source='two_phase_commit',
                        status='warning',
                        timestamp_utc=payment.abort_completed_at or (payment.created_at + timedelta(minutes=12 + i))
                    )
                    events.append(event4)
    
    for event in events:
        session.add(event)
    
    session.commit()
    print(f"📅 Создано {len(events)} событий таймлайна!")
    return events



def main():
    """Главная функция инициализации"""
    parser = argparse.ArgumentParser(description="Инициализация БД QRPayHub")
    parser.add_argument("--reset", action="store_true", help="Пересоздать БД (удалить/дропнуть и создать заново)")
    parser.add_argument("--no-seed", action="store_true", help="Не наполнять тестовыми данными")
    args = parser.parse_args()

    print("🚀 Инициализация базы данных QRPayHub")
    print("=" * 50)
    
    try:
        if args.reset:
            reset_database()

        # Создаем таблицы
        create_tables()
        
        # Создаем сессию
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = SessionLocal()
        
        try:
            if not args.no_seed:
                # Создаем тестовые данные в правильном порядке
                print("📦 Создание базовых данных...")
                create_test_banks(session)
                create_test_merchants(session)
                create_system_settings(session)
                create_test_admins(session)
                
                print("\n📦 Создание данных платежей...")
                create_test_payments(session)
                create_two_phase_operations(session)  # Логи двухфазных операций
                create_sample_timeline_events(session)  # События таймлайна
                
                print("\n📦 Создание данных продавцов...")
                create_trading_points(session)  # Торговые точки
                create_test_merchant_qr_codes(session)
                create_test_merchant_payments(session)
                create_test_merchant_settings(session)
                
                print("\n📦 Создание дополнительных данных...")
                # Sandbox и fallback данные удалены
            else:
                print("ℹ️ Пропускаю наполнение тестовыми данными (--no-seed)")
            
            print("\n" + "=" * 50)
            print("🎉 База данных успешно инициализирована!")
            print("\n📊 Текущие данные:")
            print(f"  🏦 Банков: {session.query(Bank).count()}")
            print(f"  🏪 Продавцов: {session.query(Merchant).count()}")
            print(f"  🏢 Торговых точек: {session.query(TradingPoint).count()}")
            print(f"  💳 Платежей (requests): {session.query(PaymentRequest).count()}")
            print(f"  📱 QR-кодов: {session.query(QRCode).count()}")
            print(f"  💰 Платежей продавцов: {session.query(MerchantPayment).count()}")
            print(f"  👨‍💼 Администраторов: {session.query(Admin).count()}")
            
            print(f"\n🔄 Двухфазные транзакции:")
            print(f"  📊 Операций двухфазного коммита: {session.query(TwoPhaseOperation).count()}")
            print(f"  📝 Записей транзакций: {session.query(TransactionRecord).count()}")
            print(f"  💸 Биллинговых записей: {session.query(BillingRecord).count()}")
            
            print(f"\n📋 Системные данные:")
            print(f"  ⚙️ Системных настроек: {session.query(SystemSetting).count()}")
            print(f"  📅 События таймлайна: {session.query(TimelineEvent).count()}")
            print(f"  📊 Логи аудита: {session.query(AuditLog).count()}")
            print(f"  📈 Записей rate limiting: {session.query(RateLimitRecord).count()}")
            
            print(f"\n🧪 Тестирование:")
            print(f"  🏦 Песочница банков: удалена")
            print(f"  🔄 Fallback сценариев: удалены")
            
            # Статистика по статусам транзакций
            print("\n📈 Статистика транзакций:")
            for status in TransactionStatus:
                count = session.query(PaymentRequest).filter(PaymentRequest.status == status).count()
                if count > 0:
                    emoji = {
                        'pending': '⏳',
                        'preparing': '🔄',
                        'prepared': '✅',
                        'committing': '💳',
                        'completed': '🎉',
                        'aborting': '🚫',
                        'aborted': '❌'
                    }.get(status.value, '📋')
                    print(f"  {emoji} {status.value}: {count}")
            
            print("\n🔑 Токены доступа банков:")
            banks = session.query(Bank).all()
            for bank in banks:
                print(f"  {bank.code}: {bank.access_token[:20]}...")
                
            print("\n🎯 Для тестирования двухфазных транзакций:")
            print("  1. Запустите сервер: uvicorn app.main:app --reload")
            print("  2. Откройте админ панель: /admin")
            print("  3. Логин: admin, пароль: admin123")
            print("  4. Посмотрите на транзакции в разных статусах")
            print("  5. Тестовый эндпоинт: POST /api/v1/payment/two-phase-payment")
            print("  6. Проверьте события в таймлайне и логи операций")
            print("  7. Тестируйте фоновый сервис восстановления")
            
            print("\n💡 Примеры статусов транзакций:")
            print("  - PENDING: Ожидает обработки")
            print("  - PREPARING: В процессе подготовки")
            print("  - COMPLETED: Успешно завершена")
            print("  - ABORTED: Отменена")
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
