"""
Модуль отслеживания контекста изображений (ImageContextTracker).

Отвечает за ответственность Image Context:
1. Определение активного изображения в сессии.
2. Сохранение исходного (root) изображения и предотвращение его перезаписи.
3. Отслеживание цепочки последовательных правок (root -> edit_1 -> edit_2 -> ...).
4. Проверку физического существования файлов на диске.
5. 100% обратную совместимость со словарной структурой _last_image_result.
"""

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_CONTEXT_PATH = Path(__file__).resolve().parent.parent / "data" / "image_context.json"


@dataclass
class ImageEntry:
    """Запись об одном сгенерированном или отредактированном изображении."""
    file_path: str
    prompt: str = ""
    action: str = "generate"  # generate | revise | edit | select
    instruction: str = ""
    source_image_path: Optional[str] = None
    edit_type: str = "general"
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_valid_on_disk(self) -> bool:
        """Проверяет, существует ли файл изображения физически на диске."""
        if not self.file_path:
            return False
        try:
            return os.path.isfile(self.file_path)
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "prompt": self.prompt,
            "action": self.action,
            "instruction": self.instruction,
            "source_image_path": self.source_image_path,
            "edit_type": self.edit_type,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["ImageEntry"]:
        if not isinstance(data, dict):
            return None
        file_path = str(data.get("file_path") or "").strip()
        if not file_path:
            return None
        raw_meta = data.get("metadata")
        try:
            ts = float(data.get("timestamp", time.time()))
        except (TypeError, ValueError):
            ts = time.time()
        return cls(
            file_path=file_path,
            prompt=str(data.get("prompt") or ""),
            action=str(data.get("action") or "generate"),
            instruction=str(data.get("instruction") or ""),
            source_image_path=(
                str(data["source_image_path"]) if data.get("source_image_path") else None
            ),
            edit_type=str(data.get("edit_type") or "general"),
            timestamp=ts,
            metadata=dict(raw_meta) if isinstance(raw_meta, dict) else {},
        )


