// Основные функции для админ панели
document.addEventListener('DOMContentLoaded', function() {
    // Загружаем информацию об админе при загрузке страницы
    loadAdminInfo();
});

async function loadAdminInfo() {
    try {
        const token = localStorage.getItem('admin_token');
        if (!token) {
            console.log('Токен админа не найден');
            return;
        }

        const response = await fetch(QRPayHub.utils.getApiUrl('/api/v1/admin-auth/me'), {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            console.error('Ошибка загрузки профиля админа:', response.status);
            return;
        }

        const admin = await response.json();
        
        // Обновляем имя админа в навигации
        const adminNameElement = document.getElementById('current-admin-name');
        if (adminNameElement) {
            adminNameElement.textContent = admin.full_name || admin.username || 'Администратор';
        }

        // Обновляем email админа если есть элемент
        const adminEmailElement = document.getElementById('current-admin-email');
        if (adminEmailElement) {
            adminEmailElement.textContent = admin.email || '';
        }

        // Обновляем роль админа если есть элемент
        const adminRoleElement = document.getElementById('current-admin-role');
        if (adminRoleElement) {
            const roleText = admin.role === 'super_admin' ? 'Супер Администратор' : 'Администратор';
            adminRoleElement.textContent = roleText;
        }

        console.log('Информация об админе загружена:', admin.full_name);

    } catch (error) {
        console.error('Ошибка при загрузке информации об админе:', error);
        
        // Показываем дефолтное имя если произошла ошибка
        const adminNameElement = document.getElementById('current-admin-name');
        if (adminNameElement && !adminNameElement.textContent) {
            adminNameElement.textContent = 'Администратор';
        }
    }
}

// Функция для выхода из системы
function logout() {
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_info');
    window.location.href = '/admin-login';
}

// Функция для проверки авторизации
function checkAuth() {
    const token = localStorage.getItem('admin_token');
    if (!token) {
        window.location.href = '/admin-login';
        return false;
    }
    return true;
}

// Функция для получения токена с проверкой
function getAuthToken() {
    const token = localStorage.getItem('admin_token');
    if (!token) {
        throw new Error('Токен не найден');
    }
    return token;
}
