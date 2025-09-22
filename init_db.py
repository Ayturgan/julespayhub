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
    Bank, PaymentLog, TransactionStatus, TwoPhaseOperation,
    TransactionRecord, BillingRecord, RateLimitRecord
)
from app.models.merchant import Merchant, MerchantSettings, TradingPoint
from app.models.admin import Admin
from app.models.unified import UnifiedPayment, UnifiedQRCode
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
    """Создание тестовых платежей с разными статусами для UnifiedPayment"""
    print("💳 Создание тестовых унифицированных платежей...")

    banks = session.query(Bank).all()
    merchants = session.query(Merchant).all()
    admins = session.query(Admin).all()
    qr_codes = session.query(UnifiedQRCode).all()

    now = datetime.now(timezone.utc)
    test_payments = []

    # Платеж от продавца (успешный)
    if merchants and banks and qr_codes:
        merchant = merchants[0]
        test_payments.append(
            UnifiedPayment(
                merchant_id=merchant.id,
                qr_code_id=qr_codes[0].id,
                amount=1500.0,
                currency="KGS",
                description="Оплата за товары от " + merchant.name,
                status=TransactionStatus.COMPLETED,
                receiver_name=merchant.name,
                receiver_account=merchant.bank_account,
                receiver_bank_code=merchant.bank_bik,
                payer_phone="+996700111222",
                payer_bank_code=banks[1].code,
                sender_account="9876543210123456",
                transaction_id="UP_M_" + secrets.token_hex(8),
                payment_reference="UP_REF_M_" + secrets.token_hex(8),
                is_paid=True,
                paid_at=now - timedelta(days=1),
                commit_completed_at=now - timedelta(days=1),
            )
        )

    # Платеж от админа (в ожидании)
    if admins and banks and qr_codes:
        admin = admins[0]
        test_payments.append(
            UnifiedPayment(
                admin_id=admin.id,
                qr_code_id=qr_codes[1].id if len(qr_codes) > 1 else None,
                amount=5000.0,
                currency="USD",
                description="Административный сбор",
                status=TransactionStatus.PENDING,
                receiver_name=admin.organization_name or admin.full_name,
                receiver_account=admin.bank_account,
                receiver_bank_code=admin.bank_code,
                payment_reference="UP_REF_A_" + secrets.token_hex(8),
                expires_at=now + timedelta(days=5),
            )
        )

    for payment_data in test_payments:
        session.add(payment_data)
        print(f"  ✅ Платеж {payment_data.payment_reference} - {payment_data.amount} {payment_data.currency} ({payment_data.status.value})")

    session.commit()
    print("💳 Унифицированные платежи созданы успешно!")
    return test_payments

