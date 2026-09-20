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

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_FILE = PROJECT_PATH / "data" / "memory.json"


def normalize_for_comparison(text: str) -> str:
    """Нормализует текст для выявления дубликатов."""
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_valid_memory_text(text: str) -> Tuple[bool, str]:
    """
    Проверяет текст на пригодность для долговременной памяти:
    отсекает пустые строки, системный мусор, трейсбеки и дампы ошибок.
    """
    if not text or not isinstance(text, str):
        return False, "Текст памяти не может быть пустым."

    stripped = text.strip()
    if len(stripped) < 3:
        return False, "Слишком короткий текст для сохранения в память (минимум 3 символа)."

    if len(stripped) > 500:
        return False, "Текст слишком длинный (максимум 500 символов). Для больших данных используйте файлы проекта."

    # Проверка на наличие букв/цифр
    if not re.search(r"[a-zA-Zа-яА-Я0-9]", stripped):
        return False, "Текст должен содержать осмысленные слова или цифры."

    # Фильтрация трейсбеков Python
    if re.search(r"traceback\s+\(most recent call last\)", stripped, re.IGNORECASE):
        return False, "Текст похож на системный трейсбек и не подходит для долговременной памяти."

    if re.search(r'File\s+"[^"]+",\s+line\s+\d+', stripped):
        return False, "Текст содержит строки трейсбека файлов и не подходит для долговременной памяти."

    # Фильтрация типичных сообщений об исключениях
    if re.search(r"\b(SyntaxError|ImportError|TypeError|ValueError|IndexError|KeyError|AttributeError|ZeroDivisionError|RuntimeError|FileNotFoundError|PermissionError|OSError|Exception)\s*:", stripped):
        return False, "Текст похож на ошибку выполнения программы, а не на факт для запоминания."

    # Фильтрация сырых дампов разметки или JSON
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            json.loads(stripped)
            return False, "Текст содержит сырой JSON-дамп и отклонён как технический мусор."
        except Exception:
            pass

    if re.search(r"^<(?:\?xml|!DOCTYPE|html|div|xml|body|[a-zA-Z0-9_-]+)", stripped, re.IGNORECASE) and stripped.endswith(">"):
        return False, "Текст содержит сырой HTML/XML код и отклонён как технический мусор."

    # Фильтрация дампов шестнадцатеричных байтов
    if re.search(r"(?:0x[0-9a-fA-F]{2,}\s*){4,}", stripped):
        return False, "Текст содержит бинарный/hex дамп и отклонён."

    return True, "OK"


