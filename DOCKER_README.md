# QRPayHub Docker Setup

## Быстрый запуск

### 1. Сборка и запуск
```bash
# Собрать и запустить контейнеры
docker-compose up --build

# Или в фоновом режиме
docker-compose up -d --build
```

### 2. Доступ к приложению
- **Основное приложение**: http://localhost:8000
- **Админ панель**: http://localhost:8000/admin
- **API документация**: http://localhost:8000/docs

### 3. Остановка
```bash
# Остановить контейнеры
docker-compose down

# Остановить и удалить volumes (удалит базу данных)
docker-compose down -v
```

## Структура проекта в Docker

### Volumes (монтирования)
- `.:/app` - весь код проекта
- `./logs:/app/logs` - логи приложения
- `./qrpayhub.db:/app/qrpayhub.db` - SQLite база данных

### Переменные окружения
Все настройки находятся в `docker-compose.yml`:
- `DATABASE_URL` - SQLite база данных
- `BASE_URL` - базовый URL приложения
- `ENABLE_BANK_SIMULATOR` - включение симулятора банков
- Настройки rate limiting и мониторинга

## Разработка

### Hot Reload
Приложение автоматически перезагружается при изменении кода благодаря:
- Volume монтированию `.:/app`
- Uvicorn с флагом `--reload`

### Логи
```bash
# Просмотр логов в реальном времени
docker-compose logs -f qrpayhub

# Просмотр последних логов
docker-compose logs qrpayhub
```

### База данных
- База данных автоматически инициализируется при первом запуске
- Данные сохраняются в `./qrpayhub.db` на хосте
- Для сброса базы: `docker-compose down -v && docker-compose up --build`

## Полезные команды

```bash
# Пересборка без кэша
docker-compose build --no-cache

# Запуск только одного сервиса
docker-compose up qrpayhub

# Выполнение команд внутри контейнера
docker-compose exec qrpayhub python init_db.py

# Просмотр состояния контейнеров
docker-compose ps
```

## Troubleshooting

### Проблемы с правами доступа
```bash
# Исправить права на файлы
sudo chown -R $USER:$USER .
chmod +x docker-init.sh
```

### Проблемы с портами
Если порт 8000 занят, измените в `docker-compose.yml`:
```yaml
ports:
  - "8001:8000"  # Использовать порт 8001 на хосте
```

### Очистка Docker
```bash
# Удалить неиспользуемые образы
docker system prune -a

# Удалить все контейнеры и volumes
docker-compose down -v
docker system prune -a --volumes
```
