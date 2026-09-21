"""
Модуль настроек приложения Акакия (AppSettings).

Обеспечивает централизованное хранение и персистентность пользовательских настроек:
- Звуковые уведомления (notification_sound);
- Голосовое озвучивание напоминаний (speak_reminders);
- Дополнительные пользовательские параметры.

Хранилище: data/settings.json (потокобезопасная атомарная запись через .tmp и os.replace).
"""

import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.json"


class AppSettings:
    """
    Класс настроек приложения с автоматической персистентностью в JSON.
    """

    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        self.storage_path = Path(storage_path) if storage_path else DEFAULT_SETTINGS_PATH
        self._lock = threading.RLock()

        # Значения по умолчанию
        self.notification_sound: bool = True
        self.speak_reminders: bool = True
        self.extra_settings: Dict[str, Any] = {}

        self.load()

    def load(self) -> bool:
        """Загружает настройки из JSON-файла, если он существует."""
        with self._lock:
            if not self.storage_path.exists():
                return False

            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    self.notification_sound = bool(data.get("notification_sound", True))
                    self.speak_reminders = bool(data.get("speak_reminders", True))
                    self.extra_settings = {
                        k: v for k, v in data.items()
                        if k not in ("notification_sound", "speak_reminders")
                    }
                    return True
            except Exception as e:
                logger.error(f"Ошибка чтения файла настроек {self.storage_path}: {e}")
                return False

        return False

    def save(self) -> bool:
        """Атомарно сохраняет настройки в JSON-файл через временный файл."""
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                data = self.to_dict()

                tmp_path = self.storage_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                os.replace(tmp_path, self.storage_path)
                return True
            except Exception as e:
                logger.error(f"Ошибка сохранения настроек {self.storage_path}: {e}")
                return False

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует настройки в словарь."""
        with self._lock:
            res = {
                "notification_sound": self.notification_sound,
                "speak_reminders": self.speak_reminders
            }
            res.update(self.extra_settings)
            return res

    def from_dict(self, data: Dict[str, Any], save: bool = True) -> None:
        """Обновляет настройки из словаря."""
        if not isinstance(data, dict):
            return

        with self._lock:
            if "notification_sound" in data:
                self.notification_sound = bool(data["notification_sound"])
            if "speak_reminders" in data:
                self.speak_reminders = bool(data["speak_reminders"])

            for k, v in data.items():
                if k not in ("notification_sound", "speak_reminders"):
                    self.extra_settings[k] = v

            if save:
                self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """Получение произвольной настройки по ключу."""
        with self._lock:
            if key == "notification_sound":
                return self.notification_sound
            elif key == "speak_reminders":
                return self.speak_reminders
            return self.extra_settings.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """Установка произвольной настройки по ключу."""
        with self._lock:
            if key == "notification_sound":
                self.notification_sound = bool(value)
            elif key == "speak_reminders":
                self.speak_reminders = bool(value)
            else:
                self.extra_settings[key] = value

            if save:
                self.save()


# Синглтон настроек приложения
_global_app_settings: Optional[AppSettings] = None
_global_settings_lock = threading.Lock()


def get_app_settings(storage_path: Optional[Union[str, Path]] = None) -> AppSettings:
    """Возвращает глобальный синглтон AppSettings."""
    global _global_app_settings
    with _global_settings_lock:
        if _global_app_settings is None or (storage_path is not None and _global_app_settings.storage_path != Path(storage_path)):
            _global_app_settings = AppSettings(storage_path=storage_path)
        return _global_app_settings


def reset_app_settings() -> None:
    """Сбрасывает синглтон (для изолированных тестов)."""
    global _global_app_settings
    with _global_settings_lock:
        _global_app_settings = None
