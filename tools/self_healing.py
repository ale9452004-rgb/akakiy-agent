"""
Модуль контролируемого самовосстановления и обработки ошибок (Self-Healing).

Обеспечивает:
- сбор структурированного контекста ошибки (ErrorContext);
- детерминированную классификацию ошибок на recoverable / non-recoverable (ErrorClassifier);
- управление лимитами повторных попыток на уровне шага и плана (SelfHealingManager);
- предотвращение бесконечных циклов восстановления;
- фиксацию истории попыток в AgentContext и итоговом AgentResult.
"""

import time
from typing import Any, Dict, List, Optional, Union


class ErrorCategory:
    """Категории ошибок для классификации механизма Self-Healing."""
    TRANSIENT = "transient"                 # Временные ошибки (сеть, таймаут, кратковременный сбой)
    RESOURCE_BUSY = "resource_busy"         # Ресурс временно занят (VRAM, GPU, процесс)
    FILE_LOCKED = "file_locked"             # Файл заблокирован другим процессом
    VALIDATION_SYNTAX = "validation_syntax" # Синтаксическая ошибка валидации после изменений
    FATAL = "fatal"                         # Фатальная неустранимая ошибка
    USER_CANCELLED = "user_cancelled"       # Действие отменено пользователем
    SECURITY_VIOLATION = "security_violation" # Нарушение безопасности (path traversal, запрещённая операция)
    UNSUPPORTED = "unsupported"             # Неизвестное действие / ненайденный агент / неверные параметры
    EXHAUSTED = "exhausted"                 # Лимит попыток исчерпан
    UNKNOWN = "unknown"                     # Неизвестная / неклассифицированная ошибка


