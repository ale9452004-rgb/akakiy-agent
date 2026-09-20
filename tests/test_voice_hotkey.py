"""
Тесты для глобального хоткея Push-to-Talk (GlobalHotKeyManager),
интеграции с VoiceService и AkakiyGUI.
"""

import sys
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from voice.hotkey import (
    GlobalHotKeyManager,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_NOREPEAT,
    VK_SPACE,
    AKAKIY_VOICE_HOTKEY_ID,
)
from voice.service import VoiceService
import gui


class TestGlobalHotKeyManager(unittest.TestCase):
    """Тестирование жизненного цикла и логики GlobalHotKeyManager."""

    def test_hotkey_manager_init(self):
        on_press = MagicMock()
        on_release = MagicMock()
        mgr = GlobalHotKeyManager(
            on_press=on_press,
            on_release=on_release,
            modifiers=MOD_CONTROL | MOD_SHIFT,
            vk=VK_SPACE,
            hotkey_id=12345,
            hold_threshold_seconds=0.25,
        )
        self.assertEqual(mgr.on_press, on_press)
        self.assertEqual(mgr.on_release, on_release)
        self.assertEqual(mgr.modifiers, MOD_CONTROL | MOD_SHIFT)
        self.assertEqual(mgr.vk, VK_SPACE)
        self.assertEqual(mgr.hotkey_id, 12345)
        self.assertEqual(mgr.hold_threshold_seconds, 0.25)
        self.assertFalse(mgr.is_registered)
        self.assertFalse(mgr.is_running)

    @unittest.skipUnless(sys.platform == "win32", "Требуется платформа Windows для нативного Win32 API")
    def test_native_start_and_stop_lifecycle(self):
        on_press = MagicMock()
        on_release = MagicMock()
        mgr = GlobalHotKeyManager(
            on_press=on_press,
            on_release=on_release,
            hotkey_id=0xAA99,  # Уникальный тестовый ID
        )

        try:
            started = mgr.start(timeout=2.0)
            self.assertTrue(started, "Хоткей должен успешно зарегистрироваться в Windows")
            self.assertTrue(mgr.is_running)
            self.assertTrue(mgr.is_registered)
        finally:
            mgr.stop()
            self.assertFalse(mgr.is_running)
            self.assertFalse(mgr.is_registered)

    @patch("ctypes.windll.user32.RegisterHotKey", return_value=0)
    @patch("ctypes.GetLastError", return_value=1409)
    def test_hotkey_registration_failure_graceful(self, mock_err, mock_reg):
        on_press = MagicMock()
        mgr = GlobalHotKeyManager(on_press=on_press)

        started = mgr.start(timeout=1.0)
        self.assertFalse(started, "При занятом хоткее start должен вернуть False без исключений")
        self.assertFalse(mgr.is_registered)
        mgr.stop()
        self.assertFalse(mgr.is_running)

    def test_hotkey_double_start_protection(self):
        on_press = MagicMock()
        mgr = GlobalHotKeyManager(on_press=on_press)

        with patch.object(mgr, "_message_loop") as mock_loop:
            # Имитируем успешный запуск в потоке
            def fake_loop():
                mgr._is_registered = True
                mgr._ready_event.set()

            mock_loop.side_effect = fake_loop

            first_start = mgr.start(timeout=1.0)
            thread_1 = mgr._thread

            # Повторный вызов start
            second_start = mgr.start(timeout=1.0)
            thread_2 = mgr._thread

            self.assertIs(thread_1, thread_2, "Повторный запуск не должен создавать новый поток")
            mgr.stop()

    def test_dispatch_hotkey_triggers_on_press(self):
        on_press = MagicMock()
        mgr = GlobalHotKeyManager(on_press=on_press)
        mgr._dispatch_hotkey()
        on_press.assert_called_once()

    def test_stop_idempotency(self):
        on_press = MagicMock()
        mgr = GlobalHotKeyManager(on_press=on_press)
        # Вызов stop на незапущенном менеджере не должен бросать исключений
        mgr.stop()
        mgr.stop()
        self.assertFalse(mgr.is_running)


class TestVoiceServiceFinishListening(unittest.TestCase):
    """Тестирование поддержки Push-to-Talk в VoiceService."""

    def test_finish_listening_sets_event(self):
        service = VoiceService()
        self.assertFalse(service._finish_event.is_set())
        service.finish_listening()
        self.assertTrue(service._finish_event.is_set())

    def test_stop_session_sets_finish_event(self):
        service = VoiceService()
        self.assertFalse(service._stop_event.is_set())
        self.assertFalse(service._finish_event.is_set())
        service.stop_session()
        self.assertTrue(service._stop_event.is_set())
        self.assertTrue(service._finish_event.is_set())


class TestGUIHotKeyIntegration(unittest.TestCase):
    """Тестирование интеграции хоткея в интерфейс AkakiyGUI."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    @patch("gui.GlobalHotKeyManager")
    def test_gui_initializes_hotkey_manager(self, mock_hotkey_cls):
        mock_mgr = MagicMock()
        mock_hotkey_cls.return_value = mock_mgr

        mock_voice = MagicMock()
        mock_voice.is_busy.return_value = False
        mock_voice.state = "idle"

        app = gui.AkakiyGUI(
            root=self.root,
            agent=MagicMock(),
            household=MagicMock(),
            memory=MagicMock(),
            voice=mock_voice,
        )

        self.assertIsNotNone(app.hotkey_manager)
        mock_mgr.start.assert_called_once()

        # Проверяем обработчик нажатия
        app._handle_hotkey_press()
        # При первом нажатии должен запуститься сеанс
        mock_voice.start_session.assert_called_once_with(continuous=True)

        # Проверяем защиту от параллельного запуска при повторном нажатии
        mock_voice.is_busy.return_value = True
        app._handle_hotkey_press()
        # Повторное нажатие останавливает текущий сеанс, не запуская новый
        mock_voice.stop_session.assert_called_once()

        # Проверяем отпускание клавиши (Push-to-Talk release)
        mock_voice.state = "listening"
        app._handle_hotkey_release()
        mock_voice.finish_listening.assert_called_once()

        # Проверяем чистое завершение при закрытии окна
        app._on_window_close()
        mock_mgr.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
