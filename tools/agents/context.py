"""
Модуль контекста выполнения Sub-Agent'а (AgentContext).

Версия 2.0 (Multi-Agent Foundation Contract):
- структурированные атрибуты задачи (task_id, task_type, status, instruction, root_task_id);
- хранение файлов и их метаданных (files, file_metadata, add_file, get_file_metadata);
- передача результатов предыдущих шагов (previous_results, add_result, get_last_result);
- метаданные параметров и протокол сопоставления (__getitem__, __setitem__, __contains__);
- иерархическая связь parent/child с безопасной изоляцией (parent_context, parent_agent, create_child_context);
- сериализация в dict и JSON (to_dict, from_dict, to_json, from_json);
- 100% обратная совместимость с SubAgent и ImageAgent API.
"""

import copy
import json
import uuid
from typing import Any, Dict, List, Optional, Union


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
        parent_agent: Optional[Any] = None,
        task_id: Optional[str] = None,
        task_type: Optional[str] = None,
        instruction: Optional[str] = None,
        status: str = "pending",
        root_task_id: Optional[str] = None,
        file_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        parent_context: Optional["AgentContext"] = None,
        recovery_history: Optional[List[Dict[str, Any]]] = None,
    ):
        self.task_id = str(task_id) if task_id else str(uuid.uuid4())
        self.root_task_id = str(root_task_id) if root_task_id else self.task_id
        self.task = str(task) if task is not None else ""
        self.task_type = str(task_type) if task_type is not None else None
        self.instruction = str(instruction) if instruction is not None else None
        self.status = str(status) if status is not None else "pending"

        self.files: List[str] = [str(f) for f in files] if files else []
        self.file_metadata: Dict[str, Dict[str, Any]] = (
            {str(k): dict(v) for k, v in file_metadata.items()} if file_metadata else {}
        )
        for f in self.files:
            if f not in self.file_metadata:
                self.file_metadata[f] = {}

        self.previous_results: List[Any] = list(previous_results) if previous_results else []
        self._results_by_agent: Dict[str, List[Any]] = {}

        for res in self.previous_results:
            self._index_result(res)

        self.metadata: Dict[str, Any] = dict(metadata) if metadata is not None else {}
        self.parent_agent = parent_agent
        self.parent_context = parent_context
        self._recovery_history: List[Dict[str, Any]] = list(recovery_history) if recovery_history else []

    def _index_result(self, result: Any, agent_name: Optional[str] = None) -> None:
        """Внутренний метод индексации результата по имени агента."""
        name = agent_name
        if not name:
            if isinstance(result, dict):
                name = result.get("agent") or result.get("agent_name")
            elif hasattr(result, "agent_name") and getattr(result, "agent_name"):
                name = str(getattr(result, "agent_name"))
            elif hasattr(result, "agent") and getattr(result, "agent"):
                name = str(getattr(result, "agent"))
        if name:
            self._results_by_agent.setdefault(str(name), []).append(result)

    # =========================================================================
    # Работа с файлами и их метаданными
    # =========================================================================

    def add_file(self, file_path: str, **metadata) -> None:
        """
        Добавляет путь к файлу в контекст и опционально обновляет его метаданные.
        Если файл уже добавлен, дубликат не создаётся, но метаданные обновляются.
        """
        if not file_path:
            return
        path_str = str(file_path)
        if path_str not in self.files:
            self.files.append(path_str)
        if path_str not in self.file_metadata:
            self.file_metadata[path_str] = {}
        if metadata:
            self.file_metadata[path_str].update(metadata)

    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Возвращает копию словаря метаданных для указанного файла."""
        return dict(self.file_metadata.get(str(file_path), {}))

    def set_file_metadata(self, file_path: str, metadata: Dict[str, Any]) -> None:
        """Устанавливает метаданные для файла (добавляя файл в список, если его там нет)."""
        if not file_path:
            return
        path_str = str(file_path)
        if path_str not in self.files:
            self.files.append(path_str)
        self.file_metadata[path_str] = dict(metadata) if metadata else {}

    def remove_file(self, file_path: str) -> bool:
        """Удаляет файл и его метаданные из контекста. Возвращает True, если файл был удалён."""
        path_str = str(file_path)
        removed = False
        if path_str in self.files:
            self.files.remove(path_str)
            removed = True
        self.file_metadata.pop(path_str, None)
        return removed

    def has_file(self, file_path: str) -> bool:
        """Проверяет наличие файла в контексте."""
        return str(file_path) in self.files

    # =========================================================================
    # Передача и доступ к результатам предыдущих агентов
    # =========================================================================

    def add_result(self, result: Any, agent_name: Optional[str] = None) -> None:
        """
        Добавляет результат работы предыдущего агента в контекст.
        Если передан agent_name, индексирует результат для быстрого поиска.
        """
        self.previous_results.append(result)
        self._index_result(result, agent_name=agent_name)

    def get_last_result(self, agent_name: Optional[str] = None) -> Optional[Any]:
        """
        Возвращает последний результат выполнения.
        Если указан agent_name, возвращает последний результат указанного агента.
        """
        if agent_name:
            results = self._results_by_agent.get(agent_name)
            if results:
                return results[-1]
            return None
        return self.previous_results[-1] if self.previous_results else None

    def get_results_from(self, agent_name: str) -> List[Any]:
        """Возвращает список всех результатов конкретного агента."""
        return list(self._results_by_agent.get(str(agent_name), []))

    @property
    def artifacts(self) -> List[Any]:
        """Все артефакты, полученные из предыдущих результатов субагентов."""
        accumulated: List[Any] = []
        for r in self.previous_results:
            if hasattr(r, "artifacts") and r.artifacts:
                accumulated.extend(r.artifacts)
            elif isinstance(r, dict) and "artifacts" in r and isinstance(r["artifacts"], list):
                accumulated.extend(r["artifacts"])
        return accumulated

    def record_recovery_attempt(self, attempt_data: Union[Dict[str, Any], Any]) -> None:
        """
        Фиксирует попытку восстановления в истории контекста (Self-Healing).
        """
        rec = attempt_data.to_dict() if hasattr(attempt_data, "to_dict") and callable(attempt_data.to_dict) else dict(attempt_data)
        self._recovery_history.append(rec)
        if "recovery_history" in self.metadata:
            self.metadata["recovery_history"].append(rec)

    @property
    def recovery_history(self) -> List[Dict[str, Any]]:
        """История попыток восстановления ошибок (Self-Healing)."""
        if self._recovery_history:
            return list(self._recovery_history)
        return list(self.metadata.get("recovery_history", []))

    # =========================================================================
    # Метаданные и параметры (dict-like protocol)
    # =========================================================================

    def get(self, key: str, default: Any = None) -> Any:
        """Удобное получение значения из metadata по ключу."""
        return self.metadata.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение в metadata."""
        self.metadata[key] = value

    def update_metadata(self, mapping: Dict[str, Any]) -> None:
        """Пакетно обновляет metadata."""
        if mapping and isinstance(mapping, dict):
            self.metadata.update(mapping)

    def has_metadata(self, key: str) -> bool:
        """Проверяет наличие ключа в metadata."""
        return key in self.metadata

    def __getitem__(self, key: str) -> Any:
        return self.metadata[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.metadata

    # =========================================================================
    # Управление состоянием задачи
    # =========================================================================

    def mark_completed(self, status: str = "completed") -> None:
        """Отмечает успешное завершение контекста задачи."""
        self.status = status

    def mark_failed(self, status: str = "failed") -> None:
        """Отмечает сбой контекста задачи."""
        self.status = status

    # =========================================================================
    # Иерархическая связь parent / child agents
    # =========================================================================

    def create_child_context(
        self,
        task: str = "",
        files: Optional[List[str]] = None,
        task_type: Optional[str] = None,
        instruction: Optional[str] = None,
        inherit_files: bool = False,
        inherit_metadata: bool = True,
        inherit_results: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        child_agent: Optional[Any] = None,
    ) -> "AgentContext":
        """
        Создаёт изолированный дочерний контекст для выполнения подзадачи в multi-agent конвейере.

        - root_task_id наследуется от родителя для сквозной трассировки;
        - parent_context указывает на текущий контекст;
        - parent_agent указывает на child_agent или родительского агента;
        - метаданные и результаты наследуются с изоляцией (глубокое копирование).
        """
        child_files: List[str] = []
        child_file_metadata: Dict[str, Dict[str, Any]] = {}

        if inherit_files:
            child_files.extend(self.files)
            child_file_metadata = {k: dict(v) for k, v in self.file_metadata.items()}

        if files:
            for f in files:
                f_str = str(f)
                if f_str not in child_files:
                    child_files.append(f_str)
                if f_str not in child_file_metadata:
                    child_file_metadata[f_str] = {}

        child_metadata: Dict[str, Any] = {}
        if inherit_metadata:
            try:
                child_metadata = copy.deepcopy(self.metadata)
            except Exception:
                child_metadata = dict(self.metadata)

        if metadata:
            child_metadata.update(metadata)

        child_results: List[Any] = []
        if inherit_results:
            child_results = list(self.previous_results)

        return AgentContext(
            task=task,
            files=child_files,
            previous_results=child_results,
            metadata=child_metadata,
            parent_agent=child_agent or self.parent_agent,
            task_id=str(uuid.uuid4()),
            task_type=task_type or self.task_type,
            instruction=instruction,
            status="pending",
            root_task_id=self.root_task_id,
            file_metadata=child_file_metadata,
            parent_context=self,
            recovery_history=list(self.recovery_history),
        )

    def copy(self) -> "AgentContext":
        """Создаёт независимую копию текущего контекста."""
        return self.from_dict(
            self.to_dict(),
            parent_agent=self.parent_agent,
            parent_context=self.parent_context
        )

    # =========================================================================
    # Сериализация и десериализация
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """
        Сериализует контекст в словарь.
        parent_agent и parent_context исключаются во избежание циклических ссылок.
        """
        serialized_results = []
        for res in self.previous_results:
            if hasattr(res, "to_dict") and callable(res.to_dict):
                try:
                    serialized_results.append(res.to_dict())
                except Exception:
                    serialized_results.append(str(res))
            elif isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                serialized_results.append(res)
            else:
                serialized_results.append(str(res))

        res: Dict[str, Any] = {
            "task_id": self.task_id,
            "root_task_id": self.root_task_id,
            "task": self.task,
            "task_type": self.task_type,
            "instruction": self.instruction,
            "status": self.status,
            "files": list(self.files),
            "file_metadata": {k: dict(v) for k, v in self.file_metadata.items()},
            "previous_results": serialized_results,
            "metadata": dict(self.metadata),
        }
        if self.recovery_history:
            res["recovery_history"] = self.recovery_history
        return res

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        parent_agent: Optional[Any] = None,
        parent_context: Optional["AgentContext"] = None
    ) -> "AgentContext":
        """
        Создаёт экземпляр AgentContext из словаря.
        Поддерживает как словари версии v2, так и старый формат v1 (100% совместимость).
        """
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")

        return cls(
            task=data.get("task", ""),
            files=data.get("files"),
            previous_results=data.get("previous_results"),
            metadata=data.get("metadata"),
            parent_agent=parent_agent,
            task_id=data.get("task_id"),
            task_type=data.get("task_type"),
            instruction=data.get("instruction"),
            status=data.get("status", "pending"),
            root_task_id=data.get("root_task_id"),
            file_metadata=data.get("file_metadata"),
            parent_context=parent_context,
            recovery_history=data.get("recovery_history"),
        )

    def to_json(self, indent: Optional[int] = None) -> str:
        """Сериализует контекст в JSON-строку."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(
        cls,
        json_str: str,
        parent_agent: Optional[Any] = None,
        parent_context: Optional["AgentContext"] = None
    ) -> "AgentContext":
        """Создаёт экземпляр AgentContext из JSON-строки."""
        if not isinstance(json_str, str):
            raise TypeError(f"Ожидается str, получен {type(json_str)}")
        return cls.from_dict(
            json.loads(json_str),
            parent_agent=parent_agent,
            parent_context=parent_context
        )

    def __repr__(self) -> str:
        task_preview = (self.task[:30] + "...") if len(self.task) > 30 else self.task
        tid = self.task_id[:8] if self.task_id else "none"
        return (
            f"<AgentContext id='{tid}' task='{task_preview}' "
            f"status='{self.status}' files={len(self.files)} meta={len(self.metadata)}>"
        )
