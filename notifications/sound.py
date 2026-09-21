"""
Модуль воспроизведения системных звуковых уведомлений Акакия.

Использует стандартный Windows-механизм winsound без внешних зависимостей.
Воспроизведение осуществляется асинхронно (SND_ASYNC), не блокируя поток GUI.
"""

import logging
import sys
from typing import Any, Optional

from tools.settings import AppSettings, get_app_settings

logger = logging.getLogger(__name__)


def play_system_sound(sound_alias: str = "SystemNotification") -> bool:
    """
    Воспроизводит системный звук Windows через winsound.
    Работает асинхронно, с защитой от любых сбоев.
    """
    if sys.platform != "win32":
        logger.debug("Системный звук пропущен: платформа не является Windows.")
        return False

    try:
        import winsound

        # 1. Попытка воспроизведения стандартного системного звука уведомления Windows
        try:
            flags = winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            winsound.PlaySound(sound_alias, flags)
            return True
        except Exception:
            pass

        # 2. Fallback на стандартный звуковой сигнал Windows
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return True
        except Exception:
            pass

        return False

    except Exception as e:
        logger.debug(f"Не удалось воспроизвести системный звук: {e}")
        return False


def play_notification_sound(settings: Optional[AppSettings] = None) -> bool:
    """
    Воспроизводит звук уведомления с учётом пользовательских настроек (notification_sound).
    Возвращает True, если звук был отправлен на воспроизведение, иначе False.
    """
    current_settings = settings if settings is not None else get_app_settings()

    # Проверка настройки: если звук выключен, выходим
    if current_settings is not None:
        sound_enabled = getattr(current_settings, "notification_sound", True)
        if not sound_enabled:
            return False

    return play_system_sound("SystemNotification")
