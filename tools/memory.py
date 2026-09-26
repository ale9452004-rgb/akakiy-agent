"""
Модуль памяти и контекста Акакия (MemoryManager).
Обеспечивает:
1. Долговременную память (Long-Term Memory): сохранение фактов, предпочтений и заметок в data/memory.json.
2. Защиту от мусора и шума (фильтрация трейсбеков, дампов ошибок, пустых строк).
3. Защиту от дублирования записей (акустическая и текстовая нормализация).
4. Краткосрочную память (Short-Term Memory): скользящее окно ходов диалога для сохранения контекста.
5. Инструменты для вызова через Agent, CLI, GUI, Voice и Registry.
"""

from collections import deque
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from config import PROJECT_PATH
from tools.persistent_memory import (
    MemoryEntry,
    PersistentMemory,
    MemoryType,
    MemorySource,
    normalize_for_comparison,
    is_valid_memory_text,
    DEFAULT_PERSISTENT_MEMORY_FILE,
)

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_FILE = DEFAULT_PERSISTENT_MEMORY_FILE


class MemoryManager:
    """
    Менеджер краткосрочной и долговременной памяти Акакия.
    Использует PersistentMemory как слой долговременного хранения.
    """

    def __init__(
        self,
        storage_path: Optional[Union[str, Path]] = None,
        storage_file: Optional[Union[str, Path]] = None,
        max_turns: int = 10
    ):
        actual_path = storage_path or storage_file
        self.storage_path = Path(actual_path) if actual_path else DEFAULT_MEMORY_FILE
        self.max_turns = max_turns
        self.short_term: deque = deque(maxlen=max_turns * 2)
        self._ensure_storage_dir()
        self.persistent = PersistentMemory(storage_path=self.storage_path)

    def _ensure_storage_dir(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Не удалось создать директорию памяти {self.storage_path.parent}: {e}")

    @property
    def memories(self) -> List[Any]:
        """Доступ к списку записей долговременной памяти."""
        return self.persistent.entries

    @memories.setter
    def memories(self, value: List[Any]) -> None:
        self.persistent.entries = value

    def reload(self):
        """Перечитывает долговременную память с диска."""
        self.persistent.reload()

    def _load_memories(self) -> List[Dict[str, Any]]:
        """Загружает долговременную память с диска."""
        return [dict(e) for e in self.persistent._load_from_disk()]

    def _save_memories(self) -> bool:
        """Атомарно сохраняет долговременную память на диск."""
        return self.persistent.save()

    # =========================================================================
    # Долговременная память (Long-Term Memory)
    # =========================================================================

    def remember(
        self,
        text: str,
        category: str = "general",
        source: str = MemorySource.USER,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Сохраняет факт или предпочтение в долговременную память.
        Проверяет на технический мусор и дубликаты.
        """
        return self.persistent.create(
            content=text,
            type=category,
            category=category,
            source=source,
            tags=tags,
            metadata=metadata
        )

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все сохранённые записи памяти."""
        return self.persistent.get_all()

    def recall(self, query: str = "") -> List[Dict[str, Any]]:
        """Ищет записи или возвращает все (псевдоним для search/get_all)."""
        if query and str(query).strip():
            return self.search(str(query).strip())
        return self.get_all()

    def search(
        self,
        query: str = "",
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Поиск записей в памяти по ключевым словам и фильтрам."""
        return self.persistent.search(query=query, type=type, tags=tags, source=source)

    def forget(self, target: Union[int, str]) -> Tuple[bool, str]:
        """
        Удаляет запись из памяти по ID или текстовому совпадению.
        """
        return self.persistent.delete(target)

    def clear_long_term(self) -> Tuple[bool, str]:
        """Очищает всю долговременную память."""
        return self.persistent.clear()

    def get_entry(self, entry_id: Union[int, str]) -> Optional[MemoryEntry]:
        """Возвращает структурированную запись памяти по ID."""
        return self.persistent.get(entry_id)

    def update_entry(
        self,
        entry_id: Union[int, str],
        content: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MemoryEntry]]:
        """Безопасно обновляет существующую запись памяти."""
        return self.persistent.update(
            entry_id=entry_id,
            content=content,
            type=type,
            tags=tags,
            metadata=metadata,
            source=source
        )

    def delete_entry(self, entry_id: Union[int, str]) -> Tuple[bool, str]:
        """Удаляет запись памяти по ID."""
        return self.persistent.delete(entry_id)

    def remember_result(
        self,
        result: Any,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = MemorySource.AGENT
    ) -> Tuple[bool, str, Optional[MemoryEntry]]:
        """Явно сохраняет результат задачи в долговременную память."""
        return self.persistent.remember_result(
            result=result,
            title=title,
            tags=tags,
            source=source
        )

    def format_memories_summary(self, memory_list: Optional[List[Dict[str, Any]]] = None) -> str:
        """Форматирует список записей в наглядный текст для пользователя."""
        records = memory_list if memory_list is not None else self.memories
        if not records:
            return "В долговременной памяти пока нет сохранённых записей."

        lines = ["Сохранённые записи в памяти:"]
        for m in records:
            m_id = m.get("id", "?")
            m_text = m.get("text", "")
            lines.append(f"  {m_id}. {m_text}")
        return "\n".join(lines)

    def format_for_system_prompt(self) -> str:
        """Форматирует факты для инъекции в системный промпт модели."""
        if not self.memories:
            return ""
        lines = ["Сохранённые факты и знания (долговременная память):"]
        for m in self.memories:
            lines.append(f"- {m.get('text', '')}")
        return "\n".join(lines)

    # =========================================================================
    # Краткосрочная память диалога (Short-Term Memory / Sliding Window)
    # =========================================================================

    def add_turn(self, user_query: str, assistant_response: str, tool_name: Optional[str] = None):
        """
        Фиксирует завершённый ход диалога в краткосрочной памяти.
        """
        if not user_query or not str(user_query).strip():
            return

        ts = datetime.now().strftime("%H:%M:%S")
        self.short_term.append({
            "role": "user",
            "content": str(user_query).strip(),
            "timestamp": ts
        })

        resp_text = str(assistant_response or "").strip()
        if not resp_text:
            resp_text = f"Инструмент {tool_name} выполнен." if tool_name else "Запрос обработан."

        # Ограничиваем объём одной реплики в краткосрочной памяти (макс 600 символов)
        if len(resp_text) > 600:
            resp_text = resp_text[:600] + "..."

        self.short_term.append({
            "role": "assistant",
            "content": resp_text,
            "tool": tool_name,
            "timestamp": ts
        })

    def get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Возвращает последние сообщения краткосрочной памяти."""
        items = list(self.short_term)
        return items[-limit:] if limit > 0 else items

    def get_recent_turns(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Возвращает завершённые ходы диалога в формате:
        [{"user": "...", "assistant": "...", "tool": ...}]
        """
        items = list(self.short_term)
        turns = []
        i = 0
        while i < len(items):
            if items[i].get("role") == "user":
                user_msg = items[i].get("content", "")
                asst_msg = ""
                tool_val = None
                if i + 1 < len(items) and items[i + 1].get("role") == "assistant":
                    asst_msg = items[i + 1].get("content", "")
                    tool_val = items[i + 1].get("tool")
                    i += 1
                turns.append({
                    "user": user_msg,
                    "assistant": asst_msg,
                    "tool": tool_val
                })
            i += 1
        return turns[-limit:] if limit > 0 else turns

    def format_short_term_context(self, limit: int = 6) -> str:
        """Форматирует последние ходы для информирования LLM о контексте предыдущих реплик."""
        history = self.get_recent_history(limit)
        if not history:
            return ""

        lines = ["Контекст предыдущего диалога:"]
        for item in history:
            role_label = "Пользователь" if item.get("role") == "user" else "Акакий"
            content = item.get("content", "")
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    def clear_short_term(self):
        """Очищает историю текущей сессии."""
        self.short_term.clear()


# =============================================================================
# Singleton и инструменты для Registry / Agent
# =============================================================================

_global_memory_manager: Optional[MemoryManager] = None


def get_memory_manager(storage_path: Optional[Union[str, Path]] = None) -> MemoryManager:
    """Возвращает глобальный синглтон MemoryManager."""
    global _global_memory_manager
    if _global_memory_manager is None or storage_path is not None:
        _global_memory_manager = MemoryManager(storage_path=storage_path)
    return _global_memory_manager


def remember(text: str) -> Dict[str, Any]:
    """Инструмент: сохраняет полезный факт или предпочтение в долговременную память."""
    mgr = get_memory_manager()
    success, msg, entry = mgr.remember(text)
    return {
        "success": success,
        "message": msg,
        "entry": entry
    }


def recall_memory(query: str = "") -> Dict[str, Any]:
    """Инструмент: ищет или перечисляет факты из долговременной памяти."""
    mgr = get_memory_manager()
    if query and query.strip():
        results = mgr.search(query.strip())
        summary = mgr.format_memories_summary(results)
        return {
            "success": True,
            "count": len(results),
            "query": query.strip(),
            "message": summary,
            "memories": results
        }
    else:
        results = mgr.get_all()
        summary = mgr.format_memories_summary(results)
        return {
            "success": True,
            "count": len(results),
            "message": summary,
            "memories": results
        }


def forget_memory(target: str) -> Dict[str, Any]:
    """Инструмент: удаляет запись из долговременной памяти по номеру или фрагменту текста."""
    mgr = get_memory_manager()
    success, msg = mgr.forget(target)
    return {
        "success": success,
        "message": msg
    }


def update_memory(
    target: Union[int, str],
    content: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Инструмент: обновляет существующую запись в долговременной памяти."""
    mgr = get_memory_manager()
    success, msg, entry = mgr.update_entry(
        entry_id=target,
        content=content,
        type=category,
        tags=tags
    )
    return {
        "success": success,
        "message": msg,
        "entry": entry
    }


__all__ = [
    "MemoryManager",
    "get_memory_manager",
    "remember",
    "recall_memory",
    "forget_memory",
    "update_memory",
    "MemoryEntry",
    "PersistentMemory",
    "MemoryType",
    "MemorySource",
    "normalize_for_comparison",
    "is_valid_memory_text",
    "DEFAULT_MEMORY_FILE",
    "DEFAULT_PERSISTENT_MEMORY_FILE",
]

