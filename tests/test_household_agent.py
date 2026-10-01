"""
Targeted tests for HouseholdAgent (Domain Agent Layer).

Проверяет:
1. Метаданные (name, description, capabilities, tools, to_dict).
2. Проверку возможностей (has_capability, has_tool).
3. Успешное выполнение реальных операций (задачи, заметки, напоминания, списки) через изолированный HouseholdManager.
4. Вызовы через естественный язык, явный action/tool и прямое имя метода.
5. Неизвестные/неподдерживаемые команды.
6. Обработку ошибок существующего household слоя (валидация, несуществующий ID, исключения).
7. Гарантированный возврат канонического AgentResult во всех сценариях.
8. Совместимость с AgentRegistry (регистрация, поиск по capability, поиск по tool, execute через registry).
"""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.household import HouseholdAgent
from agents.registry import AgentRegistry
from tools.agents.result import AgentResult
from tools.household import HouseholdManager


class TestHouseholdAgentMetadata(unittest.TestCase):
    """Тестирование метаданных и спецификации HouseholdAgent."""

    def setUp(self):
        self.agent = HouseholdAgent()

    def test_inheritance(self):
        self.assertIsInstance(self.agent, BaseAgent)

    def test_metadata_fields(self):
        self.assertEqual(self.agent.name, "household")
        self.assertTrue(len(self.agent.description) > 0)
        self.assertTrue(self.agent.enabled)

    def test_capabilities(self):
        expected_caps = ["household", "tasks", "reminders", "notes", "lists"]
        for cap in expected_caps:
            self.assertIn(cap, self.agent.capabilities)
            self.assertTrue(self.agent.has_capability(cap))
            self.assertTrue(self.agent.has_capability(cap.upper()))

        self.assertFalse(self.agent.has_capability("coding"))
        self.assertFalse(self.agent.has_capability("drawing"))

    def test_tools(self):
        expected_tools = [
            "create_task", "list_tasks", "complete_task", "delete_task",
            "create_reminder", "list_reminders", "complete_reminder", "delete_reminder",
            "check_due_reminders", "create_note", "list_notes", "search_notes", "delete_note",
            "create_list", "show_list", "add_list_item", "complete_list_item", "toggle_list_item",
            "delete_list_item", "delete_list"
        ]
        for t in expected_tools:
            self.assertIn(t, self.agent.tools)
            self.assertTrue(self.agent.has_tool(t))

        self.assertFalse(self.agent.has_tool("git_commit"))
        self.assertFalse(self.agent.has_tool("run_command"))

    def test_to_dict_serialization(self):
        d = self.agent.to_dict()
        self.assertEqual(d["name"], "household")
        self.assertIn("tasks", d["capabilities"])
        self.assertIn("create_task", d["tools"])
        self.assertTrue(d["enabled"])


