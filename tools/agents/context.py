"""
Модуль контекста выполнения Sub-Agent'а (AgentContext).

Обеспечивает:
- передачу целевой задачи / инструкции агенту;
- передачу списка связанных файлов проекта;
- передачу истории / результатов предыдущих шагов;
- хранение произвольных метаданных и параметров конфигурации;
- опциональную ссылку на родительского агента (parent_agent).
"""

from typing import Any, Dict, List, Optional


class AgentContext:
    """
    Контекст задачи, передаваемый в SubAgent.run().
    """

    def __init__(
        self,
        task: str = "",
        files: Optional[List[str]] = None,
        previous_results: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_agent: Optional[Any] = None
    ):
        self.task = str(task) if task is not None else ""
        self.files = [str(f) for f in files] if files else []
        self.previous_results = list(previous_results) if previous_results else []
        self.metadata = dict(metadata) if metadata is not None else {}
        self.parent_agent = parent_agent

    def add_file(self, file_path: str) -> None:
        """Добавляет путь к файлу в контекст, если он ещё не добавлен."""
        if file_path and str(file_path) not in self.files:
            self.files.append(str(file_path))

    def get(self, key: str, default: Any = None) -> Any:
        """Удобное получение значения из metadata по ключу."""
        return self.metadata.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует контекст в словарь (без parent_agent во избежание циклических ссылок)."""
        return {
            "task": self.task,
            "files": list(self.files),
            "previous_results": list(self.previous_results),
            "metadata": dict(self.metadata)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], parent_agent: Optional[Any] = None) -> "AgentContext":
        """Создаёт экземпляр AgentContext из словаря."""
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")
        return cls(
            task=data.get("task", ""),
            files=data.get("files"),
            previous_results=data.get("previous_results"),
            metadata=data.get("metadata"),
            parent_agent=parent_agent
        )

    def __repr__(self) -> str:
        task_preview = (self.task[:30] + "...") if len(self.task) > 30 else self.task
        return f"<AgentContext task='{task_preview}' files={len(self.files)} meta={len(self.metadata)}>"
