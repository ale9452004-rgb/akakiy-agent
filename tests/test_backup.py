"""
Тесты для модуля резервного копирования и восстановления данных tools/backup.py.
"""

import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from commands import handle_cli_command, show_help
from tools.backup import (
    CURRENT_BACKUP_VERSION,
    export_data,
    import_data,
    validate_backup,
)
from tools.household import HouseholdManager
from tools.memory import MemoryManager
from ui.views.settings import SettingsView


class TestBackupValidation(unittest.TestCase):
    """Тестирование валидации резервных копий."""

    def test_validate_valid_dict(self):
        valid_payload = {
            "akakiy_backup_version": 1,
            "created_at": "2026-09-21T03:00:00",
            "app_version": "2.0",
            "data": {
                "household": {
                    "tasks": [{"id": 1, "title": "Task 1", "completed": False}],
                    "reminders": [],
                    "notes": [{"id": 1, "title": "Note 1", "content": "test"}],
                    "lists": {"groceries": [{"id": 1, "text": "Milk", "completed": False}]},
                },
                "memory": {
                    "memories": [{"id": 1, "fact": "Пользователь любит чай"}],
                },
            },
        }
        ok, msg, parsed = validate_backup(valid_payload)
        self.assertTrue(ok)
        self.assertEqual(msg, "OK")
        self.assertIsNotNone(parsed)

    def test_validate_nonexistent_file(self):
        ok, msg, parsed = validate_backup("non_existent_file_path_12345.json")
        self.assertFalse(ok)
        self.assertIn("не найден", msg)
        self.assertIsNone(parsed)

    def test_validate_corrupted_json(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
            f.write("{corrupted json content...")
            tmp_path = f.name

        try:
            ok, msg, parsed = validate_backup(tmp_path)
            self.assertFalse(ok)
            self.assertIn("не является корректным JSON", msg)
            self.assertIsNone(parsed)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_validate_missing_version(self):
        payload = {"data": {"household": {}, "memory": {}}}
        ok, msg, parsed = validate_backup(payload)
        self.assertFalse(ok)
        self.assertIn("akakiy_backup_version", msg)

    def test_validate_incompatible_version(self):
        payload = {
            "akakiy_backup_version": 999,
            "data": {"household": {}, "memory": {}},
        }
        ok, msg, parsed = validate_backup(payload)
        self.assertFalse(ok)
        self.assertIn("Неподдерживаемая версия", msg)

    def test_validate_invalid_household_structure(self):
        payload = {
            "akakiy_backup_version": 1,
            "data": {
                "household": {
                    "tasks": "not a list",
                    "reminders": [],
                    "notes": [],
                    "lists": {},
                },
                "memory": {"memories": []},
            },
        }
        ok, msg, parsed = validate_backup(payload)
        self.assertFalse(ok)
        self.assertIn("tasks", msg)

    def test_validate_invalid_memory_structure(self):
        payload = {
            "akakiy_backup_version": 1,
            "data": {
                "household": {
                    "tasks": [],
                    "reminders": [],
                    "notes": [],
                    "lists": {},
                },
                "memory": {"memories": "not a list"},
            },
        }
        ok, msg, parsed = validate_backup(payload)
        self.assertFalse(ok)
        self.assertIn("memories", msg)


class TestBackupExportImport(unittest.TestCase):
    """Тестирование экспорта, импорта и транзакционности."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        self.h_file = self.temp_path / "household.json"
        self.m_file = self.temp_path / "memory.json"

        # Инициализируем менеджеры с кастомными путями storage_path
        self.household = HouseholdManager(storage_path=self.h_file)
        self.memory = MemoryManager(storage_path=self.m_file)

        # Заполняем тестовыми данными
        self.household.create_task("Купить хлеб")
        self.household.create_note("Заметка о встрече", "Подробности встречи")
        self.household.add_list_item("покупки", "сыр")
        self.household.create_reminder("Позвонить врачу", "2026-12-31 10:00")

        self.memory.remember("Пользователь программирует на Python", category="work")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_creates_valid_json_with_metadata(self):
        out_file = self.temp_path / "backup.json"
        res = export_data(output_path=out_file, household=self.household, memory=self.memory)

        self.assertTrue(res["success"])
        self.assertTrue(out_file.exists())

        with open(out_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["akakiy_backup_version"], CURRENT_BACKUP_VERSION)
        self.assertEqual(data["app_version"], "2.0")
        self.assertIn("created_at", data)
        self.assertIn("stats", data)
        self.assertEqual(data["stats"]["tasks_count"], 1)
        self.assertEqual(data["stats"]["reminders_count"], 1)
        self.assertEqual(data["stats"]["notes_count"], 1)
        self.assertEqual(data["stats"]["lists_count"], 1)
        self.assertEqual(data["stats"]["memories_count"], 1)

    def test_export_rejects_saving_inside_data_dir(self):
        from config import PROJECT_PATH
        data_dir_file = PROJECT_PATH / "data" / "sub" / "leak_backup.json"
        res = export_data(output_path=data_dir_file, household=self.household, memory=self.memory)
        self.assertFalse(res["success"])
        self.assertIn("Запрещено сохранять backup-файлы внутри каталога data/", res["error"])

    def test_round_trip_export_clear_import(self):
        out_file = self.temp_path / "backup_roundtrip.json"
        export_res = export_data(output_path=out_file, household=self.household, memory=self.memory)
        self.assertTrue(export_res["success"])

        # Очищаем данные на диске и в памяти
        self.h_file.write_text(json.dumps({"tasks": [], "reminders": [], "notes": [], "lists": {}}), encoding="utf-8")
        self.m_file.write_text(json.dumps([]), encoding="utf-8")
        self.household.reload()
        self.memory.reload()

        self.assertEqual(len(self.household.tasks), 0)
        self.assertEqual(len(self.household.notes), 0)
        self.assertEqual(len(self.memory.memories), 0)

        # Импортируем обратно
        import_res = import_data(input_path=out_file, household=self.household, memory=self.memory)
        self.assertTrue(import_res["success"])

        # Проверяем, что менеджеры содержат восстановленные данные
        self.assertEqual(len(self.household.tasks), 1)
        self.assertEqual(self.household.tasks[0]["title"], "Купить хлеб")
        self.assertEqual(len(self.household.notes), 1)
        self.assertEqual(self.household.notes[0]["title"], "Заметка о встрече")
        self.assertEqual(len(self.household.reminders), 1)
        self.assertEqual(self.household.lists["покупки"][0]["text"], "сыр")
        self.assertEqual(len(self.memory.memories), 1)
        self.assertEqual(self.memory.memories[0]["text"], "Пользователь программирует на Python")

    def test_import_invalid_file_does_not_change_data(self):
        invalid_file = self.temp_path / "corrupted.json"
        invalid_file.write_text("invalid json...", encoding="utf-8")

        initial_tasks = list(self.household.tasks)
        initial_memories = list(self.memory.memories)

        res = import_data(input_path=invalid_file, household=self.household, memory=self.memory)
        self.assertFalse(res["success"])

        # Проверяем, что данные не затронуты
        self.assertEqual(self.household.tasks, initial_tasks)
        self.assertEqual(self.memory.memories, initial_memories)

    def test_import_rollback_on_failure(self):
        # Экспортируем данные во временный бэкап с новыми значениями
        new_backup_file = self.temp_path / "new_backup.json"
        payload = {
            "akakiy_backup_version": 1,
            "created_at": "2026-09-21T03:00:00",
            "app_version": "2.0",
            "data": {
                "household": {
                    "tasks": [{"id": 99, "title": "Новая задача", "completed": False}],
                    "reminders": [],
                    "notes": [],
                    "lists": {},
                },
                "memory": {
                    "memories": [{"id": 100, "text": "Новый факт"}],
                },
            },
        }
        new_backup_file.write_text(json.dumps(payload), encoding="utf-8")

        original_h_content = self.h_file.read_text(encoding="utf-8")
        original_m_content = self.m_file.read_text(encoding="utf-8")

        orig_replace = os.replace

        def failing_replace(src, dst):
            if str(dst) == str(self.m_file):
                raise IOError("Disk write error simulation during memory write!")
            return orig_replace(src, dst)

        with patch("tools.backup.os.replace", side_effect=failing_replace):
            res = import_data(input_path=new_backup_file, household=self.household, memory=self.memory)

        self.assertFalse(res["success"])
        self.assertIn("Disk write error simulation", res["error"])

        # Проверяем, что household.json откатился к прежнему состоянию!
        current_h_content = self.h_file.read_text(encoding="utf-8")
        current_m_content = self.m_file.read_text(encoding="utf-8")
        self.assertEqual(current_h_content, original_h_content)
        self.assertEqual(current_m_content, original_m_content)
        self.assertEqual(self.household.tasks[0]["title"], "Купить хлеб")


class TestBackupCLIIntegration(unittest.TestCase):
    """Тестирование CLI-команд :export и :import."""

    @patch("commands.export_data")
    def test_cli_export_command(self, mock_export):
        mock_export.return_value = {
            "success": True,
            "message": "Экспорт выполнен успешно",
            "path": r"C:\backups\test.json",
            "stats": {"tasks_count": 1, "reminders_count": 0, "notes_count": 0, "lists_count": 0, "memories_count": 2},
        }

        with patch("sys.stdout"):
            handled = handle_cli_command(":export my_backup.json")

        self.assertTrue(handled)
        mock_export.assert_called_once_with(output_path="my_backup.json")

    @patch("commands.import_data")
    def test_cli_import_command(self, mock_import):
        mock_import.return_value = {
            "success": True,
            "message": "Импорт выполнен успешно",
            "path": r"C:\backups\test.json",
            "stats": {"tasks_count": 5, "reminders_count": 1, "notes_count": 2, "lists_count": 1, "memories_count": 3},
        }

        with patch("sys.stdout"):
            handled = handle_cli_command(":import my_backup.json")

        self.assertTrue(handled)
        mock_import.assert_called_once_with(input_path="my_backup.json")

    def test_cli_import_missing_argument(self):
        buf = []
        with patch("builtins.print", side_effect=buf.append):
            handled = handle_cli_command(":import")

        self.assertTrue(handled)
        output = "\n".join(buf)
        self.assertIn("Использование", output)

    def test_show_help_contains_export_import(self):
        buf = []
        with patch("builtins.print", side_effect=buf.append):
            show_help()

        output = "\n".join(buf)
        self.assertIn(":export", output)
        self.assertIn(":import", output)


class TestBackupGUISettingsIntegration(unittest.TestCase):
    """Тестирование фасадных вызовов GUI для экспорта/импорта."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.mock_shell = MagicMock()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_ui_export_data_cancel(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.lbl_backup_res = MagicMock()

        with patch("ui.views.settings.filedialog.asksaveasfilename", return_value=""):
            res = view.ui_export_data()

        self.assertIsNone(res)
        self.assertEqual(view.lbl_backup_res.config.call_count, 0)

    @patch("ui.views.settings.export_data")
    def test_ui_export_data_success(self, mock_export):
        mock_export.return_value = {
            "success": True,
            "message": "Экспорт выполнен",
            "path": "C:/test_backup.json",
            "stats": {"tasks_count": 2, "reminders_count": 1, "notes_count": 0, "lists_count": 1, "memories_count": 5},
        }
        view = SettingsView(self.root, shell=self.mock_shell)
        view.lbl_backup_res = MagicMock()

        with patch("ui.views.settings.filedialog.asksaveasfilename", return_value="C:/test_backup.json"):
            res = view.ui_export_data()

        mock_export.assert_called_once_with(
            output_path="C:/test_backup.json",
            household=self.mock_shell.household,
            memory=self.mock_shell.memory,
        )
        self.assertTrue(res["success"])
        view.lbl_backup_res.config.assert_called_once()
        self.assertIn("Экспорт выполнен", view.lbl_backup_res.config.call_args[1]["text"])

    def test_ui_import_data_cancel_file(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.lbl_backup_res = MagicMock()

        with patch("ui.views.settings.filedialog.askopenfilename", return_value=""):
            res = view.ui_import_data()

        self.assertIsNone(res)
        self.assertEqual(view.lbl_backup_res.config.call_count, 0)

    def test_ui_import_data_cancel_confirm(self):
        view = SettingsView(self.root, shell=self.mock_shell)
        view.lbl_backup_res = MagicMock()

        with patch("ui.views.settings.filedialog.askopenfilename", return_value="C:/backup.json"):
            with patch("ui.views.settings.messagebox.askyesno", return_value=False):
                res = view.ui_import_data()

        self.assertIsNone(res)
        self.assertEqual(view.lbl_backup_res.config.call_count, 0)

    @patch("ui.views.settings.import_data")
    def test_ui_import_data_success(self, mock_import):
        mock_import.return_value = {
            "success": True,
            "message": "Импорт успешно завершен",
            "path": "C:/backup.json",
            "stats": {"tasks_count": 3, "reminders_count": 0, "notes_count": 1, "lists_count": 2, "memories_count": 4},
        }
        view = SettingsView(self.root, shell=self.mock_shell)
        view.lbl_backup_res = MagicMock()

        with patch("ui.views.settings.filedialog.askopenfilename", return_value="C:/backup.json"):
            with patch("ui.views.settings.messagebox.askyesno", return_value=True):
                res = view.ui_import_data()

        mock_import.assert_called_once_with(
            input_path="C:/backup.json",
            household=self.mock_shell.household,
            memory=self.mock_shell.memory,
        )
        self.mock_shell.refresh_current_view.assert_called_once()
        self.assertTrue(res["success"])
        view.lbl_backup_res.config.assert_called_once()
        self.assertIn("Импорт успешно завершен", view.lbl_backup_res.config.call_args[1]["text"])


if __name__ == "__main__":
    unittest.main()
