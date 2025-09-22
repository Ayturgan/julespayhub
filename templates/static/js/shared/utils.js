/**
 * QRPayHub Shared Utilities
 */

// Форматирование валюты
function formatAmount(amount) {
    if (amount === null || amount === undefined) return '0.00';
    return new Intl.NumberFormat('ru-RU', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(amount);
}

// Форматирование процентов
function formatPercent(value) {
    if (value === null || value === undefined) return '0%';
    return `${value.toFixed(1)}%`;
}

// Форматирование даты
function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('ru-RU', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Показ алертов
function showAlert(message, type = 'success') {
    // Создаем элемент алерта
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 10000;
        max-width: 400px;
        animation: slideIn 0.3s ease;
    `;
    alert.textContent = message;
    
    // Добавляем стили для анимации
    if (!document.getElementById('alert-styles')) {
        const style = document.createElement('style');
        style.id = 'alert-styles';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }
    
    // Добавляем в DOM
    document.body.appendChild(alert);
    
    // Удаляем через 5 секунд
    setTimeout(() => {
        alert.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            if (alert.parentNode) {
                alert.parentNode.removeChild(alert);
            }
        }, 300);
    }, 5000);
}

// Аутентификация продавца
function requireMerchantAuth() {
    const token = localStorage.getItem('merchant_token');
    if (!token) {
        showAlert('Требуется авторизация', 'error');
        setTimeout(() => {
            window.location.href = '/merchant-login';
        }, 2000);
        return null;
    }
    return token;
}

// Функция для получения правильного URL с учетом протокола
function getApiUrl(path) {
    try {
        // ПРИНУДИТЕЛЬНАЯ ЗАМЕНА HTTP НА HTTPS В ЛЮБОМ МЕСТЕ
        let securePath = path;
        if (typeof securePath === 'string') {
            securePath = securePath.replace(/http:\/\//g, 'https://');
        }
        
        // Если путь уже содержит HTTPS, возвращаем как есть
        if (securePath.startsWith('https://')) {
            return securePath;
        }
        
        // Если путь начинается с //, добавляем HTTPS
        if (securePath.startsWith('//')) {
            return 'https:' + securePath;
        }
        
        // ДЛЯ ОТНОСИТЕЛЬНЫХ ПУТЕЙ ВСЕГДА ИСПОЛЬЗУЕМ ОТНОСИТЕЛЬНЫЙ ПУТЬ
        // Это позволит браузеру автоматически использовать текущий протокол (HTTPS)
        if (securePath.startsWith('/')) {
            return securePath;
        }
        
        // Fallback - добавляем слеш в начало
        return '/' + securePath;
        
    } catch (error) {
        console.warn('Ошибка в getApiUrl:', error);
        // В случае ошибки возвращаем исходный путь, но заменяем HTTP на HTTPS
        return typeof path === 'string' ? path.replace(/http:\/\//g, 'https://') : path;
    }
}

// API запросы
class API {
    static async request(url, options = {}) {
        // Получаем токен для авторизации
        const token = localStorage.getItem('merchant_token');
        
        // Преобразуем URL для использования правильного протокола
        const secureUrl = getApiUrl(url);
        
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
        };
        
        // Добавляем токен авторизации если он есть
        if (token) {
            defaultOptions.headers['Authorization'] = `Bearer ${token}`;
        }
        
        const config = { ...defaultOptions, ...options };
        
        // Объединяем заголовки
        if (options.headers) {
            config.headers = { ...defaultOptions.headers, ...options.headers };
        }
        
        try {
            const response = await fetch(secureUrl, config);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API request failed:', error);
            showAlert(`Ошибка запроса: ${error.message}`, 'error');
            throw error;
        }
    }
    
    static async get(url) {
        return this.request(url);
    }
    
    static async post(url, data) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    static async put(url, data) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    static async delete(url) {
        return this.request(url, {
            method: 'DELETE'
        });
    }
}

// Управление состоянием
class StateManager {
    constructor() {
        this.state = {};
        this.listeners = {};
    }
    
    setState(key, value) {
        this.state[key] = value;
        this.notifyListeners(key, value);
    }
    
    getState(key) {
        return this.state[key];
    }
    
    subscribe(key, callback) {
        if (!this.listeners[key]) {
            this.listeners[key] = [];
        }
        this.listeners[key].push(callback);
    }
    
    notifyListeners(key, value) {
        if (this.listeners[key]) {
            this.listeners[key].forEach(callback => callback(value));
        }
    }
}

// Глобальный экземпляр StateManager
const stateManager = new StateManager();

// Утилиты для работы с DOM
const DOM = {
    // Показать/скрыть элемент
    toggle: (selector, show = null) => {
        const element = document.querySelector(selector);
        if (element) {
            if (show === null) {
                element.style.display = element.style.display === 'none' ? '' : 'none';
            } else {
                element.style.display = show ? '' : 'none';
            }
        }
    },
    
    // Добавить/удалить класс
    toggleClass: (selector, className) => {
        const element = document.querySelector(selector);
        if (element) {
            element.classList.toggle(className);
        }
    },
    
    // Установить HTML
    setHTML: (selector, html) => {
        const element = document.querySelector(selector);
        if (element) {
            element.innerHTML = html;
        }
    },
    
    // Установить текст
    setText: (selector, text) => {
        const element = document.querySelector(selector);
        if (element) {
            element.textContent = text;
        }
    }
};

// ГЛОБАЛЬНОЕ ПЕРЕОПРЕДЕЛЕНИЕ FETCH ДЛЯ ПРИНУДИТЕЛЬНОЙ ЗАМЕНЫ HTTP НА HTTPS
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    // Принудительно заменяем HTTP на HTTPS в URL
    let secureUrl = url;
    if (typeof secureUrl === 'string') {
        const originalUrl = secureUrl;
        secureUrl = secureUrl.replace(/http:\/\//g, 'https://');
        
        // Логируем только если URL изменился
        if (originalUrl !== secureUrl) {
            console.log('🔒 HTTP -> HTTPS conversion:', originalUrl, '->', secureUrl);
        }
    }
    
    // Вызываем оригинальный fetch с безопасным URL
    return originalFetch.call(this, secureUrl, options);
};

// ГЛОБАЛЬНОЕ ПЕРЕОПРЕДЕЛЕНИЕ XMLHttpRequest ДЛЯ ПРИНУДИТЕЛЬНОЙ ЗАМЕНЫ HTTP НА HTTPS
const originalXHROpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
    // Принудительно заменяем HTTP на HTTPS в URL
    let secureUrl = url;
    if (typeof secureUrl === 'string') {
        const originalUrl = secureUrl;
        secureUrl = secureUrl.replace(/http:\/\//g, 'https://');
        
        // Логируем только если URL изменился
        if (originalUrl !== secureUrl) {
            console.log('🔒 XMLHttpRequest HTTP -> HTTPS conversion:', originalUrl, '->', secureUrl);
        }
    }
    
    // Вызываем оригинальный open с безопасным URL
    return originalXHROpen.call(this, method, secureUrl, async, user, password);
};

// Экспорт для использования в модулях
window.QRPayHub = window.QRPayHub || {};
window.QRPayHub.utils = {
    formatAmount,
    formatPercent,
    formatDate,
    showAlert,
    getApiUrl,  // Добавляем новую функцию
    API,
    StateManager,
    stateManager,
    DOM
};

