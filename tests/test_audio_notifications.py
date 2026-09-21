"""
Тесты для звуковых уведомлений и настроек Акакия (Audio Notifications & Settings).

Проверяет:
1. Персистентность AppSettings (значения по умолчанию, сохранение/загрузка из JSON);
2. Воспроизведение системного звука Windows (winsound, флаг notification_sound);
3. Безопасность при ошибках аудиоустройства;
4. Интеграцию со звуком в NotificationService.notify();
5. Голосовое озвучивание напоминания через существующий VoiceService/TTS в _handle_reminder_due;
6. Игнорирование озвучивания при speak_reminders=False;
7. Безопасность при сбое TTS (не ломает GUI и обработчик напоминаний);
8. Переключение настроек и реакцию кнопок в SettingsView.
"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from notifications.models import NotificationItem
from notifications.service import NotificationService
from notifications.sound import play_notification_sound, play_system_sound
from tools.settings import AppSettings, get_app_settings, reset_app_settings


class TestAppSettings(unittest.TestCase):
    """Тестирование модели и персистентности настроек приложения."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "test_settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()
        reset_app_settings()

    def test_default_values(self):
        """Значения по умолчанию: звук и озвучивание включены."""
        settings = AppSettings(storage_path=self.settings_file)
        self.assertTrue(settings.notification_sound)
        self.assertTrue(settings.speak_reminders)

    def test_save_and_reload_persistence(self):
        """Проверка сохранения настроек и их корректной загрузки после перезапуска."""
        settings = AppSettings(storage_path=self.settings_file)
        settings.notification_sound = False
        settings.speak_reminders = False
        self.assertTrue(settings.save())

        self.assertTrue(self.settings_file.exists())

        # Создаем второй экземпляр, имитируя перезапуск приложения
        reloaded = AppSettings(storage_path=self.settings_file)
        self.assertFalse(reloaded.notification_sound)
        self.assertFalse(reloaded.speak_reminders)

    def test_get_and_set_methods(self):
        """Проверка методов get() и set()."""
        settings = AppSettings(storage_path=self.settings_file)
        settings.set("notification_sound", False)
        self.assertFalse(settings.get("notification_sound"))

        # Проверка кастомных ключей
        settings.set("theme", "cyber_dark")
        self.assertEqual(settings.get("theme"), "cyber_dark")

    def test_singleton_accessor(self):
        """Проверка синглтона get_app_settings."""
        s1 = get_app_settings(storage_path=self.settings_file)
        s2 = get_app_settings()
        self.assertIs(s1, s2)
        reset_app_settings()


