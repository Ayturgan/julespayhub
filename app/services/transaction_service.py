"""
Сервис для управления транзакциями с улучшенной изоляцией
Обеспечивает атомарность операций и предотвращает race conditions
"""

from typing import Callable, Any, TypeVar, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from contextlib import contextmanager
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')

class TransactionService:
    """Сервис для управления транзакциями"""
    
    def __init__(self):
        self.max_retries = 3
        self.retry_delay = 0.1  # секунды
        
    @contextmanager
    def atomic_transaction(self, db: Session, retry_on_deadlock: bool = True):
        """
        Контекстный менеджер для атомарных транзакций
        
        Args:
            db: Сессия базы данных
            retry_on_deadlock: Повторять ли при deadlock
            
        Yields:
            Сессия базы данных в транзакции
        """
        
        retry_count = 0
        
        while retry_count < self.max_retries:
            try:
                # Начинаем транзакцию
                yield db
                
                # Если дошли до сюда, коммитим транзакцию
                db.commit()
                logger.debug("✅ Транзакция успешно закоммичена")
                return
                
            except IntegrityError as e:
                # Ошибки целостности - откатываем и не повторяем
                db.rollback()
                logger.error(f"❌ Ошибка целостности в транзакции: {e}")
                raise
                
            except OperationalError as e:
                # Операционные ошибки (включая deadlock)
                db.rollback()
                retry_count += 1
                
                if "deadlock" in str(e).lower() and retry_on_deadlock and retry_count < self.max_retries:
                    logger.warning(f"🔄 Deadlock обнаружен, повторяем попытку {retry_count}/{self.max_retries}")
                    time.sleep(self.retry_delay * retry_count)  # Экспоненциальная задержка
                    continue
                else:
                    logger.error(f"❌ Операционная ошибка в транзакции: {e}")
                    raise
                    
            except Exception as e:
                # Любые другие ошибки - откатываем
                db.rollback()
                logger.error(f"❌ Неожиданная ошибка в транзакции: {e}")
                raise
        
        # Если дошли до сюда, значит превысили лимит повторов
        raise OperationalError("Превышен лимит повторов транзакции", None, None)
    
    def with_transaction(self, retry_on_deadlock: bool = True):
        """
        Декоратор для функций, требующих транзакционной изоляции
        
        Args:
            retry_on_deadlock: Повторять ли при deadlock
            
        Returns:
            Декорированная функция
        """
        
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                # Ищем сессию БД в аргументах
                db_session = None
                
                # Ищем в позиционных аргументах
                for arg in args:
                    if isinstance(arg, Session):
                        db_session = arg
                        break
                
                # Ищем в именованных аргументах
                if db_session is None:
                    db_session = kwargs.get('db')
                
                if db_session is None:
                    raise ValueError("Сессия базы данных не найдена в аргументах функции")
                
                # Выполняем функцию в транзакции
                with self.atomic_transaction(db_session, retry_on_deadlock):
                    return func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    def execute_in_transaction(
        self, 
        db: Session, 
        func: Callable[..., T], 
        *args, 
        retry_on_deadlock: bool = True,
        **kwargs
    ) -> T:
        """
        Выполняет функцию в транзакции
        
        Args:
            db: Сессия базы данных
            func: Функция для выполнения
            *args: Аргументы функции
            retry_on_deadlock: Повторять ли при deadlock
            **kwargs: Именованные аргументы функции
            
        Returns:
            Результат выполнения функции
        """
        
        with self.atomic_transaction(db, retry_on_deadlock):
            return func(*args, **kwargs)
    
    def lock_for_update(self, db: Session, model_class, **filters):
        """
        Блокирует запись для обновления (SELECT FOR UPDATE)
        
        Args:
            db: Сессия базы данных
            model_class: Класс модели
            **filters: Фильтры для поиска записи
            
        Returns:
            Заблокированная запись или None
        """
        
        try:
            query = db.query(model_class).filter_by(**filters)
            return query.with_for_update().first()
        except Exception as e:
            logger.error(f"❌ Ошибка при блокировке записи: {e}")
            raise

# Глобальный экземпляр сервиса
transaction_service = TransactionService()
