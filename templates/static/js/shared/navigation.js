/**
 * QRPayHub Navigation Module
 */

class Navigation {
    constructor() {
        this.currentSection = 'dashboard';
        this.sections = new Map();
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadInitialSection();
    }
    
    bindEvents() {
        // Обработчики для навигационных ссылок
        document.addEventListener('click', (e) => {
            if (e.target.matches('.nav-link')) {
                e.preventDefault();
                const sectionName = e.target.getAttribute('data-section');
                if (sectionName) {
                    this.showSection(sectionName);
                }
            }
        });
    }
    
    loadInitialSection() {
        // Определяем начальную секцию из URL или по умолчанию
        const urlParams = new URLSearchParams(window.location.search);
        const section = urlParams.get('section') || this.currentSection;
        this.showSection(section);
    }
    
    showSection(sectionName) {
        // Скрываем все секции
        document.querySelectorAll('.section').forEach(section => {
            section.classList.remove('active');
        });
        
        // Убираем активный класс с кнопок
        document.querySelectorAll('.nav-link').forEach(item => {
            item.classList.remove('active');
        });
        
        // Показываем выбранную секцию
        const targetSection = document.getElementById(sectionName);
        if (targetSection) {
            targetSection.classList.add('active');
        }
        
        // Добавляем активный класс к кнопке
        const activeLink = document.querySelector(`[data-section="${sectionName}"]`);
        if (activeLink) {
            activeLink.classList.add('active');
        }
        
        this.currentSection = sectionName;
        
        // Обновляем URL
        this.updateURL(sectionName);
        
        // Загружаем данные для секции
        this.loadSectionData(sectionName);
    }
    
    updateURL(sectionName) {
        const url = new URL(window.location);
        url.searchParams.set('section', sectionName);
        window.history.pushState({}, '', url);
    }
    
    loadSectionData(sectionName) {
        // Вызываем соответствующий обработчик загрузки данных
        const handler = this.sections.get(sectionName);
        if (handler && typeof handler === 'function') {
            try {
                handler();
            } catch (error) {
                console.error(`Error loading section ${sectionName}:`, error);
                QRPayHub.utils.showAlert(`Ошибка загрузки раздела: ${error.message}`, 'error');
            }
        }
    }
    
    // Регистрация обработчиков загрузки данных для секций
    registerSection(sectionName, handler) {
        this.sections.set(sectionName, handler);
    }
    
    // Получение текущей секции
    getCurrentSection() {
        return this.currentSection;
    }
    
    // Проверка, активна ли секция
    isSectionActive(sectionName) {
        return this.currentSection === sectionName;
    }
    
    // Обновление заголовка страницы
    updatePageTitle(title) {
        const pageTitle = document.querySelector('.page-title');
        if (pageTitle) {
            pageTitle.textContent = title;
        }
        
        // Обновляем title страницы
        document.title = `QRPayHub — ${title}`;
    }
    
    // Добавление хлебных крошек
    setBreadcrumbs(items) {
        const breadcrumbsContainer = document.querySelector('.breadcrumbs');
        if (breadcrumbsContainer && items.length > 0) {
            const breadcrumbsHTML = items.map((item, index) => {
                if (index === items.length - 1) {
                    return `<span class="breadcrumb-item active">${item.text}</span>`;
                } else {
                    return `<a href="#" class="breadcrumb-item" data-section="${item.section}">${item.text}</a>`;
                }
            }).join(' / ');
            
            breadcrumbsContainer.innerHTML = breadcrumbsHTML;
        }
    }
}

// Создаем глобальный экземпляр навигации
const navigation = new Navigation();

// Экспорт для использования в модулях
window.QRPayHub = window.QRPayHub || {};
window.QRPayHub.navigation = navigation;

