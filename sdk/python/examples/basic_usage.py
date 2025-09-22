#!/usr/bin/env python3
"""
QRPayHub SDK - Базовые примеры использования
"""

import os
from qrpayhub_sdk import QRPayHubClient, PaymentStatus
from qrpayhub_sdk.exceptions import (
    PaymentNotFoundError,
    AuthenticationError,
    ValidationError,
    RateLimitError
)


def main():
    # Настройка клиента
    client = QRPayHubClient(
        base_url=os.getenv('QRPAYHUB_BASE_URL', 'https://api.qrpayhub.com'),
        access_token=os.getenv('QRPAYHUB_ACCESS_TOKEN', 'your-access-token'),
        hmac_secret=os.getenv('QRPAYHUB_HMAC_SECRET', 'your-hmac-secret'),
        user_agent='MyBank-Backend/1.0.0'
    )
    
    # Пример 1: Получение информации о платеже
    print("=== Пример 1: Получение информации о платеже ===")
    
    try:
        # Токен из QR-кода (в реальности получается от сканирования)
        qr_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
        
        payment_info = client.get_payment_info(
            token=qr_token,
            device_id="mobile-device-12345",
            app_version="1.0.0"
        )
        
        print(f"✅ Платеж найден:")
        print(f"   Получатель: {payment_info.receiver_name}")
        print(f"   Счет: {payment_info.receiver_account}")
        print(f"   Банк: {payment_info.receiver_bank_code}")
        print(f"   Сумма: {payment_info.amount} {payment_info.currency}")
        print(f"   Описание: {payment_info.description}")
        print(f"   Референс: {payment_info.payment_reference}")
        
    except PaymentNotFoundError as e:
        print(f"❌ Платеж не найден: {e.user_message}")
    except AuthenticationError as e:
        print(f"❌ Ошибка аутентификации: {e.user_message}")
    except ValidationError as e:
        print(f"❌ Ошибка валидации: {e.user_message}")
    except RateLimitError as e:
        print(f"❌ Превышен лимит запросов: {e.user_message}")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    
    print()
    
    # Пример 2: Отправка успешного webhook
    print("=== Пример 2: Отправка успешного webhook ===")
    
    try:
        result = client.send_payment_status(
            token=qr_token,
            status=PaymentStatus.SUCCESS,
            transaction_id="TXN240101123456",
            amount=2500.00,
            payer_phone="+996555123456",
            currency="KGS",
            fee_amount=25.00,
            processing_time_ms=1250
        )
        
        print(f"✅ Webhook отправлен успешно:")
        print(f"   Статус: {result['status']}")
        print(f"   Сообщение: {result['message']}")
        print(f"   Обработано в: {result.get('processed_at', 'N/A')}")
        
    except ValidationError as e:
        print(f"❌ Ошибка валидации webhook: {e.user_message}")
    except AuthenticationError as e:
        print(f"❌ Ошибка аутентификации webhook: {e.user_message}")
    except Exception as e:
        print(f"❌ Ошибка отправки webhook: {e}")
    
    print()
    
    # Пример 3: Отправка неуспешного webhook
    print("=== Пример 3: Отправка неуспешного webhook ===")
    
    try:
        result = client.send_payment_status(
            token=qr_token,
            status=PaymentStatus.FAILED,
            transaction_id="TXN240101123457",
            amount=0,  # При неуспешном платеже сумма обычно 0
            payer_phone="+996555123456",
            currency="KGS",
            error_code="INSUFFICIENT_FUNDS",
            error_message="Недостаточно средств на счете"
        )
        
        print(f"✅ Webhook о неуспешном платеже отправлен:")
        print(f"   Статус: {result['status']}")
        print(f"   Сообщение: {result['message']}")
        
    except Exception as e:
        print(f"❌ Ошибка отправки webhook: {e}")
    
    print()
    
    # Пример 4: Обработка различных ошибок
    print("=== Пример 4: Обработка различных ошибок ===")
    
    # Неверный токен
    try:
        client.get_payment_info("invalid-token")
    except PaymentNotFoundError:
        print("✅ Правильно обработана ошибка 'платеж не найден'")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    
    # Неверный статус в webhook
    try:
        client.send_payment_status(
            token=qr_token,
            status="invalid_status",  # Неверный статус
            transaction_id="TXN240101123458",
            amount=1000.00,
            payer_phone="+996555123456"
        )
    except ValidationError:
        print("✅ Правильно обработана ошибка валидации статуса")
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
    
    # Закрываем клиент
    client.close()


def context_manager_example():
    """Пример использования с context manager"""
    print("=== Пример 5: Использование context manager ===")
    
    with QRPayHubClient(
        base_url='https://api.qrpayhub.com',
        access_token='your-access-token',
        hmac_secret='your-hmac-secret'
    ) as client:
        try:
            # Клиент автоматически закроется после выхода из блока with
            payment_info = client.get_payment_info("some-token")
            print(f"Платеж: {payment_info.amount} {payment_info.currency}")
        except Exception as e:
            print(f"Ошибка: {e}")


def async_webhook_example():
    """Пример асинхронной отправки webhook"""
    import threading
    import time
    
    print("=== Пример 6: Асинхронная отправка webhook ===")
    
    def send_webhook_async(client, webhook_data):
        """Функция для отправки webhook в отдельном потоке"""
        try:
            result = client.send_payment_status(**webhook_data)
            print(f"✅ Webhook отправлен: {result['message']}")
        except Exception as e:
            print(f"❌ Ошибка webhook: {e}")
    
    client = QRPayHubClient(
        base_url='https://api.qrpayhub.com',
        access_token='your-access-token',
        hmac_secret='your-hmac-secret'
    )
    
    # Данные для webhook
    webhook_data = {
        'token': 'some-token',
        'status': PaymentStatus.SUCCESS,
        'transaction_id': 'TXN240101123459',
        'amount': 1500.00,
        'payer_phone': '+996555123456'
    }
    
    # Отправляем webhook асинхронно
    thread = threading.Thread(
        target=send_webhook_async,
        args=(client, webhook_data)
    )
    thread.start()
    
    print("Webhook отправляется в фоновом режиме...")
    
    # Ждем завершения
    thread.join()
    client.close()


if __name__ == '__main__':
    main()
    context_manager_example()
    async_webhook_example()