class TestSoundPlayback(unittest.TestCase):
    """Тестирование воспроизведения системного звука и флагов активности."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "test_settings.json"
        self.settings = AppSettings(storage_path=self.settings_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("sys.platform", "win32")
    def test_play_notification_sound_enabled(self):
        """При включенном звуке вызывается play_system_sound."""
        self.settings.notification_sound = True
        with patch("notifications.sound.play_system_sound") as mock_play:
            mock_play.return_value = True
            res = play_notification_sound(self.settings)
            self.assertTrue(res)
            mock_play.assert_called_once_with("SystemNotification")

    def test_play_notification_sound_disabled(self):
        """При выключенном звуке системный звук не воспроизводится."""
        self.settings.notification_sound = False
        with patch("notifications.sound.play_system_sound") as mock_play:
            res = play_notification_sound(self.settings)
            self.assertFalse(res)
            mock_play.assert_not_called()

    @patch("sys.platform", "win32")
    def test_play_system_sound_winsound_success(self):
        """Проверка вызова winsound.PlaySound на платформе Windows."""
        with patch.dict("sys.modules", {"winsound": MagicMock()}):
            import winsound
            winsound.SND_ALIAS = 0x00010000
            winsound.SND_ASYNC = 0x00000001
            winsound.SND_NODEFAULT = 0x00000002

            res = play_system_sound("SystemNotification")
            self.assertTrue(res)
            winsound.PlaySound.assert_called_once()

    @patch("sys.platform", "win32")
    def test_play_system_sound_error_safety(self):
        """Сбой аудиоустройства не вызывает исключений и безопасно возвращает False."""
        with patch.dict("sys.modules", {"winsound": MagicMock()}):
            import winsound
            winsound.PlaySound.side_effect = RuntimeError("Audio driver failure")
            winsound.MessageBeep.side_effect = RuntimeError("Speaker failure")

            res = play_system_sound("SystemNotification")
            self.assertFalse(res)


class TestNotificationServiceIntegration(unittest.TestCase):
    """Тестирование интеграции звука с NotificationService."""

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "test_settings.json"
        self.settings = AppSettings(storage_path=self.settings_file)
        self.service = NotificationService(master=self.root, settings=self.settings)

    def tearDown(self):
        self.service.close_all()
        self.root.destroy()
        self.temp_dir.cleanup()

    def test_notify_calls_sound_when_enabled(self):
        """При показе уведомления вызывается play_notification_sound."""
        self.settings.notification_sound = True
        item = NotificationItem(id="test_1", title="Заголовок", text="Тест")

        with patch("notifications.service.play_notification_sound") as mock_snd:
            self.service.notify(item)
            mock_snd.assert_called_once_with(self.settings)

    def test_notify_sound_disabled(self):
        """При выключенном звуке play_notification_sound получает настройку с notification_sound=False."""
        self.settings.notification_sound = False
        item = NotificationItem(id="test_2", title="Заголовок", text="Тест")

        with patch("notifications.sound.play_system_sound") as mock_sys_play:
            self.service.notify(item)
            mock_sys_play.assert_not_called()


class TestGuiReminderAudioIntegration(unittest.TestCase):
    """Тестирование озвучивания напоминаний в AkakiyGUI._handle_reminder_due."""

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "test_settings.json"
        self.settings = AppSettings(storage_path=self.settings_file)

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()

    def test_reminder_due_speaks_when_enabled(self):
        """Если speak_reminders=True, вызывается voice.tts.speak."""
        from gui import AkakiyGUI

        with patch.object(AkakiyGUI, "_create_layout"), \
             patch.object(AkakiyGUI, "_start_clock"), \
             patch.object(AkakiyGUI, "_poll_queue"), \
             patch.object(AkakiyGUI, "_switch_section"), \
             patch("gui.GlobalHotKeyManager"):

            gui = AkakiyGUI(self.root)
            gui.settings = self.settings
            self.settings.speak_reminders = True

            # Мокируем голос и TTS
            mock_voice = MagicMock()
            mock_tts = MagicMock()
            mock_voice.tts = mock_tts
            gui.voice = mock_voice

            # Вызываем обработку напоминания
            rem = {"id": 42, "text": "Принять витамины", "remind_at": "2026-09-21 10:00:00"}
            gui._handle_reminder_due(rem)

            mock_tts.speak.assert_called_once_with("Напоминание: Принять витамины")

    def test_reminder_due_does_not_speak_when_disabled(self):
        """Если speak_reminders=False, voice.tts.speak НЕ вызывается."""
        from gui import AkakiyGUI

        with patch.object(AkakiyGUI, "_create_layout"), \
             patch.object(AkakiyGUI, "_start_clock"), \
             patch.object(AkakiyGUI, "_poll_queue"), \
             patch.object(AkakiyGUI, "_switch_section"), \
             patch("gui.GlobalHotKeyManager"):

            gui = AkakiyGUI(self.root)
            gui.settings = self.settings
            self.settings.speak_reminders = False

            mock_voice = MagicMock()
            mock_tts = MagicMock()
            mock_voice.tts = mock_tts
            gui.voice = mock_voice

            rem = {"id": 42, "text": "Принять витамины", "remind_at": "2026-09-21 10:00:00"}
            gui._handle_reminder_due(rem)

            mock_tts.speak.assert_not_called()

    def test_reminder_due_tts_error_safety(self):
        """Ошибка в TTS не прерывает работу GUI и обработчика напоминаний."""
        from gui import AkakiyGUI

        with patch.object(AkakiyGUI, "_create_layout"), \
             patch.object(AkakiyGUI, "_start_clock"), \
             patch.object(AkakiyGUI, "_poll_queue"), \
             patch.object(AkakiyGUI, "_switch_section"), \
             patch("gui.GlobalHotKeyManager"):

            gui = AkakiyGUI(self.root)
            gui.settings = self.settings
            self.settings.speak_reminders = True

            mock_voice = MagicMock()
            mock_tts = MagicMock()
            mock_tts.speak.side_effect = RuntimeError("Audio device busy")
            mock_voice.tts = mock_tts
            gui.voice = mock_voice

            rem = {"id": 42, "text": "Принять витамины", "remind_at": "2026-09-21 10:00:00"}
            # Метод должен успешно завершиться без исключения
            try:
                gui._handle_reminder_due(rem)
            except Exception as e:
                self.fail(f"_handle_reminder_due выбросил исключение при ошибке TTS: {e}")


class TestSettingsViewUI(unittest.TestCase):
    """Тестирование интерактивных настроек звука в SettingsView."""

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.temp_dir.name) / "test_settings.json"
        self.settings = AppSettings(storage_path=self.settings_file)

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()

    def test_toggle_sound_and_tts_buttons(self):
        from ui.views.settings import SettingsView

        fake_shell = MagicMock()
        fake_shell.settings = self.settings

        view = SettingsView(self.root, shell=fake_shell)

        # Изначально оба включены
        self.assertTrue(self.settings.notification_sound)
        self.assertTrue(self.settings.speak_reminders)
        self.assertEqual(view.btn_toggle_sound.cget("text"), "[ ВКЛ ]")
        self.assertEqual(view.btn_toggle_tts.cget("text"), "[ ВКЛ ]")

        # Переключаем звук
        view.toggle_notification_sound()
        self.assertFalse(self.settings.notification_sound)
        self.assertEqual(view.btn_toggle_sound.cget("text"), "[ ВЫКЛ ]")

        # Переключаем TTS
        view.toggle_speak_reminders()
        self.assertFalse(self.settings.speak_reminders)
        self.assertEqual(view.btn_toggle_tts.cget("text"), "[ ВЫКЛ ]")

        # Проверяем персистентность в файле
        reloaded = AppSettings(storage_path=self.settings_file)
        self.assertFalse(reloaded.notification_sound)
        self.assertFalse(reloaded.speak_reminders)

    def test_test_sound_button(self):
        from ui.views.settings import SettingsView

        fake_shell = MagicMock()
        fake_shell.settings = self.settings

        view = SettingsView(self.root, shell=fake_shell)

        with patch("notifications.sound.play_system_sound") as mock_sound:
            view.test_notification_sound()
            mock_sound.assert_called_once()


if __name__ == "__main__":
    unittest.main()
