"""
Набор тестов для модульных экранов бытовых сервисов (Tasks, Reminders, Notes, Lists) (Task R3.3).
Проверяет как изолированную работу каждого View, так и интеграцию с Shell (AkakiyGUI).
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

# Обеспечиваем импорт из корня проекта
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from ui.views import TasksView, RemindersView, NotesView, ListsView, BaseView
from tools.household import HouseholdManager


class TestIsolatedHouseholdViews(unittest.TestCase):
    """Изолированное тестирование классов экранов с реальным HouseholdManager."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_views_isolated.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)

        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household
        self.mock_shell.current_selected_list = ""

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

    def test_tasks_view_isolated_crud(self):
        view = TasksView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.entry_task)
        self.assertIsNotNone(view.tasks_list_frame)

        # Create task
        view.entry_task.insert(0, "Купить яблоки")
        view.ui_create_task()
        self.root.update_idletasks()

        tasks = self.household.list_tasks(status="all")["tasks"]
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0]["id"]
        self.assertEqual(tasks[0]["title"], "Купить яблоки")

        # Toggle task
        view.ui_toggle_task(task_id)
        task = self.household.list_tasks(status="all")["tasks"][0]
        self.assertTrue(task["completed"])

        # Delete task
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_task(task_id)
        self.assertEqual(len(self.household.list_tasks(status="all")["tasks"]), 0)

    def test_reminders_view_isolated_crud(self):
        view = RemindersView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.entry_rem_text)
        self.assertIsNotNone(view.entry_rem_time)
        self.assertIsNotNone(view.rems_list_frame)

        # Create reminder
        view.entry_rem_text.insert(0, "Принять витамины")
        view.entry_rem_time.insert(0, "12:00")
        view.ui_create_reminder()
        self.root.update_idletasks()

        rems = self.household.list_reminders(include_triggered=True)["reminders"]
        self.assertEqual(len(rems), 1)
        rem_id = rems[0]["id"]
        self.assertEqual(rems[0]["text"], "Принять витамины")

        # Check due reminders
        with patch("tkinter.messagebox.showinfo") as mock_info:
            view.ui_check_reminders()
            mock_info.assert_called_once()

        # Delete reminder
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_reminder(rem_id)
        self.assertEqual(len(self.household.list_reminders(include_triggered=True)["reminders"]), 0)

    def test_notes_view_isolated_crud(self):
        view = NotesView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.entry_note_title)
        self.assertIsNotNone(view.entry_note_content)
        self.assertIsNotNone(view.entry_note_search)
        self.assertIsNotNone(view.notes_list_frame)

        # Create note
        view.entry_note_title.insert(0, "Рецепт сырников")
        view.entry_note_content.insert(0, "Творог 400г, 1 яйцо, 2 ложки муки")
        view.ui_create_note()
        self.root.update_idletasks()

        notes = self.household.list_notes()["notes"]
        self.assertEqual(len(notes), 1)
        note_id = notes[0]["id"]
        self.assertEqual(notes[0]["title"], "Рецепт сырников")

        # Search filter
        view.entry_note_search.insert(0, "сырники")
        view.refresh()
        self.root.update_idletasks()

        # Delete note
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_note(note_id)
        self.assertEqual(len(self.household.list_notes()["notes"]), 0)

    def test_lists_view_isolated_crud(self):
        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.entry_new_list)
        self.assertIsNotNone(view.list_names_box)
        self.assertIsNotNone(view.right_items_pane)

        # Create list
        view.entry_new_list.insert(0, "инструменты")
        view.ui_create_list()
        self.root.update_idletasks()
        self.assertIn("инструменты", self.household.lists)

        # Select list and add item
        view.select_list("инструменты")
        self.assertIsNotNone(view.entry_item_text)
        view.entry_item_text.insert(0, "Отвертка")
        view.ui_add_item("инструменты")
        self.root.update_idletasks()

        items = self.household.lists["инструменты"]
        self.assertEqual(len(items), 1)
        item_id = items[0]["id"]
        self.assertEqual(items[0]["text"], "Отвертка")

        # Toggle item
        view.ui_toggle_item("инструменты", item_id)
        self.assertTrue(self.household.lists["инструменты"][0]["completed"])

        # Delete item
        view.ui_delete_item("инструменты", item_id)
        self.assertEqual(len(self.household.lists["инструменты"]), 0)

        # Delete list
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_entire_list("инструменты")
        self.assertNotIn("инструменты", self.household.lists)


if __name__ == "__main__":
    unittest.main()
