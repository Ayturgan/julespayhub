#!/bin/bash

echo "🚀 Инициализация QRPayHub в Docker..."

# Запускаем приложение
echo "🌐 Запуск QRPayHub..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
