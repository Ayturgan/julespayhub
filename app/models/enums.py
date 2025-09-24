import enum


class TransactionStatus(enum.Enum):
    """Статусы двухфазных транзакций"""
    PENDING = "pending"           # Исходное состояние
    PREPARING = "preparing"       # QRPayHub начал фазу подготовки
    PREPARED = "prepared"         # Оба банка подтвердили готовность, деньги зарезервированы
    COMMITTING = "committing"     # QRPayHub дал команду на выполнение
    COMPLETED = "completed"       # Транзакция успешно завершена
    ABORTING = "aborting"         # QRPayHub дал команду на отмену
    ABORTED = "aborted"           # Транзакция отменена, средства возвращены

