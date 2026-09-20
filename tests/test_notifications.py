"""
Тестовый набор для модульной системы уведомлений Акакия.
Проверяет:
1. ReminderMonitor: обнаружение наступивших напоминаний, защиту от дубликатов, start/stop.
2. NotificationWindow & NotificationService: создание, стек окон, репозиционирование, закрытие, коллбэки действий (Выполнено / Отложить).
3. Интеграцию с AkakiyGUI: сквозной жизненный цикл уведомлений.
"""

from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.household import HouseholdManager
from notifications.models import NotificationAction, NotificationItem
from notifications.window import NotificationWindow
from notifications.service import NotificationService
from notifications.monitor import ReminderMonitor
from gui import AkakiyGUI


class TestReminderMonitor(unittest.TestCase):
    """Тестирование ReminderMonitor (без Tkinter)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_household.json"
        self.household = HouseholdManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_monitor_start_and_stop(self):
        callback = MagicMock()
        monitor = ReminderMonitor(
            household=self.household,
            on_reminder=callback,
            interval_sec=0.5
        )
        self.assertFalse(monitor.is_running())

        monitor.start()
        self.assertTrue(monitor.is_running())

        # Повторный start безопасен
        monitor.start()
        self.assertTrue(monitor.is_running())

        monitor.stop(timeout=1.0)
        self.assertFalse(monitor.is_running())

        # Повторный stop безопасен
        monitor.stop()
        self.assertFalse(monitor.is_running())

    def test_monitor_detects_due_reminder(self):
        callback = MagicMock()
        monitor = ReminderMonitor(
            household=self.household,
            on_reminder=callback,
            interval_sec=5.0
        )

        # Создаём напоминание с прошедшим временем
        past_time = "2026-09-20 12:00:00"
        self.household.create_reminder("Принять витамины", past_time)

        # Вызываем синхронную проверку
        due = monitor.check_now(current_time="2026-09-21 12:00:00")
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["text"], "Принять витамины")
        callback.assert_called_once_with(due[0])

    def test_monitor_deduplication(self):
        callback = MagicMock()
        monitor = ReminderMonitor(
            household=self.household,
            on_reminder=callback,
            interval_sec=5.0
        )

        past_time = "2026-09-20 12:00:00"
        self.household.create_reminder("Полить цветы", past_time)

        # Первая проверка — находит и вызывает callback
        due_first = monitor.check_now(current_time="2026-09-21 12:00:00")
        self.assertEqual(len(due_first), 1)
        self.assertEqual(callback.call_count, 1)

        # Вторая проверка — не должна повторно вызывать callback для того же напоминания
        due_second = monitor.check_now(current_time="2026-09-21 12:00:00")
        self.assertEqual(len(due_second), 0)
        self.assertEqual(callback.call_count, 1)

    def test_monitor_without_reminders(self):
        callback = MagicMock()
        monitor = ReminderMonitor(
            household=self.household,
            on_reminder=callback,
            interval_sec=5.0
        )
        due = monitor.check_now()
        self.assertEqual(len(due), 0)
        callback.assert_not_called()

    def test_monitor_handles_exception_gracefully(self):
        callback = MagicMock()
        broken_household = MagicMock()
        broken_household.check_due_reminders.side_effect = RuntimeError("Disk IO Error")

        monitor = ReminderMonitor(
            household=broken_household,
            on_reminder=callback,
            interval_sec=5.0
        )
        # Не должно выбрасывать исключение
        due = monitor.check_now()
        self.assertEqual(len(due), 0)
        callback.assert_not_called()


class TestNotificationServiceAndWindow(unittest.TestCase):
    """Тестирование NotificationWindow и NotificationService."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.service = NotificationService(self.root)

    def tearDown(self):
        try:
            self.service.close_all()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_create_single_notification(self):
        notif_id = self.service.show_info("Тест", "Текст информационного сообщения")
        self.root.update_idletasks()

        self.assertEqual(self.service.get_active_count(), 1)
        self.assertIn(notif_id, self.service.get_active_ids())

        win = self.service._active_windows[notif_id]
        self.assertIsInstance(win, NotificationWindow)
        self.assertTrue(win.winfo_exists())
        self.assertIn("Текст информационного сообщения", win.lbl_text.cget("text"))

    def test_multiple_notifications_and_stacking(self):
        id1 = self.service.show_info("Инфо 1", "Первое уведомление")
        id2 = self.service.show_info("Инфо 2", "Второе уведомление")
        id3 = self.service.show_info("Инфо 3", "Третье уведомление")
        self.root.update_idletasks()

        self.assertEqual(self.service.get_active_count(), 3)
        self.assertEqual(self.service.get_active_ids(), [id3, id2, id1])

        # Проверяем, что окна имеют разные Y координаты (стек)
        win1 = self.service._active_windows[id1]
        win2 = self.service._active_windows[id2]
        win3 = self.service._active_windows[id3]

        y1 = win1.winfo_y()
        y2 = win2.winfo_y()
        y3 = win3.winfo_y()

        # id3 самое свежее (в основании стека), id1 самое старое (вверху)
        self.assertGreater(y3, y2)
        self.assertGreater(y2, y1)

    def test_close_notification_and_restack(self):
        id1 = self.service.show_info("Инфо 1", "Первое")
        id2 = self.service.show_info("Инфо 2", "Второе")
        id3 = self.service.show_info("Инфо 3", "Третье")
        self.root.update_idletasks()

        # Закрываем среднее уведомление
        self.service.close(id2)
        self.root.update_idletasks()

        self.assertEqual(self.service.get_active_count(), 2)
        self.assertNotIn(id2, self.service.get_active_ids())

        # Оставшиеся окна аккуратно перекомпонованы
        win3 = self.service._active_windows[id3]
        win1 = self.service._active_windows[id1]
        self.assertTrue(win3.winfo_exists())
        self.assertTrue(win1.winfo_exists())

    def test_reminder_actions_complete_callback(self):
        on_complete = MagicMock()
        on_snooze = MagicMock()

        rem_id = self.service.show_reminder(
            title="Напоминание",
            text="Сдать отчет",
            timestamp_str="18:00",
            on_complete=on_complete,
            on_snooze=on_snooze
        )
        self.root.update_idletasks()

        win = self.service._active_windows[rem_id]
        self.assertEqual(len(win.action_buttons), 2)

        # Нажимаем первую кнопку ('✓ Выполнено')
        btn_complete = win.action_buttons[0]
        self.assertIn("Выполнено", btn_complete.cget("text"))
        btn_complete.invoke()
        self.root.update_idletasks()

        on_complete.assert_called_once()
        on_snooze.assert_not_called()
        self.assertEqual(self.service.get_active_count(), 0)

    def test_reminder_actions_snooze_callback(self):
        on_complete = MagicMock()
        on_snooze = MagicMock()

        rem_id = self.service.show_reminder(
            title="Напоминание",
            text="Позвонить клиенту",
            timestamp_str="19:00",
            on_complete=on_complete,
            on_snooze=on_snooze
        )
        self.root.update_idletasks()

        win = self.service._active_windows[rem_id]
        # Нажимаем вторую кнопку ('⏰ Отложить')
        btn_snooze = win.action_buttons[1]
        self.assertIn("Отложить", btn_snooze.cget("text"))
        btn_snooze.invoke()
        self.root.update_idletasks()

        on_snooze.assert_called_once()
        on_complete.assert_not_called()
        self.assertEqual(self.service.get_active_count(), 0)

    def test_close_button_dismiss(self):
        on_close = MagicMock()
        item = NotificationItem(
            id="test_dismiss",
            title="Тест",
            text="Проверка кнопки закрытия",
            on_close=on_close
        )
        self.service.notify(item)
        self.root.update_idletasks()

        win = self.service._active_windows["test_dismiss"]
        self.assertIsNotNone(win.btn_close)
        win.btn_close.invoke()
        self.root.update_idletasks()

        self.assertEqual(self.service.get_active_count(), 0)
        on_close.assert_called_once()

    def test_close_all(self):
        self.service.show_info("1", "Текст 1")
        self.service.show_info("2", "Текст 2")
        self.root.update_idletasks()
        self.assertEqual(self.service.get_active_count(), 2)

        self.service.close_all()
        self.root.update_idletasks()
        self.assertEqual(self.service.get_active_count(), 0)


