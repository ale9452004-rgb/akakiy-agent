"""
Автоматизированный набор тестов для BaseView и UI-утилит (Task R3.2).
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ui.views.base import BaseView, _bind_hover, bind_hover
from gui import AkakiyGUI


class TestBaseView(unittest.TestCase):
    """Тестирование базового класса экрана (BaseView)."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_shell = MagicMock()
        self.mock_shell.agent = MagicMock()
        self.mock_shell.household = MagicMock()
        self.mock_shell.memory = MagicMock()
        self.mock_shell.voice = MagicMock()
        self.mock_shell.root = self.root

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_instantiation_and_contract(self):
        view = BaseView(self.root, shell=self.mock_shell)
        self.assertIsInstance(view, tk.Frame)
        self.assertEqual(view.shell, self.mock_shell)

        # Контрактные методы по умолчанию не падают
        view.render()
        view.refresh()

    def test_service_access_via_shell(self):
        view = BaseView(self.root, shell=self.mock_shell)
        self.assertEqual(view.agent, self.mock_shell.agent)
        self.assertEqual(view.household, self.mock_shell.household)
        self.assertEqual(view.memory, self.mock_shell.memory)
        self.assertEqual(view.voice, self.mock_shell.voice)

        # Без shell возвращает None
        orphan_view = BaseView(self.root, shell=None)
        self.assertIsNone(orphan_view.agent)
        self.assertIsNone(orphan_view.household)
        self.assertIsNone(orphan_view.memory)
        self.assertIsNone(orphan_view.voice)

    def test_navigation_delegation_to_shell(self):
        view = BaseView(self.root, shell=self.mock_shell)

        view.switch_section("tasks")
        self.mock_shell.switch_section.assert_called_once_with("tasks")

        view.switch_view("notes")
        self.mock_shell.switch_view.assert_called_once_with("notes")

    def test_theme_constants_match_gui(self):
        view = BaseView(self.root, shell=self.mock_shell)
        colors = [
            "BG_MAIN", "BG_PANEL", "BG_CARD", "BG_HOVER", "BG_ACTIVE",
            "BORDER_COL", "BORDER_LIGHT",
            "FG_WHITE", "FG_MAIN", "FG_MUTED", "FG_DIM",
            "ACCENT_BLUE", "ACCENT_CYAN", "ACCENT_PURPLE",
            "ACCENT_GREEN", "ACCENT_AMBER", "ACCENT_RED"
        ]
        for c in colors:
            self.assertTrue(hasattr(view, c), f"BaseView lacks {c}")
            self.assertEqual(getattr(view, c), getattr(AkakiyGUI, c), f"Color mismatch for {c}")

    def test_bind_hover_utility(self):
        self.root.deiconify()
        btn = tk.Button(self.root, text="Test", bg="#111111", fg="#ffffff")
        btn.pack()
        _bind_hover(btn, normal_bg="#111111", hover_bg="#222222", normal_fg="#ffffff", hover_fg="#00ffff")

        self.root.update()
        btn.event_generate("<Enter>", when="now")
        self.assertEqual(btn.cget("bg"), "#222222")
        self.assertEqual(btn.cget("fg"), "#00ffff")

        btn.event_generate("<Leave>", when="now")
        self.assertEqual(btn.cget("bg"), "#111111")
        self.assertEqual(btn.cget("fg"), "#ffffff")
        self.root.withdraw()


if __name__ == "__main__":
    unittest.main()
