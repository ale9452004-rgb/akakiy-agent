"""
Модуль глобального хоткея Windows (Global HotKey / Push-to-Talk) для Акакия.

Использует Win32 API (RegisterHotKey, UnregisterHotKey, GetMessageW, GetAsyncKeyState)
через ctypes без дополнительных внешних зависимостей.
Обеспечивает перехват комбинации клавиш (по умолчанию Ctrl+Shift+Space) даже когда окно
Акакия не в фокусе, с поддержкой как режима Toggle (нажал — включил, нажал — выключил),
так и Push-to-Talk (зажал — говорит, отпустил — отправил).
"""

import ctypes
from ctypes import wintypes
import logging
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Win32 Константы модификаторов
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Виртуальные клавиши
VK_SPACE = 0x20

# Сообщения Windows
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Идентификатор хоткея Акакия
AKAKIY_VOICE_HOTKEY_ID = 0xAA01


class GlobalHotKeyManager:
    """
    Менеджер глобального хоткея Windows.

    Запускает фоновый поток с Win32 Message Loop, регистрирует глобальный хоткей
    и вызывает соответствующие коллбэки при нажатии и отпускании.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Optional[Callable[[], None]] = None,
        modifiers: int = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
        vk: int = VK_SPACE,
        hotkey_id: int = AKAKIY_VOICE_HOTKEY_ID,
        hold_threshold_seconds: float = 0.3,
    ):
        self.on_press = on_press
        self.on_release = on_release
        self.modifiers = modifiers
        self.vk = vk
        self.hotkey_id = hotkey_id
        self.hold_threshold_seconds = hold_threshold_seconds

        self._is_registered = False
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_registered(self) -> bool:
        """Зарегистрирован ли хоткей в операционной системе."""
        return self._is_registered

    @property
    def is_running(self) -> bool:
        """Запущен ли рабочий поток менеджера хоткеев."""
        return self._is_running

    def start(self, timeout: float = 2.0) -> bool:
        """
        Запускает фоновый поток регистрации и обработки хоткея.
        Возвращает True, если хоткей успешно зарегистрирован.
        """
        if sys.platform != "win32":
            logger.info("Глобальный хоткей поддерживается только на платформе Windows.")
            return False

        with self._lock:
            if self._is_running:
                logger.info("GlobalHotKeyManager уже запущен.")
                return self._is_registered

            self._ready_event.clear()
            self._is_running = True
            self._thread = threading.Thread(
                target=self._message_loop,
                name="Akakiy-GlobalHotKey-Thread",
                daemon=True,
            )
            self._thread.start()

        # Ожидаем завершения регистрации в потоке
        self._ready_event.wait(timeout=timeout)
        return self._is_registered

    def stop(self):
        """Останавливает рабочий поток и освобождает глобальный хоткей."""
        with self._lock:
            if not self._is_running:
                return

            self._is_running = False

            if sys.platform == "win32" and self._thread_id:
                try:
                    user32 = ctypes.windll.user32
                    user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
                except Exception as ex:
                    logger.debug(f"Ошибка при отправке WM_QUIT потоку хоткея: {ex}")

            if self._thread and self._thread.is_alive():
                if threading.current_thread() != self._thread:
                    self._thread.join(timeout=1.5)

            self._thread = None
            self._thread_id = None
            self._is_registered = False

    def _message_loop(self):
        """Внутренний цикл Windows-сообщений потока хоткея."""
        if sys.platform != "win32":
            self._ready_event.set()
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id = kernel32.GetCurrentThreadId()

        # Регистрация глобального хоткея
        success = user32.RegisterHotKey(
            0,
            self.hotkey_id,
            self.modifiers,
            self.vk,
        )

        if not success:
            err_code = ctypes.GetLastError()
            logger.warning(
                f"Не удалось зарегистрировать глобальный хоткей (код {err_code}). "
                f"Возможно, комбинация уже занята другим приложением."
            )
            self._is_registered = False
            self._ready_event.set()
            return

        self._is_registered = True
        self._ready_event.set()
        logger.info(f"Глобальный хоткей успешно зарегистрирован (ID={self.hotkey_id}).")

        try:
            msg = wintypes.MSG()
            while self._is_running and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self._dispatch_hotkey()

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as ex:
            logger.error(f"Непредвиденная ошибка в цикле сообщений хоткея: {ex}", exc_info=True)
        finally:
            try:
                user32.UnregisterHotKey(0, self.hotkey_id)
                logger.info(f"Глобальный хоткей освобождён (ID={self.hotkey_id}).")
            except Exception as ex:
                logger.debug(f"Ошибка при UnregisterHotKey: {ex}")
            self._is_registered = False

    def _dispatch_hotkey(self):
        """Обрабатывает факт нажатия хоткея и запускает отслеживание отпускания."""
        # Вызываем on_press
        if self.on_press and callable(self.on_press):
            try:
                self.on_press()
            except Exception as ex:
                logger.warning(f"Ошибка в коллбэке on_press хоткея: {ex}")

        # Если задан коллбэк отпускания, запускаем фоновое отслеживание отпускания клавиши
        if self.on_release and callable(self.on_release) and sys.platform == "win32":
            threading.Thread(
                target=self._watch_release,
                daemon=True,
                name="Akakiy-HotKeyRelease-Watcher",
            ).start()

    def _watch_release(self):
        """Отслеживает отпускание основной клавиши (Push-to-Talk)."""
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        start_time = time.time()
        was_held = False

        # Пока клавиша физически зажата
        while self._is_running:
            key_state = user32.GetAsyncKeyState(self.vk)
            if not (key_state & 0x8000):
                # Клавиша отпущена
                break

            time.sleep(0.02)
            if (time.time() - start_time) >= self.hold_threshold_seconds:
                was_held = True

        # Если клавиша удерживалась дольше порога (режим Push-to-Talk)
        if was_held and self._is_running and self.on_release and callable(self.on_release):
            try:
                self.on_release()
            except Exception as ex:
                logger.warning(f"Ошибка в коллбэке on_release хоткея: {ex}")
