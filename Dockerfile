FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем директории для логов и базы данных
RUN mkdir -p logs

# Устанавливаем права на запись
RUN chmod -R 755 /app
RUN chmod +x /app/docker-init.sh

# Устанавливаем переменные окружения для Docker
ENV DOCKER_ENV=true

# Открываем порт
EXPOSE 8000

# Команда по умолчанию
CMD ["bash", "/app/docker-init.sh"]
