#!/usr/bin/env python3
"""
Скрипт для запуска QRPayHub с включенным симулятором банков

Использование:
python run_with_simulator.py

Или через uvicorn с переменной окружения:
ENABLE_BANK_SIMULATOR=true uvicorn app.main:app --reload
"""

import os
import sys
import subprocess

def main():
    """Запуск приложения с включенным симулятором"""
    
    print("🏦 Запуск QRPayHub с симулятором банков...")
    print("=" * 50)
    
    # Устанавливаем переменную окружения
    env = os.environ.copy()
    env["ENABLE_BANK_SIMULATOR"] = "true"
    
    # Определяем команду запуска
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "app.main:app", 
        "--reload", 
        "--host", "0.0.0.0", 
        "--port", "8000"
    ]
    
    print(f"Команда запуска: {' '.join(cmd)}")
    print(f"Переменные окружения: ENABLE_BANK_SIMULATOR=true")
    print("=" * 50)
    print("")
    print("📱 Симулятор банков доступен по адресу:")
    print("   http://localhost:8000/simulation")
    print("")
    print("🔧 Админ панель:")
    print("   http://localhost:8000/admin")
    print("")
    print("📖 API документация:")
    print("   http://localhost:8000/docs")
    print("")
    print("=" * 50)
    print("Нажмите Ctrl+C для остановки")
    print("=" * 50)
    
    try:
        # Запускаем приложение
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n🛑 Приложение остановлено пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка запуска: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