class ImageContextTracker:
    """
    Управляет состоянием активного изображения и цепочками правок в сессии Акакия.
    Поддерживает опциональную персистентность состояния на диске (storage_path).
    """

    def __init__(
        self,
        storage_path: Optional[Union[str, Path]] = None,
        auto_load: bool = True,
        max_history: int = 50,
    ) -> None:
        self._lock = threading.RLock()
        self.storage_path: Optional[Path] = Path(storage_path) if storage_path else None
        self.max_history = max(1, int(max_history))
        self.root_image: Optional[ImageEntry] = None
        self.active_image: Optional[ImageEntry] = None
        self.history: List[ImageEntry] = []

        if self.storage_path is not None and auto_load:
            self.load()

    def clear(self) -> None:
        """Сбрасывает контекст изображений."""
        with self._lock:
            self.root_image = None
            self.active_image = None
            self.history = []
            self._auto_save()

    def _auto_save(self) -> None:
        if self.storage_path is not None:
            self.save()

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": 1,
                "root_image": self.root_image.to_dict() if self.root_image else None,
                "active_image": self.active_image.to_dict() if self.active_image else None,
                "history": [entry.to_dict() for entry in self.history[-self.max_history:]],
            }

    def save(self) -> bool:
        """Атомарно сохраняет состояние контекста изображений на диск."""
        with self._lock:
            if self.storage_path is None:
                return False
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                data = self.to_dict()
                tmp_path = self.storage_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.storage_path)
                return True
            except Exception as e:
                logger.warning("Ошибка сохранения контекста изображений в %s: %s", self.storage_path, e)
                return False

    def load(self) -> bool:
        """Загружает сохранённое состояние контекста изображений с диска."""
        with self._lock:
            if self.storage_path is None or not self.storage_path.exists():
                return False
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return False

                loaded_history: List[ImageEntry] = []
                for item in data.get("history") or []:
                    entry = ImageEntry.from_dict(item)
                    if entry is not None:
                        loaded_history.append(entry)

                root_entry = ImageEntry.from_dict(data.get("root_image"))
                active_entry = ImageEntry.from_dict(data.get("active_image"))

                # Привязываем ссылки к объектам в history, если пути совпадают
                if loaded_history:
                    by_path = {e.file_path: e for e in loaded_history}
                    if root_entry and root_entry.file_path in by_path:
                        root_entry = by_path[root_entry.file_path]
                    if active_entry and active_entry.file_path in by_path:
                        active_entry = by_path[active_entry.file_path]

                self.history = loaded_history[-self.max_history:]
                self.root_image = root_entry
                self.active_image = active_entry
                return True
            except Exception as e:
                logger.warning("Ошибка загрузки контекста изображений из %s: %s", self.storage_path, e)
                return False

    @staticmethod
    def _same_path(path_a: Optional[str], path_b: Optional[str]) -> bool:
        if not path_a or not path_b:
            return False
        if path_a == path_b:
            return True
        try:
            return Path(path_a).resolve() == Path(path_b).resolve()
        except Exception:
            return os.path.normcase(os.path.normpath(path_a)) == os.path.normcase(os.path.normpath(path_b))

    def track_generation(
        self,
        file_path: str,
        prompt: str,
        is_revision: bool = False,
        **metadata: Any
    ) -> ImageEntry:
        """
        Фиксирует успешную генерацию нового изображения (Scenario A)
        или перегенерацию по замечанию (Scenario B).
        """
        with self._lock:
            action = "revise" if is_revision else "generate"
            entry = ImageEntry(
                file_path=str(file_path),
                prompt=str(prompt or ""),
                action=action,
                instruction=str(metadata.get("critique_details", "")),
                source_image_path=None,
                edit_type="general",
                timestamp=time.time(),
                metadata=dict(metadata),
            )
            self.root_image = entry
            self.active_image = entry
            self.history = [entry]
            self._auto_save()
            return entry

    def track_edit(
        self,
        file_path: str,
        instruction: str,
        prompt: str,
        source_image_path: Optional[str] = None,
        edit_type: str = "general",
        **metadata: Any
    ) -> ImageEntry:
        """
        Фиксирует успешную правку существующего изображения (Scenario C).
        Исходное изображение (root_image) сохраняется в истории.
        Активным изображением (active_image) становится результат правки.
        """
        with self._lock:
            effective_source = source_image_path or (
                self.active_image.file_path if self.active_image else None
            )
            entry = ImageEntry(
                file_path=str(file_path),
                prompt=str(prompt or ""),
                action="edit",
                instruction=str(instruction or ""),
                source_image_path=str(effective_source) if effective_source else None,
                edit_type=str(edit_type or "general"),
                timestamp=time.time(),
                metadata=dict(metadata),
            )
            if not self.root_image:
                self.root_image = entry
            self.active_image = entry
            self.history.append(entry)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            self._auto_save()
            return entry

    def select_active_image(
        self,
        file_path: str,
        prompt: Optional[str] = None,
        validate_disk: bool = True,
        **metadata: Any
    ) -> Tuple[bool, Optional[ImageEntry], str]:
        """
        Выбирает указанное изображение как текущее активное (например, из UI или через select_image).
        Если файл есть в истории — переключает active_image на него;
        иначе регистрирует новую запись в контексте.
        """
        with self._lock:
            raw_path = str(file_path or "").strip()
            if not raw_path:
                return False, None, "Не указан путь к файлу изображения."
            if validate_disk and not os.path.isfile(raw_path):
                return False, None, f"Файл изображения не найден на диске: {raw_path}"

            for entry in reversed(self.history):
                if self._same_path(entry.file_path, raw_path):
                    if prompt and not entry.prompt:
                        entry.prompt = str(prompt)
                    if metadata:
                        for k, v in metadata.items():
                            if v is not None and k not in entry.metadata:
                                entry.metadata[k] = v
                    self.active_image = entry
                    if not self.root_image:
                        self.root_image = entry
                    self._auto_save()
                    return True, entry, f"Активное изображение переключено на: {Path(entry.file_path).name}"

            entry = ImageEntry(
                file_path=raw_path,
                prompt=str(prompt or ""),
                action="select",
                instruction="",
                source_image_path=None,
                edit_type="general",
                timestamp=time.time(),
                metadata={k: v for k, v in metadata.items() if v is not None},
            )
            if not self.root_image:
                self.root_image = entry
            self.active_image = entry
            self.history.append(entry)
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
            self._auto_save()
            return True, entry, f"Выбрано активное изображение: {Path(raw_path).name}"

    def sync_from_legacy_dict(self, data: Optional[Dict[str, Any]], validate_disk: bool = True) -> bool:
        """
        Синхронизирует внутреннее состояние из legacy-словаря (_last_image_result),
        сохраняя привязку storage_path.
        """
        if not data or not isinstance(data, dict):
            return False
        created_files = data.get("created_files") or []
        prompt = data.get("prompt") or data.get("clean_prompt") or ""
        file_path = created_files[0] if created_files else data.get("source_image_path")
        if not file_path:
            return False
        if validate_disk and not os.path.isfile(str(file_path)):
            return False
        self.track_generation(
            file_path=str(file_path),
            prompt=str(prompt),
            width=data.get("width"),
            height=data.get("height"),
            aspect_ratio=data.get("aspect_ratio"),
            count=data.get("count", 1),
        )
        return True

    def get_active_image_path(self, validate_disk: bool = True) -> Optional[str]:
        """
        Возвращает путь к текущему активному изображению.
        Если validate_disk=True, проверяет наличие на диске. Если файл удален,
        ищет ближайший существующий файл в истории в обратном порядке.
        """
        with self._lock:
            if self.active_image:
                if not validate_disk or self.active_image.is_valid_on_disk():
                    return self.active_image.file_path

            # Поиск последнего доступного на диске файла из истории
            if validate_disk and self.history:
                for entry in reversed(self.history):
                    if entry.is_valid_on_disk():
                        self.active_image = entry
                        return entry.file_path

            return None

    def get_root_image_path(self) -> Optional[str]:
        """Возвращает путь к самому первому изображению в цепочке правок."""
        with self._lock:
            if self.root_image:
                return self.root_image.file_path
            return None

    def get_active_prompt(self) -> str:
        """Возвращает актуальный промпт для текущего активного изображения."""
        with self._lock:
            if self.active_image:
                return self.active_image.prompt
            return ""

    def get_history_summary(self) -> List[Dict[str, Any]]:
        """Возвращает историю шагов генерации и правок."""
        with self._lock:
            return [entry.to_dict() for entry in self.history]

    def has_active_image(self, validate_disk: bool = True) -> bool:
        """Проверяет, есть ли в сессии активное изображение."""
        return self.get_active_image_path(validate_disk=validate_disk) is not None

    def to_legacy_dict(self, validate_disk: bool = True) -> Dict[str, Any]:
        """
        Формирует словарь, совместимый с Agent._last_image_result и CommandRouter.last_image.
        """
        with self._lock:
            active_path = self.get_active_image_path(validate_disk=validate_disk)
            active_prompt = self.get_active_prompt()
            meta = self.active_image.metadata if self.active_image else {}

            return {
                "prompt": active_prompt,
                "created_files": [active_path] if active_path else [],
                "source_image_path": active_path,
                "source_image": active_path,
                "width": meta.get("width"),
                "height": meta.get("height"),
                "aspect_ratio": meta.get("aspect_ratio"),
                "count": meta.get("count", 1),
                "root_image_path": self.get_root_image_path(),
                "history_count": len(self.history),
            }

    @classmethod
    def from_legacy_dict(
        cls,
        data: Optional[Dict[str, Any]],
        storage_path: Optional[Union[str, Path]] = None,
    ) -> "ImageContextTracker":
        """Восстанавливает трекер из словарного представления."""
        tracker = cls(storage_path=storage_path, auto_load=False)
        if not data or not isinstance(data, dict):
            return tracker

        created_files = data.get("created_files") or []
        prompt = data.get("prompt") or data.get("clean_prompt") or ""
        file_path = created_files[0] if created_files else data.get("source_image_path")

        if file_path:
            tracker.track_generation(
                file_path=str(file_path),
                prompt=str(prompt),
                width=data.get("width"),
                height=data.get("height"),
                aspect_ratio=data.get("aspect_ratio"),
                count=data.get("count", 1),
            )
        return tracker
