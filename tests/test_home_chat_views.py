"""
Тестовый набор для экранов HomeView и ChatView (Task R3.5).
Проверяет изолированную работу дашборда и диалогового чата, а также их интеграцию с AkakiyGUI.
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.household import HouseholdManager
from tools.memory import MemoryManager
from ui.views import BaseView, HomeView, ChatView
from gui import AkakiyGUI


class TestHomeViewIsolated(unittest.TestCase):
    """Изолированное тестирование HomeView."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_home_view_isolated.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.household.create_task("Тестовая задача на главной")
        self.household.create_note("Заметка 1", "Тестовый контент заметки")
        self.household.create_list("покупки")
        self.household.add_list_item("покупки", "Яблоки")

        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household
        self.mock_shell.current_state = "idle"
        self.mock_shell.neural_core = None

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_home_view_contract_and_render(self):
        view = HomeView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.neural_core)
        self.assertEqual(self.mock_shell.neural_core, view.neural_core)

        # Проверка наличия элементов дашборда
        children = view.winfo_children()
        self.assertGreater(len(children), 0)

        # Тест быстрого завершения задачи
        tasks = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0]["id"]

        view.quick_complete_task(task_id)
        self.root.update_idletasks()

        pending_after = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(pending_after), 0)

    def test_home_view_without_household_service(self):
        empty_shell = MagicMock()
        empty_shell.household = None
        empty_shell.current_state = "idle"

        view = HomeView(self.root, shell=empty_shell)
        view.pack()
        self.root.update_idletasks()

        # Должен отображаться без ошибок
        view.refresh()
        self.assertIsNotNone(view.neural_core)


class TestChatViewIsolated(unittest.TestCase):
    """Изолированное тестирование ChatView."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_shell = MagicMock()
        self.mock_shell.chat_messages = []
        self.mock_shell.log_messages = []
        self.mock_shell.agent = MagicMock()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_chat_view_contract_and_messaging(self):
        view = ChatView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.chat_text)
        self.assertIsNotNone(view.log_text)

        # При первой инициализации с пустым чатом добавляется приветствие
        self.assertEqual(len(self.mock_shell.chat_messages), 1)
        self.assertIn("Привет!", self.mock_shell.chat_messages[0][1])

        # Добавление сообщений в чат и лог
        view.append_chat("Вы", "Привет, Акакий!")
        view.append_log("USER", "Привет, Акакий!")
        self.root.update_idletasks()

        self.assertEqual(len(self.mock_shell.chat_messages), 2)
        self.assertEqual(len(self.mock_shell.log_messages), 1)

        chat_content = view.chat_text.get("1.0", tk.END)
        self.assertIn("Привет, Акакий!", chat_content)
        self.assertIn("ВЫ", chat_content)

        log_content = view.log_text.get("1.0", tk.END)
        self.assertIn("Привет, Акакий!", log_content)
        self.assertIn("USER", log_content)

        # Очистка чата
        view.clear_chat()
        self.root.update_idletasks()

        self.assertEqual(len(self.mock_shell.chat_messages), 0)
        self.assertEqual(len(self.mock_shell.log_messages), 0)
        self.assertEqual(view.chat_text.get("1.0", tk.END).strip(), "")
        self.assertEqual(view.log_text.get("1.0", tk.END).strip(), "")
        self.mock_shell.agent.context_mgr.clear_history.assert_called_once()

    def test_chat_view_history_replay_on_render(self):
        # Предзаполненные сообщения в shell
        self.mock_shell.chat_messages = [("Вы", "Запомни номер 42", "12:00:00")]
        self.mock_shell.log_messages = [("USER", "Запомни номер 42", "12:00:00")]

        view = ChatView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        chat_content = view.chat_text.get("1.0", tk.END)
        self.assertIn("Запомни номер 42", chat_content)

        log_content = view.log_text.get("1.0", tk.END)
        self.assertIn("Запомни номер 42", log_content)


class TestHomeAndChatInAkakiyGUI(unittest.TestCase):
    """Интеграционное тестирование HomeView и ChatView внутри AkakiyGUI."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_gui_home_chat.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.household.create_task("Главная задача")

        self.memory = MagicMock()
        self.agent = MagicMock()
        self.voice = MagicMock()
        self.voice.is_running = False

        self.gui = AkakiyGUI(
            self.root,
            agent=self.agent,
            household=self.household,
            memory=self.memory,
            voice=self.voice
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
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_home_view_and_quick_complete(self):
        self.gui.switch_view("home")
        self.assertEqual(self.gui.current_view_name, "home")
        self.assertIsNotNone(self.gui.home_view)
        self.assertIsNotNone(self.gui.neural_core)

        tasks = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0]["id"]

        self.gui._quick_complete_task(task_id)
        self.root.update_idletasks()

        tasks_after = self.household.list_tasks(status="pending")["tasks"]
        self.assertEqual(len(tasks_after), 0)

    def test_chat_view_and_persistence(self):
        self.gui.switch_view("chat")
        self.assertEqual(self.gui.current_view_name, "chat")
        self.assertIsNotNone(self.gui.chat_view)
        self.assertIsNotNone(self.gui.chat_text)
        self.assertIsNotNone(self.gui.log_text)

        # Отправка сообщений
        self.gui._append_chat("Вы", "Как погода?")
        self.gui._append_log("USER", "Как погода?")
        self.gui._append_chat("Акакий", "Отличная!")
        self.gui._append_log("DONE", "Отвечено.")
        self.root.update_idletasks()

        self.assertIn("Как погода?", self.gui.chat_text.get("1.0", tk.END))
        self.assertIn("Отличная!", self.gui.chat_text.get("1.0", tk.END))

        # Переключение на другую вкладку и обратно
        self.gui.switch_view("tasks")
        self.assertEqual(self.gui.current_view_name, "tasks")

        self.gui.switch_view("chat")
        self.assertEqual(self.gui.current_view_name, "chat")
        # Сообщения восстановились из chat_messages
        self.assertIn("Как погода?", self.gui.chat_text.get("1.0", tk.END))
        self.assertIn("Отличная!", self.gui.chat_text.get("1.0", tk.END))

        # Очистка
        self.gui._clear_chat()
        self.root.update_idletasks()
        self.assertEqual(len(self.gui.chat_messages), 0)
        self.assertEqual(self.gui.chat_text.get("1.0", tk.END).strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
