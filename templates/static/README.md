# QRPayHub Frontend Structure

## Обзор

Фронтенд QRPayHub был рефакторен для улучшения структуры, модульности и поддерживаемости. Теперь код разделен на логические модули с четким разделением ответственности.

## Структура папок

```
templates/static/
├── css/                    # CSS стили
│   ├── base.css           # Базовые стили и переменные
│   ├── components.css     # Общие компоненты (кнопки, формы, таблицы)
│   ├── admin.css          # Стили для админ-панели
│   └── merchant.css       # Стили для кабинета продавца
├── js/                    # JavaScript модули
│   ├── shared/            # Общие утилиты и модули
│   │   ├── utils.js       # Утилиты форматирования, API, DOM
│   │   └── navigation.js  # Система навигации
│   ├── admin/             # Модули админ-панели
│   │   └── main.js        # Основной модуль админ-панели
│   └── merchant/          # Модули кабинета продавца
│       └── main.js        # Основной модуль кабинета продавца
└── README.md              # Эта документация
```

## CSS Архитектура

### base.css
- CSS переменные (цвета, шрифты, отступы)
- Базовые стили для body, html
- Утилитарные классы
- Сетка и контейнеры

### components.css
- Кнопки (.btn, .btn-table)
- Формы (input, select, textarea)
- Таблицы (.table-container, th, td)
- Карточки (.card)
- Бейджи (.badge)
- Алерты (.alert)

### admin.css / merchant.css
- Специфичные стили для каждого интерфейса
- Layout компоненты (sidebar, main-content)
- Навигация
- Адаптивность

## JavaScript Архитектура

### Общие модули (shared/)

#### utils.js
```javascript
// Глобальный объект QRPayHub.utils
QRPayHub.utils = {
    formatAmount,      // Форматирование валюты
    formatPercent,     // Форматирование процентов
    formatDate,        // Форматирование дат
    showAlert,         // Показ уведомлений
    API,               // Класс для API запросов
    StateManager,      // Управление состоянием
    DOM                // Утилиты для работы с DOM
}
```

#### navigation.js
```javascript
// Система навигации
QRPayHub.navigation = {
    showSection(sectionName),     // Показать секцию
    registerSection(name, handler), // Зарегистрировать обработчик
    getCurrentSection(),          // Получить текущую секцию
    updatePageTitle(title)        // Обновить заголовок
}
```

### Модули интерфейсов

#### admin/main.js
```javascript
// Основной класс админ-панели
class AdminPanel {
    // Инициализация
    init()
    initializeAdmin()
    
    // Загрузка данных
    loadDashboard()
    loadBanks()
    loadPayments()
    loadMonitoring()
    loadSecurity()
    loadAnalytics()
    loadTesting()
    loadLogs()
    
    // Обработчики
    toggleBankStatus()
    showBankDetails()
    showPaymentDetails()
}
```

#### merchant/main.js
```javascript
// Основной класс кабинета продавца
class MerchantPanel {
    // Инициализация
    init()
    initializeMerchant()
    
    // Загрузка данных
    loadDashboard()
    loadQRCodes()
    loadPayments()
    loadOutlets()
    loadStatistics()
    loadSettings()
    
    // Обработчики
    downloadQR()
    copyQRLink()
    deleteQR()
    editOutlet()
    deleteOutlet()
    showPaymentDetails()
}
```

## Использование

### Подключение в HTML

```html
<!-- CSS файлы -->
<link rel="stylesheet" href="/static/css/base.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/admin.css">  <!-- или merchant.css -->

<!-- JavaScript файлы -->
<script src="/static/js/shared/utils.js"></script>
<script src="/static/js/shared/navigation.js"></script>
<script src="/static/js/admin/main.js"></script>  <!-- или merchant/main.js -->
```

### Регистрация секций

```javascript
// Регистрация обработчика для секции
QRPayHub.navigation.registerSection('dashboard', () => {
    // Загрузка данных дашборда
    loadDashboardData();
});

// Показ секции
QRPayHub.navigation.showSection('dashboard');
```

### API запросы

```javascript
// GET запрос
const data = await QRPayHub.utils.API.get('/api/v1/admin/banks');

// POST запрос
const result = await QRPayHub.utils.API.post('/api/v1/admin/banks', bankData);

// PUT запрос
const updated = await QRPayHub.utils.API.put('/api/v1/admin/banks/1', updateData);

// DELETE запрос
await QRPayHub.utils.API.delete('/api/v1/admin/banks/1');
```

### Утилиты

```javascript
// Форматирование
const amount = QRPayHub.utils.formatAmount(1500.50); // "1 500,50"
const percent = QRPayHub.utils.formatPercent(25.5);  // "25.5%"
const date = QRPayHub.utils.formatDate('2025-01-15'); // "15 янв. 2025, 00:00"

// Уведомления
QRPayHub.utils.showAlert('Операция выполнена успешно', 'success');
QRPayHub.utils.showAlert('Произошла ошибка', 'error');

// Работа с DOM
QRPayHub.utils.DOM.setHTML('#content', '<p>Новый контент</p>');
QRPayHub.utils.DOM.setText('#title', 'Новый заголовок');
QRPayHub.utils.DOM.toggle('#modal', true);
```

## Преимущества новой структуры

1. **Модульность** - каждый компонент отвечает за свою область
2. **Переиспользование** - общие утилиты и компоненты
3. **Поддерживаемость** - четкое разделение ответственности
4. **Масштабируемость** - легко добавлять новые модули
5. **Тестируемость** - изолированные компоненты легче тестировать
6. **Производительность** - загрузка только необходимых файлов

## Миграция с старой структуры

### Что изменилось:
- Удален монолитный `admin.js` (812 строк)
- Стили вынесены в отдельные CSS файлы
- Добавлена система навигации
- Унифицированы API запросы
- Добавлены общие утилиты

### Что осталось:
- HTML структура страниц
- Логика работы с данными
- Функциональность интерфейсов

## Следующие шаги

1. **Добавить TypeScript** - для типизации и лучшей разработки
2. **Создать модули для конкретных функций** - разбить main.js на более мелкие модули
3. **Добавить тесты** - для проверки работоспособности модулей
4. **Оптимизировать загрузку** - минификация и сжатие файлов
5. **Добавить документацию API** - для лучшего понимания эндпоинтов