class MemoryManager:
    """
    Менеджер краткосрочной и долговременной памяти Акакия.
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
        self.memories: List[Dict[str, Any]] = self._load_memories()

    def _ensure_storage_dir(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Не удалось создать директорию памяти {self.storage_path.parent}: {e}")

    def _load_memories(self) -> List[Dict[str, Any]]:
        """Загружает долговременную память с диска."""
        if not self.storage_path.exists():
            return []
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("memories", [])
                elif isinstance(data, list):
                    return data
                return []
        except Exception as e:
            logger.error(f"Ошибка чтения файла памяти {self.storage_path}: {e}")
            return []

    def _save_memories(self) -> bool:
        """Атомарно сохраняет долговременную память на диск."""
        self._ensure_storage_dir()
        payload = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "memories": self.memories
        }
        try:
            tmp_path = self.storage_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            # Атомарная замена
            if self.storage_path.exists():
                os.replace(tmp_path, self.storage_path)
            else:
                tmp_path.rename(self.storage_path)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения файла памяти {self.storage_path}: {e}")
            return False

    # =========================================================================
    # Долговременная память (Long-Term Memory)
    # =========================================================================

    def remember(self, text: str, category: str = "general") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Сохраняет факт или предпочтение в долговременную память.
        Проверяет на технический мусор и дубликаты.
        """
        valid, msg = is_valid_memory_text(text)
        if not valid:
            return False, f"Не удалось сохранить: {msg}", None

        clean_text = text.strip()
        norm_text = normalize_for_comparison(clean_text)

        # Проверка на дубликаты
        for m in self.memories:
            existing_norm = normalize_for_comparison(m.get("text", ""))
            if norm_text == existing_norm:
                return False, f"Эта информация уже есть в памяти (запись #{m['id']}): \"{m['text']}\"", m

        # Присваиваем следующий ID
        next_id = max([m.get("id", 0) for m in self.memories], default=0) + 1
        entry = {
            "id": next_id,
            "text": clean_text,
            "category": category,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        self.memories.append(entry)
        saved = self._save_memories()
        if not saved:
            return False, "Не удалось записать память на диск.", None

        return True, f"Запомнил: \"{clean_text}\" (запись #{next_id})", entry

    def get_all(self) -> List[Dict[str, Any]]:
        """Возвращает все сохранённые записи памяти."""
        return list(self.memories)

    def recall(self, query: str = "") -> List[Dict[str, Any]]:
        """Ищет записи или возвращает все (псевдоним для search/get_all)."""
        if query and str(query).strip():
            return self.search(str(query).strip())
        return self.get_all()

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Поиск записей в памяти по ключевым словам."""
        if not query:
            return self.get_all()

        words = [w for w in normalize_for_comparison(query).split() if len(w) > 1]
        if not words:
            return []

        results = []
        for m in self.memories:
            norm_m = normalize_for_comparison(m.get("text", ""))
            if all(w in norm_m for w in words):
                results.append(m)
            elif any(w in norm_m for w in words):
                results.append(m)
        return results

    def forget(self, target: Union[int, str]) -> Tuple[bool, str]:
        """
        Удаляет запись из памяти по ID или текстовому совпадению.
        """
        if not target and target != 0:
            return False, "Укажите номер или текст записи для удаления."

        # Попытка удалить по ID
        target_id = None
        if isinstance(target, int):
            target_id = target
        else:
            t_str = str(target).strip()
            # Проверяем, число ли это ("1", "#1", "№1")
            id_match = re.match(r"^[#№]?(\d+)$", t_str)
            if id_match:
                target_id = int(id_match.group(1))

        if target_id is not None:
            for idx, m in enumerate(self.memories):
                if m.get("id") == target_id:
                    removed = self.memories.pop(idx)
                    self._save_memories()
                    return True, f"Удалил запись #{removed['id']} из памяти: \"{removed['text']}\""
            # Если по ID не найдено, число может быть фрагментом текста (напр. токен, порт)

        # Поиск по текстовому совпадению
        target_norm = normalize_for_comparison(str(target))
        if not target_norm:
            return False, "Укажите непустой текст для удаления."

        matching_indices = []
        for idx, m in enumerate(self.memories):
            norm_m = normalize_for_comparison(m.get("text", ""))
            if target_norm in norm_m:
                matching_indices.append(idx)

        if not matching_indices:
            if target_id is not None:
                return False, f"Запись с номером #{target_id} не найдена в памяти."
            return False, f"Запись, содержащая \"{target}\", не найдена в памяти."

        if len(matching_indices) == 1:
            removed = self.memories.pop(matching_indices[0])
            self._save_memories()
            return True, f"Удалил запись #{removed['id']} из памяти: \"{removed['text']}\""

        # Несколько совпадений
        matched_entries = [self.memories[i] for i in matching_indices]
        entries_str = ", ".join(f"#{m['id']} (\"{m['text'][:30]}...\")" for m in matched_entries[:3])
        return False, f"Найдено несколько записей: {entries_str}. Укажите точный номер записи (например, 'забудь: #{matched_entries[0]['id']}')."

    def clear_long_term(self) -> Tuple[bool, str]:
        """Очищает всю долговременную память."""
        count = len(self.memories)
        self.memories.clear()
        self._save_memories()
        return True, f"Долговременная память очищена (удалено записей: {count})."

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
