"""
Тестовый набор для экранов MemoryView и SettingsView (Task R3.4).
Проверяет изолированную работу представлений памяти и настроек/диагностики.
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.memory import MemoryManager
from ui.views import BaseView, MemoryView, SettingsView


class TestMemoryViewIsolated(unittest.TestCase):
    """Изолированное тестирование MemoryView."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_memory_view_isolated.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.memory = MemoryManager(storage_path=self.storage_path)
        self.mock_shell = MagicMock()
        self.mock_shell.memory = self.memory

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

    def test_memory_view_contract_and_crud(self):
        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.entry_mem)
        self.assertIsNotNone(view.mem_list_frame)

        # Empty state check
        children = view.mem_list_frame.winfo_children()
        self.assertGreater(len(children), 0)

        # Add memory fact
        view.entry_mem.insert(0, "Любимый язык программирования - Python")
        view.ui_remember()
        self.root.update_idletasks()

        mems = self.memory.get_all()
        self.assertEqual(len(mems), 1)
        mem_id = mems[0]["id"]
        self.assertIn("Python", mems[0]["text"])

        # Forget fact
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_forget(mem_id)
        self.assertEqual(len(self.memory.get_all()), 0)

    def test_memory_view_without_memory_service(self):
        empty_shell = MagicMock()
        empty_shell.memory = None

        view = MemoryView(self.root, shell=empty_shell)
        view.pack()
        self.root.update_idletasks()

        # Should gracefully display service unavailable message without crashing
        view.ui_remember()
        view.ui_forget(1)
        self.assertIsNotNone(view.mem_list_frame)


class TestSettingsViewIsolated(unittest.TestCase):
    """Изолированное тестирование SettingsView."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.mock_shell = MagicMock()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_settings_view_contract_and_render(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertIsInstance(view, BaseView)
        self.assertIsNotNone(view.lbl_val_res)

        # refresh() should execute cleanly as a no-op
        view.refresh()

    def test_settings_view_validation_success(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        custom_val = MagicMock(return_value={"success": True, "files_checked": 50, "errors": []})
        res = view.ui_run_validation(val_func=custom_val)
        custom_val.assert_called_once()
        self.assertTrue(res["success"])
        self.assertIn("Проект валиден", view.lbl_val_res.cget("text"))

    def test_settings_view_validation_failure(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        custom_val = MagicMock(return_value={"success": False, "files_checked": 10, "errors": ["SyntaxError in file.py"]})
        res = view.ui_run_validation(val_func=custom_val)
        custom_val.assert_called_once()
        self.assertFalse(res["success"])
        self.assertIn("Ошибки валидации", view.lbl_val_res.cget("text"))


if __name__ == "__main__":
    unittest.main()