class TestHouseholdAgentExecution(unittest.TestCase):
    """Тестирование реального исполнения бытовых сценариев через изолированный HouseholdManager."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_file = Path(self.temp_dir) / "test_household.json"
        self.hm = HouseholdManager(storage_path=self.storage_file)
        self.agent = HouseholdAgent(household_manager=self.hm)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_natural_language_task_lifecycle(self):
        # 1. Создание задачи через естественный язык
        res1 = self.agent.execute("создай задачу Купить молоко и хлеб")
        self.assertIsInstance(res1, AgentResult)
        self.assertTrue(res1.success)
        self.assertIn("создана", res1.message.lower())
        self.assertEqual(res1.data.get("task", {}).get("title"), "Купить молоко и хлеб")
        task_id = res1.data["task"]["id"]

        # 2. Просмотр списка задач
        res2 = self.agent.execute("покажи задачи")
        self.assertIsInstance(res2, AgentResult)
        self.assertTrue(res2.success)
        self.assertEqual(len(res2.data.get("tasks", [])), 1)

        # 3. Выполнение задачи
        res3 = self.agent.execute(f"выполни задачу {task_id}")
        self.assertIsInstance(res3, AgentResult)
        self.assertTrue(res3.success)
        self.assertTrue(res3.data.get("task", {}).get("completed"))

        # 4. Удаление задачи
        res4 = self.agent.execute(f"удали задачу {task_id}")
        self.assertIsInstance(res4, AgentResult)
        self.assertTrue(res4.success)
        self.assertEqual(len(self.hm.tasks), 0)

    def test_natural_language_notes(self):
        # Создание заметки
        res_create = self.agent.execute("создай заметку Рецепт: Яблочный пирог с корицей")
        self.assertTrue(res_create.success)
        self.assertIn("сохранена", res_create.message.lower())
        note_id = res_create.data["note"]["id"]

        # Поиск по заметкам
        res_search = self.agent.execute("найди в заметках корицей")
        self.assertTrue(res_search.success)
        self.assertEqual(len(res_search.data.get("notes", [])), 1)

        # Удаление заметки
        res_del = self.agent.execute(f"удали заметку {note_id}")
        self.assertTrue(res_del.success)
        self.assertEqual(len(self.hm.notes), 0)

    def test_natural_language_reminders(self):
        # Создание напоминания
        res = self.agent.execute("напомни позвонить врачу в 16:00")
        self.assertTrue(res.success)
        self.assertIn("установлено", res.message.lower())
        self.assertEqual(len(self.hm.reminders), 1)

        # Список напоминаний
        res_list = self.agent.execute("покажи напоминания")
        self.assertTrue(res_list.success)
        self.assertEqual(len(res_list.data.get("reminders", [])), 1)

    def test_natural_language_lists(self):
        # Создание списка
        res_create = self.agent.execute("создай список аптека")
        self.assertTrue(res_create.success)

        # Добавление пункта
        res_add = self.agent.execute("добавь в список аптека бинт")
        self.assertTrue(res_add.success)
        self.assertEqual(res_add.data.get("item", {}).get("text"), "бинт")

        # Просмотр списка
        res_show = self.agent.execute("покажи список аптека")
        self.assertTrue(res_show.success)
        self.assertEqual(len(res_show.data.get("items", [])), 1)

    def test_explicit_action_execution(self):
        # Вызов с явным указанием action и kwargs
        res = self.agent.execute("Купить корм для кота", action="create_task")
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("task", {}).get("title"), "Купить корм для кота")

        # Вызов с явным указанием tool и structured args
        res_list = self.agent.execute("", tool="list_tasks", status="pending")
        self.assertTrue(res_list.success)
        self.assertEqual(len(res_list.data.get("tasks", [])), 1)

    def test_direct_method_name_execution(self):
        # Вызов, где task сам является именем метода
        self.hm.create_task("Тестовая задача")
        res = self.agent.execute("list_tasks")
        self.assertTrue(res.success)
        self.assertEqual(len(res.data.get("tasks", [])), 1)

    def test_unsupported_commands(self):
        # 1. Неподдерживаемая / посторонняя команда
        res1 = self.agent.execute("нарисуй пейзаж акварелью")
        self.assertIsInstance(res1, AgentResult)
        self.assertFalse(res1.success)
        self.assertIn("не поддерживается", res1.message.lower())

        # 2. Не-бытовая команда проекта
        res2 = self.agent.execute("покажи файлы проекта")
        self.assertFalse(res2.success)
        self.assertIn("не поддерживается", res2.message.lower())

        # 3. Пустой запрос
        res3 = self.agent.execute("")
        self.assertFalse(res3.success)
        self.assertIn("пустой", res3.message.lower())

    def test_error_handling_from_household_layer(self):
        # 1. Ошибка валидации HouseholdManager: пустой заголовок задачи
        res1 = self.agent.execute("", action="create_task", title="")
        self.assertIsInstance(res1, AgentResult)
        self.assertFalse(res1.success)
        self.assertIn("не может быть пустым", res1.error)

        # 2. Ошибка бизнес-логики: несуществующий ID задачи
        res2 = self.agent.execute("выполни задачу 99999")
        self.assertIsInstance(res2, AgentResult)
        self.assertFalse(res2.success)
        self.assertIn("не найдена", res2.error)

        # 3. Непредвиденное исключение в HouseholdManager
        mock_hm = MagicMock()
        mock_hm.create_task.side_effect = OSError("Диск переполнен")
        broken_agent = HouseholdAgent(household_manager=mock_hm)

        res3 = broken_agent.execute("создай задачу Тест")
        self.assertIsInstance(res3, AgentResult)
        self.assertFalse(res3.success)
        self.assertIn("Диск переполнен", res3.error)


class TestHouseholdAgentRegistryIntegration(unittest.TestCase):
    """Тестирование совместимости HouseholdAgent с AgentRegistry."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.temp_dir = tempfile.mkdtemp()
        self.storage_file = Path(self.temp_dir) / "test_household_reg.json"
        self.hm = HouseholdManager(storage_path=self.storage_file)
        self.agent = HouseholdAgent(household_manager=self.hm)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_register_and_lookup(self):
        self.registry.register(self.agent)
        self.assertTrue(self.registry.has("household"))
        self.assertIs(self.registry.get("household"), self.agent)

    def test_find_by_capability(self):
        self.registry.register(self.agent)

        by_household = self.registry.find_by_capability("household")
        self.assertEqual(len(by_household), 1)
        self.assertIs(by_household[0], self.agent)

        by_tasks = self.registry.find_by_capability("tasks")
        self.assertEqual(len(by_tasks), 1)

        by_notes = self.registry.find_by_capability("notes")
        self.assertEqual(len(by_notes), 1)

        by_coding = self.registry.find_by_capability("coding")
        self.assertEqual(len(by_coding), 0)

    def test_find_by_tool(self):
        self.registry.register(self.agent)

        by_tool = self.registry.find_by_tool("create_task")
        self.assertEqual(len(by_tool), 1)
        self.assertIs(by_tool[0], self.agent)

        by_unsupported_tool = self.registry.find_by_tool("git_commit")
        self.assertEqual(len(by_unsupported_tool), 0)

    def test_execute_via_registry(self):
        self.registry.register(self.agent)

        res = self.registry.execute("household", "создай задачу Проверить интеграцию")
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertEqual(len(self.hm.tasks), 1)

    def test_disabled_agent_in_registry(self):
        self.registry.register(self.agent)
        self.registry.disable("household")

        res = self.registry.execute("household", "покажи задачи")
        self.assertIsInstance(res, AgentResult)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)


if __name__ == "__main__":
    unittest.main()
