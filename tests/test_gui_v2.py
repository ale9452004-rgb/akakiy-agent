"""
Automated unit & integration test suite for Akakiy GUI 2.0 and NeuralCore.
Verifies:
1. NeuralCore 3D mathematics, states, transitions, audio reactivity.
2. AkakiyGUI layout structure (Topbar, Sidebar, Main Workspace, Command Bar).
3. All 8 views navigation and data binding (Home, Chat, Tasks, Reminders, Notes, Lists, Memory, Settings).
4. Direct Household and Memory CRUD operations through GUI handlers.
5. Command Bar submission and confirmation mechanics.
"""

import sys
import os
import unittest
import tkinter as tk
from unittest.mock import MagicMock, patch

# Add workspace to path
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from ui.neural_core import NeuralCore
from gui import AkakiyGUI, AkakiyCloud
from tools.household import HouseholdManager
from tools.memory import MemoryManager


class TestNeuralCore(unittest.TestCase):
    """Unit tests for the NeuralCore procedural canvas component."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_initialization_and_nodes(self):
        core = NeuralCore(self.root, width=320, height=320, num_nodes=36)
        self.assertEqual(len(core.nodes), 36)
        self.assertEqual(core.state, "idle")
        self.assertIn("core", core.color_scheme)
        self.assertIn("glow", core.color_scheme)

    def test_state_transitions(self):
        core = NeuralCore(self.root, width=200, height=200)
        states = ["idle", "thinking", "working", "listening", "speaking", "error"]
        for s in states:
            core.set_state(s)
            self.assertEqual(core.state, s)
            self.assertIn("core", core.color_scheme)
            self.assertIn("glow", core.color_scheme)

        # Fallback on unknown state
        core.set_state("unknown_state")
        self.assertEqual(core.state, "idle")

    def test_audio_amplitude_and_pulse(self):
        core = NeuralCore(self.root, width=200, height=200)
        core.set_audio_level(0.75)
        self.assertAlmostEqual(core.audio_level, 0.75, places=2)

        # Value clamped
        core.set_audio_level(1.5)
        self.assertAlmostEqual(core.audio_level, 1.0, places=2)
        core.set_audio_level(-0.5)
        self.assertAlmostEqual(core.audio_level, 0.0, places=2)

        # Pulse test
        core.pulse(intensity=0.8)
        self.assertAlmostEqual(core.audio_level, 0.8, places=2)

    def test_render_frame_math(self):
        core = NeuralCore(self.root, width=200, height=200, num_nodes=20)
        core.pack()
        self.root.update_idletasks()
        # Items were rendered by _animate()
        items = core.find_all()
        self.assertGreater(len(items), 0)

    def test_lifecycle_start_stop(self):
        core = NeuralCore(self.root, width=150, height=150)
        core.stop()
        self.assertTrue(core._is_destroyed)
        core.start()
        self.assertFalse(core._is_destroyed)


class TestAkakiyGUIViews(unittest.TestCase):
    """Integration tests for AkakiyGUI 2.0 layout, view switching, and direct backend actions."""

    @classmethod
    def setUpClass(cls):
        cls.test_household_file = os.path.join(WORKSPACE, "scratch", "test_gui_household.json")
        cls.test_memory_file = os.path.join(WORKSPACE, "scratch", "test_gui_memory.json")
        for p in (cls.test_household_file, cls.test_memory_file):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    @classmethod
    def tearDownClass(cls):
        for p in (cls.test_household_file, cls.test_memory_file):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        # Mock agent to avoid slow LLM init during UI unit tests
        self.mock_agent = MagicMock()
        self.mock_agent.ollama = MagicMock()
        self.mock_agent.ollama.client = MagicMock()
        self.mock_agent.ollama.model = "qwen3:8b"
        self.mock_agent.context_mgr = MagicMock()

        self.household = HouseholdManager(self.test_household_file)
        self.memory = MemoryManager(self.test_memory_file)
        self.mock_voice = MagicMock()
        self.mock_voice.is_running = False

        # Instantiate GUI with injected dependencies
        self.gui = AkakiyGUI(
            self.root,
            agent=self.mock_agent,
            household=self.household,
            memory=self.memory,
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

    def test_initial_layout_structure(self):
        self.assertIsNotNone(self.gui.topbar)
        self.assertIsNotNone(self.gui.sidebar)
        self.assertIsNotNone(self.gui.workspace)
        self.assertIsNotNone(self.gui.cmd_bar)
        self.assertEqual(self.gui.current_view_name, "home")
        self.assertIsNotNone(self.gui.neural_core)

    def test_switch_all_views(self):
        views = ["home", "chat", "tasks", "reminders", "notes", "lists", "memory", "settings"]
        for view_name in views:
            self.gui.switch_view(view_name)
            self.assertEqual(self.gui.current_view_name, view_name)
            self.root.update_idletasks()
            # Workspace should have children
            children = self.gui.workspace.winfo_children()
            self.assertGreater(len(children), 0, f"View {view_name} rendered empty workspace")

    def test_household_tasks_crud_via_gui(self):
        self.gui.switch_view("tasks")
        # Add task via GUI entry
        self.gui.entry_task.insert(0, "Купить протеин")
        self.gui._ui_create_task()
        self.root.update_idletasks()

        tasks = self.gui.household.list_tasks(status="all")["tasks"]
        self.assertEqual(len(tasks), 1)
        task_id = tasks[0]["id"]
        self.assertEqual(tasks[0]["title"], "Купить протеин")

        # Toggle task
        self.gui._ui_toggle_task(task_id)
        updated = [t for t in self.gui.household.list_tasks(status="all")["tasks"] if t["id"] == task_id][0]
        self.assertTrue(updated.get("completed", False))

        # Delete task with confirmed prompt
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.gui._ui_delete_task(task_id)
        remaining = [t for t in self.gui.household.list_tasks(status="all")["tasks"] if t["id"] == task_id]
        self.assertEqual(len(remaining), 0)

    def test_household_reminders_crud_via_gui(self):
        self.gui.switch_view("reminders")
        self.gui.entry_rem_text.insert(0, "Полить цветы")
        self.gui.entry_rem_time.insert(0, "20:00")
        self.gui._ui_create_reminder()
        self.root.update_idletasks()

        rems = self.gui.household.list_reminders(include_triggered=True)["reminders"]
        self.assertEqual(len(rems), 1)
        rem_id = rems[0]["id"]
        self.assertEqual(rems[0]["text"], "Полить цветы")

        # Check due with info modal mock
        with patch("tkinter.messagebox.showinfo") as mock_info:
            self.gui._ui_check_reminders()
            mock_info.assert_called_once()

        # Delete reminder
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.gui._ui_delete_reminder(rem_id)
        remaining = [r for r in self.gui.household.list_reminders(include_triggered=True)["reminders"] if r["id"] == rem_id]
        self.assertEqual(len(remaining), 0)

    def test_household_notes_crud_via_gui(self):
        self.gui.switch_view("notes")
        self.gui.entry_note_title.insert(0, "Код домофона")
        self.gui.entry_note_content.insert(0, "Пин-код #4210")
        self.gui._ui_create_note()
        self.root.update_idletasks()

        notes = self.gui.household.list_notes()["notes"]
        self.assertEqual(len(notes), 1)
        note_id = notes[0]["id"]
        self.assertIn("4210", notes[0]["content"])

        # Search notes
        self.gui.entry_note_search.insert(0, "домофон")
        self.gui._refresh_notes_list()
        self.root.update_idletasks()

        # Delete note
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.gui._ui_delete_note(note_id)
        remaining = [n for n in self.gui.household.list_notes()["notes"] if n["id"] == note_id]
        self.assertEqual(len(remaining), 0)

    def test_household_lists_crud_via_gui(self):
        self.gui.switch_view("lists")
        self.gui.entry_new_list.insert(0, "продукты")
        self.gui._ui_create_list()
        self.root.update_idletasks()

        self.assertIn("продукты", self.gui.household.lists)

        # Select list and add item
        self.gui._select_list("продукты")
        self.gui.entry_item_text.insert(0, "Овсянка")
        self.gui._ui_add_item("продукты")
        self.root.update_idletasks()

        items = self.gui.household.lists["продукты"]
        self.assertEqual(len(items), 1)
        item_id = items[0]["id"]
        self.assertEqual(items[0]["text"], "Овсянка")

        # Toggle item
        self.gui._ui_toggle_item("продукты", item_id)
        self.assertTrue(self.gui.household.lists["продукты"][0]["completed"])

        # Delete list
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.gui._ui_delete_entire_list("продукты")
        self.assertNotIn("продукты", self.gui.household.lists)

    def test_memory_crud_via_gui(self):
        self.gui.switch_view("memory")
        self.gui.entry_mem.insert(0, "Любимый чай - улун Те Гуань Инь")
        self.gui._ui_remember()
        self.root.update_idletasks()

        mems = self.gui.memory.get_all()
        self.assertEqual(len(mems), 1)
        mem_id = mems[0]["id"]

        # Forget via GUI
        with patch("tkinter.messagebox.askyesno", return_value=True):
            self.gui._ui_forget(mem_id)
        search = self.gui.memory.search("Те Гуань Инь")
        self.assertEqual(len(search), 0)

    def test_command_bar_submission_and_neural_core_state(self):
        self.gui.switch_view("chat")
        self.gui.cmd_input.delete(0, tk.END)
        self.gui.cmd_input.insert(0, "Привет, Акакий!")

        with patch("threading.Thread") as mock_thread:
            self.gui._on_send_command()
            mock_thread.assert_called_once()
            # Entry should be cleared
            self.assertEqual(self.gui.cmd_input.get(), "")
            self.assertEqual(self.gui.neural_core.state, "thinking")

    def test_settings_validation_trigger(self):
        self.gui.switch_view("settings")
        self.root.update_idletasks()
        # Verify validation callback is callable
        with patch("gui.validate_project") as mock_val:
            mock_val.return_value = {"success": True, "files_checked": 43, "errors": []}
            self.gui._ui_run_validation()
            mock_val.assert_called_once()
            self.assertIn("Проект валиден", self.gui.lbl_val_res.cget("text"))

    def test_backwards_compatibility_exports(self):
        # Verify AkakiyCloud is still importable and instantiable
        cloud = AkakiyCloud(self.root, width=100, height=100)
        self.assertIsNotNone(cloud)
        cloud.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
