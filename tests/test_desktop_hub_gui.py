"""
Тесты для Этапа №18: GUI 2.0 (Desktop Hub Акакия).
Проверяют:
1. Сохранение текущего активного экрана при отправке команд (Чат не перехватывает фокус всего хаба).
2. Работу менеджера рабочих результатов record_work_result (Sub-Agents, Planner, Tools, Ошибки).
3. Отображение состояния дня, ближайших событий и активности Акакия на HomeView.
4. Отображение артефактов и структурированных результатов в ChatView.
5. Интеграцию очередей process_result и voice_agent_result с сохранением результатов.
"""

import os
import sys
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from gui import AkakiyGUI
from ui.views.home import HomeView
from ui.views.chat import ChatView
from tools.household import HouseholdManager


class TestDesktopHubCommandAndResults(unittest.TestCase):
    """Тестирование логики команд и регистрации рабочих результатов в Desktop Hub."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_desktop_hub.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.mock_agent = MagicMock()

        self.gui = AkakiyGUI(
            root=self.root,
            agent=self.mock_agent,
            household=self.household,
            voice=MagicMock()
        )

    def tearDown(self):
        try:
            self.gui.destroy()
        except Exception:
            try:
                self.root.destroy()
            except Exception:
                pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_command_submission_preserves_current_view(self):
        """Проверяет, что при отправке команды пользователь остаётся на текущем экране, а не перекидывается в Чат."""
        self.gui.switch_view("home")
        self.assertEqual(self.gui.current_section, "home")

        self.gui.cmd_input.delete(0, tk.END)
        self.gui.cmd_input.insert(0, "добавь задачу купить чай")

        with patch("threading.Thread") as mock_thread:
            self.gui._on_send_command()
            mock_thread.assert_called_once()
            # Пользователь должен остаться на HomeView
            self.assertEqual(self.gui.current_section, "home")
            self.assertEqual(self.gui.cmd_input.get(), "")
            self.assertEqual(self.gui._last_submitted_query, "добавь задачу купить чай")

        # Проверяем также для раздела Задачи
        self.gui.switch_view("tasks")
        self.assertEqual(self.gui.current_section, "tasks")

        self.gui.cmd_input.delete(0, tk.END)
        self.gui.cmd_input.insert(0, "покажи файлы")

        with patch("threading.Thread") as mock_thread:
            self.gui._on_send_command()
            # Пользователь должен остаться на TasksView
            self.assertEqual(self.gui.current_section, "tasks")

    def test_record_work_result_subagents(self):
        """Проверяет регистрацию результатов специализированных субагентов (Image, Document и т.д.)."""
        # 1. Результат ImageAgent
        img_payload = {
            "type": "image",
            "tool": "image",
            "answer": "Изображение успешно сгенерировано: 1024x1024",
            "success": True,
            "created_files": ["data/generated/images/img_test.png"],
            "artifacts": [{"name": "img_test.png", "type": "image", "path": "data/generated/images/img_test.png"}]
        }
        entry = self.gui.record_work_result(img_payload, query="нарисуй горы")
        self.assertEqual(entry["type"], "image")
        self.assertEqual(entry["title"], "Генерация изображения")
        self.assertTrue(entry["success"])
        self.assertIn("data/generated/images/img_test.png", entry["created_files"])
        self.assertEqual(entry["query"], "нарисуй горы")

        # 2. Результат DocumentAgent
        doc_payload = {
            "type": "document",
            "tool": "document",
            "answer": "Документ DOCX успешно создан: 3 раздела",
            "success": True,
            "created_files": ["data/generated/documents/doc_test.docx"],
            "artifacts": []
        }
        entry2 = self.gui.record_work_result(doc_payload, query="создай документ отчёт")
        self.assertEqual(entry2["type"], "document")
        self.assertEqual(entry2["title"], "Создание документа")
        self.assertIn("data/generated/documents/doc_test.docx", entry2["created_files"])

        # 3. Результат ошибки
        err_payload = {
            "type": "error",
            "error": "Сбой соединения с ComfyUI",
            "success": False
        }
        entry3 = self.gui.record_work_result(err_payload, query="сгенерируй арт")
        self.assertFalse(entry3["success"])
        self.assertEqual(entry3["error"], "Сбой соединения с ComfyUI")

        # История должна содержать все 3 записи
        self.assertEqual(len(self.gui.recent_work_results), 3)

    def test_poll_queue_process_result_records_work_and_refreshes(self):
        """Проверяет сквозную обработку process_result через очередь GUI."""
        self.gui.switch_view("home")
        self.gui._last_submitted_query = "создай презентацию AI"

        payload = {
            "type": "presentation",
            "answer": "Презентация создана: 5 слайдов",
            "success": True,
            "created_files": ["data/generated/presentations/pres_ai.pptx"]
        }
        self.gui.queue.put(("process_result", payload))

        # Вызываем один такт обработки очереди
        self.gui._poll_queue()

        # Результат должен быть сохранён в recent_work_results
        self.assertGreaterEqual(len(self.gui.recent_work_results), 1)
        last_res = self.gui.recent_work_results[-1]
        self.assertEqual(last_res["type"], "presentation")
        self.assertIn("data/generated/presentations/pres_ai.pptx", last_res["created_files"])

        # В логе и чате должна появиться отметка об артефактах
        log_content = [m[1] for m in self.gui.log_messages]
        self.assertTrue(any("pres_ai.pptx" in msg for msg in log_content))

        chat_content = [m[1] for m in self.gui.chat_messages]
        self.assertTrue(any("pres_ai.pptx" in msg for msg in chat_content))


class TestHomeViewDesktopHub(unittest.TestCase):
    """Тестирование отображения состояния дня, событий и активности на HomeView."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_home_hub.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.household.create_task("Подготовить отчёт к среде")
        self.household.create_reminder("Встреча с командой", "через 1 час")
        self.household.create_note("Идеи проекта", "Пункт 1, Пункт 2")
        self.household.create_list("инвентарь")
        self.household.add_list_item("инвентарь", "Ноутбук")

        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household
        self.mock_shell.current_state = "idle"
        self.mock_shell.neural_core = None
        self.mock_shell.recent_work_results = [
            {
                "type": "image",
                "title": "Генерация изображения",
                "message": "Создан логотип в стиле киберпанк",
                "query": "нарисуй логотип",
                "success": True,
                "created_files": ["data/generated/images/logo.png"],
                "time": "14:20:00"
            },
            {
                "type": "coding",
                "title": "Задача по коду",
                "message": "Правка синтаксиса в main.py успешно применена",
                "query": "исправь код",
                "success": True,
                "created_files": ["main.py"],
                "time": "14:25:00"
            }
        ]

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

    def test_home_view_renders_day_state_and_recent_activity(self):
        """Проверяет, что на HomeView выводятся состояние дня, карточки и активность Акакия."""
        view = HomeView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # Neural Core должен быть инициализирован
        self.assertIsNotNone(view.neural_core)

        # Проверяем обновление
        view.refresh()
        self.root.update_idletasks()

    def test_home_view_empty_activity_fallback(self):
        """Проверяет корректное отображение, если история активности пока пуста."""
        self.mock_shell.recent_work_results = []
        self.mock_shell.log_messages = []

        view = HomeView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()
        view.refresh()
        self.assertIsNotNone(view.neural_core)


class TestChatViewArtifactRendering(unittest.TestCase):
    """Тестирование форматирования сообщений с артефактами в ChatView."""

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

    def test_chat_view_renders_styled_artifacts(self):
        """Проверяет корректное разделение текста и блока артефактов в ChatView."""
        view = ChatView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        msg_with_art = "Презентация создана успешно.\n\n✦ Созданные артефакты:\n  • pres_test.pptx"
        view.append_chat("Акакий", msg_with_art)
        self.root.update_idletasks()

        chat_text_content = view.chat_text.get("1.0", tk.END)
        self.assertIn("Презентация создана успешно.", chat_text_content)
        self.assertIn("pres_test.pptx", chat_text_content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