class ErrorContext:
    """
    Структурированный контекст ошибки выполнения шага плана.
    """

    def __init__(
        self,
        step_id: Any,
        action: str,
        error: str = "",
        message: str = "",
        subagent: Optional[str] = None,
        target: Optional[str] = None,
        details: str = "",
        attempt: int = 1,
        max_attempts: int = 2,
        is_recoverable: bool = False,
        category: str = ErrorCategory.UNKNOWN,
        strategy: str = "abort",
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None
    ):
        self.step_id = step_id
        self.action = str(action) if action else ""
        self.subagent = str(subagent) if subagent else None
        self.target = str(target) if target else None
        self.error = str(error) if error else ""
        self.message = str(message) if message else self.error
        self.details = str(details) if details else ""
        self.attempt = int(attempt)
        self.max_attempts = int(max_attempts)
        self.is_recoverable = bool(is_recoverable)
        self.category = str(category)
        self.strategy = str(strategy)
        self.metadata = dict(metadata) if metadata else {}
        self.timestamp = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует контекст ошибки в словарь."""
        return {
            "step_id": self.step_id,
            "action": self.action,
            "subagent": self.subagent,
            "target": self.target,
            "error": self.error,
            "message": self.message,
            "details": self.details,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "is_recoverable": self.is_recoverable,
            "category": self.category,
            "strategy": self.strategy,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ErrorContext":
        """Создаёт экземпляр ErrorContext из словаря."""
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")
        return cls(
            step_id=data.get("step_id"),
            action=data.get("action", ""),
            error=data.get("error", ""),
            message=data.get("message", ""),
            subagent=data.get("subagent"),
            target=data.get("target"),
            details=data.get("details", ""),
            attempt=data.get("attempt", 1),
            max_attempts=data.get("max_attempts", 2),
            is_recoverable=data.get("is_recoverable", False),
            category=data.get("category", ErrorCategory.UNKNOWN),
            strategy=data.get("strategy", "abort"),
            metadata=data.get("metadata"),
            timestamp=data.get("timestamp")
        )

    def __repr__(self) -> str:
        return (
            f"<ErrorContext step={self.step_id} action='{self.action}' "
            f"category='{self.category}' recoverable={self.is_recoverable} "
            f"attempt={self.attempt}/{self.max_attempts} strategy='{self.strategy}'>"
        )


class ErrorClassifier:
    """
    Детерминированный классификатор ошибок выполнения шагов плана.
    Разделяет ошибки на recoverable и non-recoverable.
    """

    # Паттерны для классификации non-recoverable
    USER_CANCEL_PATTERNS = [
        "отменил",
        "отменено",
        "отмена",
        "cancelled",
        "user_cancelled",
        "aborted"
    ]

    SECURITY_PATTERNS = [
        "path traversal",
        "за пределами",
        "запрещен",
        "запрещено",
        "security violation",
        "access denied",
        "не разрешено"
    ]

    UNSUPPORTED_PATTERNS = [
        "неизвестное действие",
        "unknown action",
        "не найден в реестре",
        "not found in registry",
        "не указан query",
        "не указан target",
        "не указана команда",
        "не хватает обязательных аргументов"
    ]

    # Паттерны для классификации recoverable
    FILE_LOCK_PATTERNS = [
        "being used by another process",
        "sharing violation",
        "файл заблокирован",
        "файл занят",
        "permissionerror",
        "permission denied",
        "device or resource busy"
    ]

    RESOURCE_BUSY_PATTERNS = [
        "resource busy",
        "vram busy",
        "cuda out of memory",
        "out of memory",
        "device busy",
        "сервер занят"
    ]

    TRANSIENT_PATTERNS = [
        "timeout",
        "timed out",
        "таймаут",
        "connection reset",
        "connection refused",
        "connection error",
        "сервер временно недоступен",
        "temporarily unavailable",
        "rate limit",
        "temporary failure",
        "transient",
        "retryable"
    ]

    def classify(
        self,
        step: Any,
        result: Any,
        attempt: int = 1,
        max_attempts: int = 2
    ) -> ErrorContext:
        """
        Классифицирует ошибку и возвращает структурированный ErrorContext.
        """
        step_dict = step.to_dict() if hasattr(step, "to_dict") else (dict(step) if isinstance(step, dict) else {})
        step_id = getattr(step, "id", None) or step_dict.get("id", "step")
        action = getattr(step, "action", None) or step_dict.get("action", "")
        subagent = getattr(step, "subagent", None) or step_dict.get("subagent")
        target = getattr(step, "target", None) or step_dict.get("target")
        details = getattr(step, "details", None) or step_dict.get("details", "")
        step_meta = getattr(step, "metadata", {}) or step_dict.get("metadata", {})

        # Извлечение текста ошибки и сообщения
        err_msg = ""
        msg = ""
        result_data: Dict[str, Any] = {}

        if hasattr(result, "error") and hasattr(result, "message"):
            err_msg = str(result.error or "")
            msg = str(result.message or "")
            if hasattr(result, "data") and isinstance(result.data, dict):
                result_data = result.data
        elif isinstance(result, dict):
            err_msg = str(result.get("error") or "")
            msg = str(result.get("message") or "")
            if isinstance(result.get("data"), dict):
                result_data = result.get("data", {})
            elif isinstance(result.get("result"), dict):
                result_data = result.get("result", {})

        if not err_msg and result_data.get("error"):
            err_msg = str(result_data["error"])
        if not msg and result_data.get("message"):
            msg = str(result_data["message"])

        combined_text = f"{err_msg} {msg} {result_data.get('error', '')} {result_data.get('message', '')}".strip()
        text_lower = combined_text.lower()

        # 1. Проверка исчерпания попыток (если уже достигнут лимит)
        if attempt >= max_attempts:
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.EXHAUSTED,
                strategy="exhausted",
                metadata={"reason": "Лимит попыток восстановления исчерпан."}
            )

        # 2. Проверка явных флагов в метаданных и данных
        if step_meta.get("recoverable") is False or step_meta.get("retryable") is False:
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.FATAL,
                strategy="abort",
                metadata={"reason": "Шаг явно помечен как невосстановимый."}
            )

        if result_data.get("fatal") is True or result_data.get("recoverable") is False:
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.FATAL,
                strategy="abort",
                metadata={"reason": "Результат явно помечен как фатальный."}
            )

        # 3. Non-recoverable: Отмена пользователем
        if any(p in text_lower for p in self.USER_CANCEL_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.USER_CANCELLED,
                strategy="abort",
                metadata={"reason": "Действие отменено пользователем."}
            )

        # 4. Non-recoverable: Нарушение безопасности (path traversal, запрещённые операции)
        if any(p in text_lower for p in self.SECURITY_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.SECURITY_VIOLATION,
                strategy="abort",
                metadata={"reason": "Обнаружено нарушение политики безопасности."}
            )

        # 5. Non-recoverable: Неподдерживаемое действие / отсутствующие обязательные параметры
        if any(p in text_lower for p in self.UNSUPPORTED_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=False,
                category=ErrorCategory.UNSUPPORTED,
                strategy="abort",
                metadata={"reason": "Действие не поддерживается или не указаны обязательные параметры."}
            )

        # 6. Recoverable: Блокировка файла (PermissionError, file locked)
        if any(p in text_lower for p in self.FILE_LOCK_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=True,
                category=ErrorCategory.FILE_LOCKED,
                strategy="retry",
                metadata={"reason": "Файл временно заблокирован другим процессом."}
            )

        # 7. Recoverable: Ресурс временно занят (VRAM/GPU/OOM)
        if any(p in text_lower for p in self.RESOURCE_BUSY_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=True,
                category=ErrorCategory.RESOURCE_BUSY,
                strategy="retry",
                metadata={"reason": "Аппаратный ресурс временно занят."}
            )

        # 8. Recoverable: Временные сбои (Timeout, connection error, transient)
        if any(p in text_lower for p in self.TRANSIENT_PATTERNS):
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=True,
                category=ErrorCategory.TRANSIENT,
                strategy="retry",
                metadata={"reason": "Кратковременный сбой сети или сервиса."}
            )

        # 9. Recoverable: Явные флаги recoverable/retryable
        if step_meta.get("retryable") is True or step_meta.get("recoverable") is True or result_data.get("recoverable") is True:
            return ErrorContext(
                step_id=step_id,
                action=action,
                error=err_msg or msg,
                message=msg,
                subagent=subagent,
                target=target,
                details=details,
                attempt=attempt,
                max_attempts=max_attempts,
                is_recoverable=True,
                category=ErrorCategory.TRANSIENT,
                strategy="retry",
                metadata={"reason": "Шаг явно помечен как допускающий повтор."}
            )

        # 10. По умолчанию: неклассифицированная ошибка считается non-recoverable в целях безопасности
        return ErrorContext(
            step_id=step_id,
            action=action,
            error=err_msg or msg,
            message=msg,
            subagent=subagent,
            target=target,
            details=details,
            attempt=attempt,
            max_attempts=max_attempts,
            is_recoverable=False,
            category=ErrorCategory.UNKNOWN,
            strategy="abort",
            metadata={"reason": "Неизвестная ошибка; повтор не разрешён политикой безопасности."}
        )


class SelfHealingManager:
    """
    Координатор механизма восстановления ошибок (Self-Healing).
    Управляет счетчиками попыток, историей восстановления и предотвращает циклы.
    """

    def __init__(
        self,
        default_max_retries: int = 1,
        max_total_recoveries: int = 5,
        classifier: Optional[ErrorClassifier] = None
    ):
        self.default_max_retries = max(0, int(default_max_retries))
        self.max_total_recoveries = max(0, int(max_total_recoveries))
        self.classifier = classifier or ErrorClassifier()
        self.total_recoveries = 0

    def reset(self) -> None:
        """Сбрасывает глобальный счетчик восстановлений плана."""
        self.total_recoveries = 0

    def can_attempt_recovery(self) -> bool:
        """Проверяет, не исчерпан ли глобальный лимит восстановлений плана."""
        return self.total_recoveries < self.max_total_recoveries

    def record_recovery(self) -> None:
        """Фиксирует факт выполнения попытки восстановления."""
        self.total_recoveries += 1

    def get_step_max_retries(self, step: Any) -> int:
        """Определяет допустимое количество retry для конкретного шага."""
        step_dict = step.to_dict() if hasattr(step, "to_dict") else (dict(step) if isinstance(step, dict) else {})
        step_meta = getattr(step, "metadata", {}) or step_dict.get("metadata", {})
        if "max_retries" in step_meta and isinstance(step_meta["max_retries"], int):
            return max(0, step_meta["max_retries"])
        return self.default_max_retries

    def classify_error(
        self,
        step: Any,
        result: Any,
        attempt: int,
        max_attempts: int
    ) -> ErrorContext:
        """Классифицирует ошибку и возвращает структурированный ErrorContext."""
        return self.classifier.classify(step, result, attempt=attempt, max_attempts=max_attempts)
