/**
 * QRPayHub Merchant Panel Main Module
 */

class MerchantPanel {
    constructor() {
        this.refreshInterval = null;
        this.init();
    }
    
    init() {
        this.initializeMerchant();
        this.startAutoRefresh();
        this.registerSections();
    }
    
    async initializeMerchant() {
        try {
            // Загружаем дашборд по умолчанию
            await this.loadDashboard();
            
            QRPayHub.utils.showAlert('Кабинет продавца инициализирован', 'success');
        } catch (error) {
            console.error('Initialization error:', error);
            QRPayHub.utils.showAlert('Ошибка инициализации кабинета продавца', 'error');
        }
    }
    
    startAutoRefresh() {
        // Обновляем дашборд каждые 30 секунд
        this.refreshInterval = setInterval(() => {
            const currentSection = QRPayHub.navigation.getCurrentSection();
            if (currentSection === 'dashboard') {
                this.loadDashboard();
            }
        }, 30000);
    }
    
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }
    
    registerSections() {
        // Регистрируем обработчики для всех секций
        QRPayHub.navigation.registerSection('dashboard', () => this.loadDashboard());
        QRPayHub.navigation.registerSection('qr-codes', () => this.loadQRCodes());
        QRPayHub.navigation.registerSection('payments', () => this.loadPayments());
        QRPayHub.navigation.registerSection('outlets', () => this.loadOutlets());
        QRPayHub.navigation.registerSection('statistics', () => this.loadStatistics());
        QRPayHub.navigation.registerSection('settings', () => this.loadSettings());
    }
    
    // Загрузка дашборда
    async loadDashboard() {
        try {
            QRPayHub.navigation.updatePageTitle('Дашборд');
            
            // Загружаем статистику продавца
            const [statsResponse, recentPaymentsResponse] = await Promise.all([
                QRPayHub.utils.API.get('/api/v1/merchant/stats'),
                QRPayHub.utils.API.get('/api/v1/merchant/payments?limit=5')
            ]);
            
            this.updateDashboardStats(statsResponse, recentPaymentsResponse);
            
        } catch (error) {
            console.error('Dashboard loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки дашборда', 'error');
        }
    }
    
    updateDashboardStats(stats, recentPayments) {
        // Обновляем статистику
        QRPayHub.utils.DOM.setHTML('#statsGrid', `
            <div class="stat-card">
                <div class="stat-value">${stats.total_payments || 0}</div>
                <div class="stat-label">Всего платежей</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${QRPayHub.utils.formatAmount(stats.total_amount || 0)}</div>
                <div class="stat-label">Общая сумма</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${stats.active_qr_codes || 0}</div>
                <div class="stat-label">Активных QR-кодов</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${stats.today_payments || 0}</div>
                <div class="stat-label">Платежей сегодня</div>
            </div>
        `);
        
        // Обновляем последние платежи
        if (recentPayments && recentPayments.length > 0) {
            const paymentsHTML = recentPayments.map(payment => `
                <tr>
                    <td>${payment.token}</td>
                    <td>${QRPayHub.utils.formatAmount(payment.amount)}</td>
                    <td>
                        <span class="badge ${payment.status === 'completed' ? 'ok' : 'warn'}">
                            ${payment.status}
                        </span>
                    </td>
                    <td>${QRPayHub.utils.formatDate(payment.created_at)}</td>
                </tr>
            `).join('');
            
            QRPayHub.utils.DOM.setHTML('#recentPaymentsTable tbody', paymentsHTML);
        } else {
            QRPayHub.utils.DOM.setHTML('#recentPaymentsTable tbody', 
                '<tr><td colspan="4" class="text-center">Нет платежей</td></tr>'
            );
        }
    }
    
    // Загрузка QR-кодов
    async loadQRCodes() {
        try {
            QRPayHub.navigation.updatePageTitle('QR-коды');
            
            const response = await QRPayHub.utils.API.get('/api/v1/merchant/qr-codes');
            this.renderQRCodes(response);
        } catch (error) {
            console.error('QR codes loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки QR-кодов', 'error');
        }
    }
    
    renderQRCodes(qrCodes) {
        if (qrCodes && qrCodes.length > 0) {
            const qrHTML = qrCodes.map(qr => `
                <div class="qr-card">
                    <div class="qr-image">
                        <img src="${QRPayHub.utils.getApiUrl('/api/v1/admin/qr-image/' + qr.token)}" alt="QR Code">
                    </div>
                    <div class="qr-details">
                        <h3>${qr.description || 'QR-код'}</h3>
                        <p><strong>Сумма:</strong> ${QRPayHub.utils.formatAmount(qr.amount)}</p>
                        <p><strong>Статус:</strong> 
                            <span class="badge ${qr.status === 'active' ? 'ok' : 'warn'}">
                                ${qr.status === 'active' ? 'Активен' : 'Неактивен'}
                            </span>
                        </p>
                        <p><strong>Создан:</strong> ${QRPayHub.utils.formatDate(qr.created_at)}</p>
                        <p><strong>Истекает:</strong> ${QRPayHub.utils.formatDate(qr.expires_at)}</p>
                    </div>
                    <div class="qr-actions">
                        <button class="btn primary" onclick="merchantPanel.downloadQR('${qr.token}')">
                            Скачать
                        </button>
                        <button class="btn secondary" onclick="merchantPanel.copyQRLink('${qr.token}')">
                            Копировать ссылку
                        </button>
                        <button class="btn danger" onclick="merchantPanel.deleteQR('${qr.token}')">
                            Удалить
                        </button>
                    </div>
                </div>
            `).join('');
            
            QRPayHub.utils.DOM.setHTML('#qrCodesGrid', qrHTML);
        } else {
            QRPayHub.utils.DOM.setHTML('#qrCodesGrid', 
                '<div class="card text-center">Нет созданных QR-кодов</div>'
            );
        }
    }
    
    // Загрузка платежей
    async loadPayments() {
        try {
            QRPayHub.navigation.updatePageTitle('Платежи');
            
            const response = await QRPayHub.utils.API.get('/api/v1/merchant/payments');
            this.renderPayments(response);
        } catch (error) {
            console.error('Payments loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки платежей', 'error');
        }
    }
    
    renderPayments(payments) {
        if (payments && payments.length > 0) {
            const paymentsHTML = payments.map(payment => `
                <tr>
                    <td>${payment.token}</td>
                    <td>${QRPayHub.utils.formatAmount(payment.amount)}</td>
                    <td>
                        <span class="badge ${payment.status === 'completed' ? 'ok' : 
                                          payment.status === 'pending' ? 'warn' : 'err'}">
                            ${payment.status}
                        </span>
                    </td>
                    <td>${QRPayHub.utils.formatDate(payment.created_at)}</td>
                    <td>${payment.payer_phone || '-'}</td>
                    <td class="table-actions">
                        <button class="btn-table primary" onclick="merchantPanel.showPaymentDetails('${payment.token}')">
                            Детали
                        </button>
                    </td>
                </tr>
            `).join('');
            
            QRPayHub.utils.DOM.setHTML('#paymentsTable tbody', paymentsHTML);
        } else {
            QRPayHub.utils.DOM.setHTML('#paymentsTable tbody', 
                '<tr><td colspan="6" class="text-center">Нет платежей</td></tr>'
            );
        }
    }
    
    // Загрузка точек продаж
    async loadOutlets() {
        try {
            QRPayHub.navigation.updatePageTitle('Точки продаж');
            
            const response = await QRPayHub.utils.API.get('/api/v1/merchant/outlets');
            this.renderOutlets(response);
        } catch (error) {
            console.error('Outlets loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки точек продаж', 'error');
        }
    }
    
    renderOutlets(outlets) {
        if (outlets && outlets.length > 0) {
            const outletsHTML = outlets.map(outlet => `
                <tr>
                    <td>${outlet.name}</td>
                    <td>${outlet.address}</td>
                    <td>${outlet.phone || '-'}</td>
                    <td>
                        <span class="badge ${outlet.is_active ? 'ok' : 'err'}">
                            ${outlet.is_active ? 'Активна' : 'Неактивна'}
                        </span>
                    </td>
                    <td class="table-actions">
                        <button class="btn-table secondary" onclick="merchantPanel.editOutlet('${outlet.id}')">
                            Редактировать
                        </button>
                        <button class="btn-table danger" onclick="merchantPanel.deleteOutlet('${outlet.id}')">
                            Удалить
                        </button>
                    </td>
                </tr>
            `).join('');
            
            QRPayHub.utils.DOM.setHTML('#outletsTable tbody', outletsHTML);
        } else {
            QRPayHub.utils.DOM.setHTML('#outletsTable tbody', 
                '<tr><td colspan="5" class="text-center">Нет точек продаж</td></tr>'
            );
        }
    }
    
    // Загрузка статистики
    async loadStatistics() {
        try {
            QRPayHub.navigation.updatePageTitle('Статистика');
            
            const response = await QRPayHub.utils.API.get('/api/v1/merchant/stats');
            this.renderStatistics(response);
        } catch (error) {
            console.error('Statistics loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки статистики', 'error');
        }
    }
    
    renderStatistics(stats) {
        // Обновляем статистику
        QRPayHub.utils.DOM.setHTML('#statisticsGrid', `
            <div class="stat-card">
                <div class="stat-value">${stats.total_payments || 0}</div>
                <div class="stat-label">Всего платежей</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${QRPayHub.utils.formatAmount(stats.total_amount || 0)}</div>
                <div class="stat-label">Общая сумма</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${stats.avg_payment || 0}</div>
                <div class="stat-label">Средний платеж</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${stats.success_rate || 0}%</div>
                <div class="stat-label">Успешность</div>
            </div>
        `);
    }
    
    // Загрузка настроек
    async loadSettings() {
        try {
            QRPayHub.navigation.updatePageTitle('Настройки');
            
            const response = await QRPayHub.utils.API.get('/api/v1/merchant/profile');
            this.renderSettings(response);
        } catch (error) {
            console.error('Settings loading error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки настроек', 'error');
        }
    }
    
    renderSettings(profile) {
        // Заполняем форму профиля
        if (profile) {
            const elements = {
                'merchantName': profile.name || '',
                'merchantEmail': profile.email || '',
                'merchantPhone': profile.phone || '',
                'merchantAddress': profile.address || ''
            };
            
            // Безопасно устанавливаем значения только для существующих элементов
            for (const [id, value] of Object.entries(elements)) {
                const element = document.getElementById(id);
                if (element && element.value !== undefined) {
                    element.value = value;
                }
            }
            
            // Обновляем отображение профиля в интерфейсе
            this.updateProfileDisplay(profile);
        }
    }
    
    updateProfileDisplay(profile) {
        // Обновляем отображение профиля в интерфейсе
        const profileElements = {
            '.profile-name': profile.name || 'Не указано',
            '.profile-email': profile.email || 'Не указано',
            '.profile-phone': profile.phone || 'Не указано',
            '.profile-company': profile.company_name || 'Не указано'
        };
        
        for (const [selector, value] of Object.entries(profileElements)) {
            const element = document.querySelector(selector);
            if (element) {
                element.textContent = value;
            }
        }
    }
    
    // Методы для работы с QR-кодами
    async downloadQR(token) {
        try {
            const link = document.createElement('a');
            link.href = QRPayHub.utils.getApiUrl(`/api/v1/admin/qr-image/${token}`);
            link.download = `qr-${token}.png`;
            link.click();
        } catch (error) {
            console.error('Download QR error:', error);
            QRPayHub.utils.showAlert('Ошибка скачивания QR-кода', 'error');
        }
    }
    
    async copyQRLink(token) {
        try {
            const link = `${window.PAYMENT_URL_TEMPLATE}${token}`;
            await navigator.clipboard.writeText(link);
            QRPayHub.utils.showAlert('Ссылка скопирована в буфер обмена', 'success');
        } catch (error) {
            console.error('Copy QR link error:', error);
            QRPayHub.utils.showAlert('Ошибка копирования ссылки', 'error');
        }
    }
    
    async deleteQR(token) {
        if (confirm('Вы уверены, что хотите удалить этот QR-код?')) {
            try {
                await QRPayHub.utils.API.delete(`/api/v1/merchant/qr-codes/${token}`);
                QRPayHub.utils.showAlert('QR-код удален', 'success');
                this.loadQRCodes(); // Перезагружаем список
            } catch (error) {
                console.error('Delete QR error:', error);
                QRPayHub.utils.showAlert('Ошибка удаления QR-кода', 'error');
            }
        }
    }
    
    // Методы для работы с точками продаж
    async editOutlet(outletId) {
        try {
            const response = await QRPayHub.utils.API.get(`/api/v1/merchant/outlets/${outletId}`);
            // Показать модальное окно для редактирования
            console.log('Edit outlet:', response);
        } catch (error) {
            console.error('Edit outlet error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки данных точки продаж', 'error');
        }
    }
    
    async deleteOutlet(outletId) {
        if (confirm('Вы уверены, что хотите удалить эту точку продаж?')) {
            try {
                await QRPayHub.utils.API.delete(`/api/v1/merchant/outlets/${outletId}`);
                QRPayHub.utils.showAlert('Точка продаж удалена', 'success');
                this.loadOutlets(); // Перезагружаем список
            } catch (error) {
                console.error('Delete outlet error:', error);
                QRPayHub.utils.showAlert('Ошибка удаления точки продаж', 'error');
            }
        }
    }
    
    // Методы для работы с платежами
    async showPaymentDetails(token) {
        try {
            const response = await QRPayHub.utils.API.get(`/api/v1/merchant/payments/${token}`);
            // Показать модальное окно с деталями платежа
            console.log('Payment details:', response);
        } catch (error) {
            console.error('Show payment details error:', error);
            QRPayHub.utils.showAlert('Ошибка загрузки деталей платежа', 'error');
        }
    }
}

// Создаем глобальный экземпляр кабинета продавца
const merchantPanel = new MerchantPanel();

// Экспорт для использования в других модулях
window.QRPayHub = window.QRPayHub || {};
window.QRPayHub.merchantPanel = merchantPanel;