class TestAkakiyGUIWithNotifications(unittest.TestCase):
    """Интеграционное тестирование системы уведомлений в AkakiyGUI."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_gui_household.json"
        self.household = HouseholdManager(storage_path=self.storage_path)

        self.mock_agent = MagicMock()
        self.mock_memory = MagicMock()
        self.mock_voice = MagicMock()
        self.mock_voice.is_running = False

        self.gui = AkakiyGUI(
            self.root,
            agent=self.mock_agent,
            household=self.household,
            memory=self.mock_memory,
            voice=self.mock_voice
        )
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.gui.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        self.temp_dir.cleanup()

    def test_gui_has_notification_system(self):
        self.assertIsNotNone(self.gui.notification_service)
        self.assertIsNotNone(self.gui.reminder_monitor)
        self.assertTrue(self.gui.reminder_monitor.is_running())

    def test_gui_reminder_notification_lifecycle(self):
        # Создаём наступившее напоминание
        past_time = "2026-09-20 10:00:00"
        res = self.household.create_reminder("Купить корм коту", past_time)
        rem_id = res["reminder"]["id"]

        # Запускаем проверку через монитор
        due = self.gui.reminder_monitor.check_now(current_time="2026-09-21 12:00:00")
        self.assertEqual(len(due), 1)

        # Выполняем polling очереди GUI
        self.gui._poll_queue()
        self.root.update_idletasks()

        # Окно уведомления появилось в notification_service
        self.assertEqual(self.gui.notification_service.get_active_count(), 1)
        notif_window = list(self.gui.notification_service._active_windows.values())[0]
        self.assertIn("Купить корм коту", notif_window.lbl_text.cget("text"))

        # Нажимаем кнопку '✓ Выполнено'
        btn_complete = notif_window.action_buttons[0]
        btn_complete.invoke()
        self.root.update_idletasks()

        # Напоминание удалено из household и уведомление закрыто
        self.assertEqual(self.gui.notification_service.get_active_count(), 0)
        rems = self.household.list_reminders(include_triggered=True)["reminders"]
        self.assertEqual(len(rems), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