def create_test_qr_codes(session):
    """Создание тестовых QR-кодов для продавцов и админов"""
    print("📱 Создание тестовых унифицированных QR-кодов...")

    merchants = session.query(Merchant).all()
    admins = session.query(Admin).all()
    qr_codes = []

    # QR-код для продавца
    if merchants:
        merchant = merchants[0]
        qr_codes.append(
            UnifiedQRCode(
                merchant_id=merchant.id,
                name=f"QR для {merchant.name}",
                description="Статический QR для магазина",
                amount=None,  # Динамический
                currency="KGS",
                qr_token="UQRC_M_" + secrets.token_hex(16),
                qr_url=f"{settings.BASE_URL}/pay?token=UQRC_M_{secrets.token_hex(16)}",
                is_active=True,
            )
        )

    # QR-код для админа
    if admins:
        admin = admins[0]
        qr_codes.append(
            UnifiedQRCode(
                admin_id=admin.id,
                name="QR для мероприятия",
                description="QR для регистрации на конференции",
                amount=2500.0,
                currency="KGS",
                qr_token="UQRC_A_" + secrets.token_hex(16),
                qr_url=f"{settings.BASE_URL}/pay?token=UQRC_A_{secrets.token_hex(16)}",
                expires_at=datetime.now(timezone.utc) + timedelta(days=10),
                max_uses=100,
                is_active=True,
            )
        )

    for qr_code_data in qr_codes:
        session.add(qr_code_data)
        owner_type = "Продавец" if qr_code_data.merchant_id else "Админ"
        print(f"  ✅ QR-код для {owner_type} - {qr_code_data.name}")

    session.commit()
    print("📱 Унифицированные QR-коды созданы успешно!")
    return qr_codes

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
    """Создание тестовых логов двухфазных операций для UnifiedPayment"""
    print("🔄 Создание логов двухфазных операций...")

    completed_payments = session.query(UnifiedPayment).filter(
        UnifiedPayment.status == TransactionStatus.COMPLETED
    ).all()

    operations = []
    for payment in completed_payments:
        if payment.transaction_id:
            # Пример лога для операции PREPARE
            op_prepare = TwoPhaseOperation(
                payment_token=payment.payment_reference,  # Используем reference как токен
                transaction_id=payment.transaction_id,
                phase="prepare",
                operation_type="request",
                bank_code=payment.payer_bank_code,
                bank_role="sender",
                request_data=f'{{"amount": {payment.amount}}}',
                response_status="prepared",
                started_at=payment.created_at,
                completed_at=payment.created_at + timedelta(seconds=10),
                duration_ms=150
            )
            operations.append(op_prepare)

            # Пример лога для операции COMMIT
            op_commit = TwoPhaseOperation(
                payment_token=payment.payment_reference,
                transaction_id=payment.transaction_id,
                phase="commit",
                operation_type="request",
                bank_code=payment.payer_bank_code,
                bank_role="sender",
                response_status="committed",
                started_at=payment.created_at + timedelta(seconds=15),
                completed_at=payment.paid_at,
                duration_ms=200
            )
            operations.append(op_commit)

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
    """Создание примеров событий таймлайна для UnifiedPayment"""
    print("📅 Создание событий таймлайна...")

    payments = session.query(UnifiedPayment).limit(2).all()
    events = []
    for payment in payments:
        event = TimelineEvent(
            payment_token=payment.payment_reference,
            transaction_id=payment.transaction_id,
            event_type='payment_created',
            title='Унифицированный платеж создан',
            description=f'Создан платеж на сумму {payment.amount} {payment.currency}',
            actor='system',
            source='init_db',
            status='success',
            timestamp_utc=payment.created_at
        )
        events.append(event)

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

        create_tables()
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = SessionLocal()

        try:
            if not args.no_seed:
                print("📦 Создание базовых данных...")
                create_test_banks(session)
                create_test_merchants(session)
                create_system_settings(session)
                create_test_admins(session)
                create_trading_points(session)
                create_test_merchant_settings(session)

                print("\n📦 Создание унифицированных данных...")
                create_test_qr_codes(session)
                create_test_payments(session)
                create_two_phase_operations(session)
                create_sample_timeline_events(session)
            else:
                print("ℹ️ Пропускаю наполнение тестовыми данными (--no-seed)")

            print("\n" + "=" * 50)
            print("🎉 База данных успешно инициализирована!")
            print("\n📊 Текущие данные:")
            print(f"  🏦 Банков: {session.query(Bank).count()}")
            print(f"  🏪 Продавцов: {session.query(Merchant).count()}")
            print(f"  👨‍💼 Администраторов: {session.query(Admin).count()}")
            print(f"  📱 Унифицированных QR-кодов: {session.query(UnifiedQRCode).count()}")
            print(f"  💳 Унифицированных Платежей: {session.query(UnifiedPayment).count()}")

            print(f"\n🔄 Двухфазные транзакции:")
            print(f"  📊 Операций двухфазного коммита: {session.query(TwoPhaseOperation).count()}")

            print(f"\n📋 Системные данные:")
            print(f"  ⚙️ Системных настроек: {session.query(SystemSetting).count()}")
            print(f"  📅 События таймлайна: {session.query(TimelineEvent).count()}")

            print("\n📈 Статистика унифицированных платежей:")
            for status in TransactionStatus:
                count = session.query(UnifiedPayment).filter(UnifiedPayment.status == status).count()
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

        finally:
            session.close()

    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
