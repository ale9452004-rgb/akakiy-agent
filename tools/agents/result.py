"""
Модуль унифицированного результата выполнения Sub-Agent'а (AgentResult).

Обеспечивает:
- единое представление статуса выполнения (success/error);
- текстовое сообщение для пользователя или оркестратора;
- список созданных или модифицированных файлов (created_files);
- произвольные структурированные данные (data);
- поддержку dict-like интерфейса для 100% обратной совместимости с существующими обработчиками.
"""

from typing import Any, Dict, List, Optional


class AgentResult:
    """
    Стандартизированный результат работы SubAgent.
    """

    def __init__(
        self,
        success: bool,
        message: str = "",
        created_files: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        self.success = bool(success)
        self.message = str(message)
        self.created_files = list(created_files) if created_files else []
        self.data = dict(data) if data is not None else {}
        self.error = str(error) if error is not None else (None if self.success else self.message)

    @classmethod
    def ok(
        cls,
        message: str = "",
        created_files: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> "AgentResult":
        """
        Фабричный метод для создания успешного результата.
        """
        return cls(
            success=True,
            message=message,
            created_files=created_files,
            data=data,
            error=None
        )

    @classmethod
    def fail(
        cls,
        error: str,
        message: str = "",
        data: Optional[Dict[str, Any]] = None
    ) -> "AgentResult":
        """
        Фабричный метод для создания неуспешного результата.
        """
        msg = message if message else error
        return cls(
            success=False,
            message=msg,
            created_files=None,
            data=data,
            error=error
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует результат в стандартный словарь.
        """
        res: Dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "created_files": list(self.created_files),
            "data": dict(self.data)
        }
        if self.error is not None:
            res["error"] = self.error
        return res

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        files_info = f", files={len(self.created_files)}" if self.created_files else ""
        err_info = f", error='{self.error}'" if self.error else ""
        return f"<AgentResult [{status}] msg='{self.message}'{files_info}{err_info}>"
