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
from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional


@dataclass
class ImageEntry:
    """Запись об одном сгенерированном или отредактированном изображении."""
    file_path: str
    prompt: str = ""
    action: str = "generate"  # generate | revise | edit
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


class ImageContextTracker:
    """
    Управляет состоянием активного изображения и цепочками правок в сессии Акакия.
    """

    def __init__(self) -> None:
        self.root_image: Optional[ImageEntry] = None
        self.active_image: Optional[ImageEntry] = None
        self.history: List[ImageEntry] = []

    def clear(self) -> None:
        """Сбрасывает контекст изображений."""
        self.root_image = None
        self.active_image = None
        self.history = []

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
        return entry

    def get_active_image_path(self, validate_disk: bool = True) -> Optional[str]:
        """
        Возвращает путь к текущему активному изображению.
        Если validate_disk=True, проверяет наличие на диске. Если файл удален,
        ищет ближайший существующий файл в истории в обратном порядке.
        """
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
        if self.root_image:
            return self.root_image.file_path
        return None

    def get_active_prompt(self) -> str:
        """Возвращает актуальный промпт для текущего активного изображения."""
        if self.active_image:
            return self.active_image.prompt
        return ""

    def get_history_summary(self) -> List[Dict[str, Any]]:
        """Возвращает историю шагов генерации и правок."""
        return [entry.to_dict() for entry in self.history]

    def has_active_image(self, validate_disk: bool = True) -> bool:
        """Проверяет, есть ли в сессии активное изображение."""
        return self.get_active_image_path(validate_disk=validate_disk) is not None

    def to_legacy_dict(self, validate_disk: bool = True) -> Dict[str, Any]:
        """
        Формирует словарь, совместимый с Agent._last_image_result и CommandRouter.last_image.
        """
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
    def from_legacy_dict(cls, data: Optional[Dict[str, Any]]) -> "ImageContextTracker":
        """Восстанавливает трекер из словарного представления."""
        tracker = cls()
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
