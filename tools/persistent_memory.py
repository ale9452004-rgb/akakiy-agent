"""
Модуль постоянной долговременной памяти Акакия (Persistent Memory).

Обеспечивает:
- структурированную модель записи памяти (MemoryEntry);
- типы и источники записей памяти (MemoryType, MemorySource);
- изолированный слой долговременного хранения (PersistentMemory), отделённый от AgentContext и runtime history диалога;
- безопасные операции CRUD (create, read, update, delete);
- поиск и фильтрацию по тексту, типам, тегам и источникам;
- надёжную атомарную сериализацию и восстановление после перезапуска приложения;
- сохранение только явно переданных фактов и результатов.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from config import PROJECT_PATH

logger = logging.getLogger(__name__)

DEFAULT_PERSISTENT_MEMORY_FILE = PROJECT_PATH / "data" / "memory.json"


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
    if re.search(
        r"\b(SyntaxError|ImportError|TypeError|ValueError|IndexError|KeyError|AttributeError|"
        r"ZeroDivisionError|RuntimeError|FileNotFoundError|PermissionError|OSError|Exception)\s*:",
        stripped
    ):
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


class MemoryType:
    """Типы записей долговременной памяти."""
    FACT = "fact"                 # Факты и знания о пользователе/проекте
    PREFERENCE = "preference"     # Предпочтения пользователя (тема, язык, стиль)
    RESULT = "result"             # Явно зафиксированный результат важной задачи
    NOTE = "note"                 # Пользовательская памятка/заметка
    GENERAL = "general"           # Общая информация
    ARTIFACT = "artifact"         # Ссылка на важный сгенерированный артефакт


class MemorySource:
    """Источники происхождения записи долговременной памяти."""
    USER = "user"                 # Напрямую от пользователя (чат, CLI, GUI)
    AGENT = "agent"               # От основного агента Акакия
    SUBAGENT = "subagent"         # От специализированного субагента
    CLI = "cli"                   # Введено через CLI команду
    GUI = "gui"                   # Введено через форму MemoryView
    SYSTEM = "system"             # Системная конфигурация/миграция


class MemoryEntry(dict):
    """
    Структурированная модель записи долговременной памяти.

    Наследует dict для 100% нативной совместимости со всеми существующими модулями
    (JSON-сериализация, backup.py, gui.py, paged_controller, тесты).
    Предоставляет доступ как через ключи (entry['text'], entry['id']), так и через атрибуты.
    """

    def __init__(
        self,
        id: Union[int, str],
        content: str,
        type: str = MemoryType.FACT,
        source: str = MemorySource.USER,
        tags: Optional[List[str]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
        text: Optional[str] = None
    ):
        clean_content = str(content if content is not None else (text or "")).strip()
        entry_type = str(type or category or MemoryType.FACT).strip().lower()
        entry_source = str(source or MemorySource.USER).strip()
        entry_tags = [str(t).strip() for t in tags if str(t).strip()] if tags else []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c_at = str(created_at) if created_at else now_str
        u_at = str(updated_at) if updated_at else c_at
        meta = dict(metadata) if metadata else {}

        super().__init__(
            id=id,
            content=clean_content,
            text=clean_content,         # Алиас для 100% обратной совместимости
            type=entry_type,
            category=entry_type,        # Алиас для 100% обратной совместимости
            source=entry_source,
            tags=entry_tags,
            created_at=c_at,
            updated_at=u_at,
            metadata=meta
        )

    # -------------------------------------------------------------------------
    # Свойства для доступа в стиле атрибутов (Object Protocol)
    # -------------------------------------------------------------------------

    @property
    def id(self) -> Union[int, str]:
        return self["id"]

    @id.setter
    def id(self, val: Union[int, str]) -> None:
        self["id"] = val

    @property
    def content(self) -> str:
        return self["content"]

    @content.setter
    def content(self, val: str) -> None:
        val_str = str(val).strip()
        self["content"] = val_str
        self["text"] = val_str

    @property
    def text(self) -> str:
        """Алиас для content."""
        return self["content"]

    @text.setter
    def text(self, val: str) -> None:
        self.content = val

    @property
    def type(self) -> str:
        return self["type"]

    @type.setter
    def type(self, val: str) -> None:
        val_str = str(val).strip().lower()
        self["type"] = val_str
        self["category"] = val_str

    @property
    def category(self) -> str:
        """Алиас для type."""
        return self["type"]

    @category.setter
    def category(self, val: str) -> None:
        self.type = val

    @property
    def source(self) -> str:
        return self["source"]

    @source.setter
    def source(self, val: str) -> None:
        self["source"] = str(val).strip()

    @property
    def tags(self) -> List[str]:
        return self["tags"]

    @tags.setter
    def tags(self, val: List[str]) -> None:
        self["tags"] = [str(t).strip() for t in val if str(t).strip()] if val else []

    @property
    def created_at(self) -> str:
        return self["created_at"]

    @created_at.setter
    def created_at(self, val: str) -> None:
        self["created_at"] = str(val)

    @property
    def updated_at(self) -> str:
        return self["updated_at"]

    @updated_at.setter
    def updated_at(self, val: str) -> None:
        self["updated_at"] = str(val)

    @property
    def metadata(self) -> Dict[str, Any]:
        return self["metadata"]

    @metadata.setter
    def metadata(self, val: Dict[str, Any]) -> None:
        self["metadata"] = dict(val) if val else {}

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает стандартный словарь записи."""
        return dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        """Создаёт экземпляр MemoryEntry из словаря (v1 или v2)."""
        if isinstance(data, MemoryEntry):
            return data
        if not isinstance(data, dict):
            raise TypeError(f"Ожидается dict, получен {type(data)}")

        return cls(
            id=data.get("id", 0),
            content=data.get("content", data.get("text", "")),
            type=data.get("type", data.get("category", MemoryType.FACT)),
            source=data.get("source", MemorySource.USER),
            tags=data.get("tags"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata")
        )

    def matches_query(self, query: str) -> bool:
        """Проверяет совпадение по тексту запроса."""
        if not query:
            return True
        norm_query = normalize_for_comparison(query)
        words = [w for w in norm_query.split() if len(w) > 1]
        if not words:
            return True
        norm_content = normalize_for_comparison(self.content)
        return all(w in norm_content for w in words) or any(w in norm_content for w in words)

    def __repr__(self) -> str:
        text_preview = (self.content[:30] + "...") if len(self.content) > 30 else self.content
        return f"<MemoryEntry #{self.id} [{self.type}] source='{self.source}' content='{text_preview}'>"


class PersistentMemory:
    """
    Выделенный слой долговременной памяти Акакия (Persistent Memory Layer).
    
    Изолирован от AgentContext и диалоговой runtime history.
    Хранит факты, предпочтения и явно зафиксированные результаты,
    переживающие перезапуск приложения.
    """

    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        actual_path = storage_path or DEFAULT_PERSISTENT_MEMORY_FILE
        self.storage_path = Path(actual_path)
        self._entries: List[MemoryEntry] = []
        self._ensure_storage_dir()
        self.reload()

    def _ensure_storage_dir(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Не удалось создать директорию памяти {self.storage_path.parent}: {e}")

    @property
    def entries(self) -> List[MemoryEntry]:
        """Прямой доступ к списку записей памяти."""
        return self._entries

    @entries.setter
    def entries(self, value: List[Any]) -> None:
        self._entries = [
            e if isinstance(e, MemoryEntry) else MemoryEntry.from_dict(e)
            for e in value
        ]

    def reload(self) -> None:
        """Перечитывает долговременную память с диска."""
        self._entries = self._load_from_disk()

    def _load_from_disk(self) -> List[MemoryEntry]:
        """Загружает записи с диска с автомиграцией формата v1 -> v2."""
        if not self.storage_path.exists():
            return []
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_list: List[Dict[str, Any]] = []
                if isinstance(data, dict):
                    raw_list = data.get("memories", [])
                elif isinstance(data, list):
                    raw_list = data

                entries = []
                for item in raw_list:
                    if isinstance(item, dict):
                        entries.append(MemoryEntry.from_dict(item))
                return entries
        except Exception as e:
            logger.error(f"Ошибка чтения файла памяти {self.storage_path}: {e}")
            return []

    def save(self) -> bool:
        """Атомарно сохраняет память на диск."""
        self._ensure_storage_dir()
        payload = {
            "version": 2,
            "updated_at": datetime.now().isoformat(),
            "memories": [e.to_dict() for e in self._entries]
        }
        try:
            tmp_path = self.storage_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if self.storage_path.exists():
                os.replace(tmp_path, self.storage_path)
            else:
                tmp_path.rename(self.storage_path)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения файла памяти {self.storage_path}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Безопасные операции CRUD
    # -------------------------------------------------------------------------

    def create(
        self,
        content: str,
        type: str = MemoryType.FACT,
        source: str = MemorySource.USER,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MemoryEntry]]:
        """
        Создаёт новую запись в долговременной памяти.
        Выполняет валидацию содержимого и проверку на дубликаты.
        """
        valid, msg = is_valid_memory_text(content)
        if not valid:
            return False, f"Не удалось сохранить: {msg}", None

        clean_text = content.strip()
        norm_text = normalize_for_comparison(clean_text)

        # Проверка на дубликаты
        for m in self._entries:
            if norm_text == normalize_for_comparison(m.content):
                return False, f"Эта информация уже есть в памяти (запись #{m.id}): \"{m.content}\"", m

        # Генерация следующего числового ID
        max_id = 0
        for m in self._entries:
            try:
                mid = int(m.id)
                if mid > max_id:
                    max_id = mid
            except (ValueError, TypeError):
                pass
        next_id = max_id + 1

        entry = MemoryEntry(
            id=next_id,
            content=clean_text,
            type=type or category or MemoryType.FACT,
            source=source,
            tags=tags,
            metadata=metadata
        )

        self._entries.append(entry)
        saved = self.save()
        if not saved:
            return False, "Не удалось записать память на диск.", None

        return True, f"Запомнил: \"{clean_text}\" (запись #{next_id})", entry

    def get(self, entry_id: Union[int, str]) -> Optional[MemoryEntry]:
        """Возвращает запись памяти по её ID."""
        clean_id_str = str(entry_id).strip().lstrip("#№")
        for m in self._entries:
            if str(m.id) == clean_id_str:
                return m
        return None

    def get_all(self) -> List[MemoryEntry]:
        """Возвращает список всех записей памяти."""
        return list(self._entries)

    def update(
        self,
        entry_id: Union[int, str],
        content: Optional[str] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ) -> Tuple[bool, str, Optional[MemoryEntry]]:
        """
        Безопасно обновляет существующую запись памяти.
        """
        entry = self.get(entry_id)
        if not entry:
            return False, f"Запись с номером #{entry_id} не найдена в памяти.", None

        if content is not None:
            valid, msg = is_valid_memory_text(content)
            if not valid:
                return False, f"Не удалось обновить: {msg}", None

            clean_text = content.strip()
            norm_text = normalize_for_comparison(clean_text)

            # Проверка дубликата среди ДРУГИХ записей
            for m in self._entries:
                if m.id != entry.id and norm_text == normalize_for_comparison(m.content):
                    return False, f"Такой текст уже есть в записи #{m.id}: \"{m.content}\"", None

            entry.content = clean_text

        if type is not None:
            entry.type = type

        if tags is not None:
            entry.tags = tags

        if metadata is not None:
            entry.metadata.update(metadata)

        if source is not None:
            entry.source = source

        entry.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        saved = self.save()
        if not saved:
            return False, "Не удалось сохранить обновлённую память на диск.", None

        return True, f"Запись #{entry.id} успешно обновлена.", entry

    def delete(self, target: Union[int, str]) -> Tuple[bool, str]:
        """
        Удаляет запись из памяти по ID или фрагменту текста.
        """
        if not target and target != 0:
            return False, "Укажите номер или текст записи для удаления."

        # 1. Попытка удаления по точному ID
        target_id_str = None
        if isinstance(target, int):
            target_id_str = str(target)
        else:
            t_str = str(target).strip()
            id_match = re.match(r"^[#№]?(\d+)$", t_str)
            if id_match:
                target_id_str = str(int(id_match.group(1)))

        if target_id_str is not None:
            for idx, m in enumerate(self._entries):
                if str(m.id) == target_id_str:
                    removed = self._entries.pop(idx)
                    self.save()
                    return True, f"Удалил запись #{removed.id} из памяти: \"{removed.content}\""

        # 2. Поиск по текстовому совпадению
        target_norm = normalize_for_comparison(str(target))
        if not target_norm:
            return False, "Укажите непустой текст для удаления."

        matching_indices = []
        for idx, m in enumerate(self._entries):
            if target_norm in normalize_for_comparison(m.content):
                matching_indices.append(idx)

        if not matching_indices:
            if target_id_str is not None:
                return False, f"Запись с номером #{target_id_str} не найдена в памяти."
            return False, f"Запись, содержащая \"{target}\", не найдена в памяти."

        if len(matching_indices) == 1:
            removed = self._entries.pop(matching_indices[0])
            self.save()
            return True, f"Удалил запись #{removed.id} из памяти: \"{removed.content}\""

        # Несколько совпадений
        matched_entries = [self._entries[i] for i in matching_indices]
        entries_str = ", ".join(f"#{m.id} (\"{m.content[:30]}...\")" for m in matched_entries[:3])
        return False, f"Найдено несколько записей: {entries_str}. Укажите точный номер записи (например, 'забудь: #{matched_entries[0].id}')."

    def clear(self) -> Tuple[bool, str]:
        """Очищает всю долговременную память."""
        count = len(self._entries)
        self._entries.clear()
        self.save()
        return True, f"Долговременная память очищена (удалено записей: {count})."

    # -------------------------------------------------------------------------
    # Поиск и фильтрация
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None
    ) -> List[MemoryEntry]:
        """
        Поиск записей памяти с опциональной фильтрацией по типу, тегам и источнику.
        """
        results: List[MemoryEntry] = []
        q_norm = normalize_for_comparison(query) if query else ""
        words = [w for w in q_norm.split() if len(w) > 1] if q_norm else []
        norm_type = type.strip().lower() if type else None
        norm_source = source.strip().lower() if source else None
        filter_tags = [t.strip().lower() for t in tags if t.strip()] if tags else None

        for m in self._entries:
            # Фильтр по типу
            if norm_type and m.type.lower() != norm_type:
                continue

            # Фильтр по источнику
            if norm_source and m.source.lower() != norm_source:
                continue

            # Фильтр по тегам (хотя бы один совпавший тег)
            if filter_tags:
                entry_tags_lower = [t.lower() for t in m.tags]
                if not any(ft in entry_tags_lower for ft in filter_tags):
                    continue

            # Фильтр по тексту запроса
            if words:
                norm_content = normalize_for_comparison(m.content)
                if not any(w in norm_content for w in words):
                    continue

            results.append(m)

        return results

    # -------------------------------------------------------------------------
    # Явная фиксация важных результатов (Explicit Result Storage)
    # -------------------------------------------------------------------------

    def remember_result(
        self,
        result: Any,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = MemorySource.AGENT
    ) -> Tuple[bool, str, Optional[MemoryEntry]]:
        """
        Явно сохраняет результат задачи в долговременную память.
        Не сохраняет автоматически каждый результат — вызывается только по явной команде.
        """
        text_content = ""
        meta: Dict[str, Any] = {}

        if hasattr(result, "message") and result.message:
            text_content = str(result.message)
        elif isinstance(result, dict) and result.get("message"):
            text_content = str(result["message"])
        elif isinstance(result, str):
            text_content = result

        if title:
            text_content = f"{title}: {text_content}"

        if hasattr(result, "created_files") and result.created_files:
            meta["created_files"] = list(result.created_files)
        if hasattr(result, "artifacts") and result.artifacts:
            meta["artifacts_count"] = len(result.artifacts)

        all_tags = list(tags) if tags else []
        if "result" not in all_tags:
            all_tags.append("result")

        return self.create(
            content=text_content,
            type=MemoryType.RESULT,
            source=source,
            tags=all_tags,
            metadata=meta
        )

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def __repr__(self) -> str:
        return f"<PersistentMemory path='{self.storage_path}' entries={len(self._entries)}>"
