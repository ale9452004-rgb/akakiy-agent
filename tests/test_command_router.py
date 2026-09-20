"""
Автоматизированный набор тестов для CommandRouter (Task R2).

Проверяет:
1. Детерминированный fast-path проекта: find_file, list_files, search_files.
2. Детерминированный fast-path бытового слоя: задачи, заметки, напоминания, списки.
3. Распознавание и роутинг команд памяти: remember, recall, forget, search, clear.
4. Распознавание и роутинг команд управления планами: create, execute, get, clear.
5. Интеграцию с оркестратором Agent.process() и сохранение контрактов.
6. Отсутствие регрессий в choose_tool() и задержку маршрутизации (< 1 мс).
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.router import CommandRouter, get_router
from tools.agent import Agent
from tools.memory import MemoryManager
from tools.context import ContextManager
from tools.household import HouseholdManager


class TestCommandRouterProject(unittest.TestCase):
    """1. Проверка fast-path для проектных CLI команд."""

    def setUp(self):
        self.router = CommandRouter()

    def test_find_file(self):
        cases = [
            ("найди файл main.py", "main.py"),
            ("найти в проекте файл tools/agent.py", "tools/agent.py"),
            ("найди файл config.py.", "config.py"),
        ]
        for cmd, expected_file in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], "find_file")
            self.assertEqual(res["arguments"]["filename"], expected_file)

            route = self.router.route(cmd)
            self.assertEqual(route["type"], "tool")
            self.assertEqual(route["tool"], "find_file")
            self.assertEqual(route["arguments"]["filename"], expected_file)

    def test_list_files_and_structure(self):
        cases = [
            "покажи список файлов проекта",
            "покажи файлы",
            "структура проекта",
            "покажи структуру проекта",
        ]
        for cmd in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], "list_files")
            route = self.router.route(cmd)
            self.assertEqual(route["type"], "tool")
            self.assertEqual(route["tool"], "list_files")

    def test_search_files(self):
        # Поиск функции
        res_fn = self.router.choose_tool("найди функцию choose_tool")
        self.assertEqual(res_fn["tool"], "search_files")
        self.assertEqual(res_fn["arguments"]["query"], "def choose_tool")

        # Поиск текста
        res_text = self.router.choose_tool("поиск по проекту CommandRouter")
        self.assertEqual(res_text["tool"], "search_files")
        self.assertEqual(res_text["arguments"]["query"], "CommandRouter")


class TestCommandRouterHousehold(unittest.TestCase):
    """2. Проверка fast-path для бытового слоя (Tasks, Notes, Reminders, Lists)."""

    def setUp(self):
        self.router = CommandRouter()

    def test_task_routing(self):
        cases = [
            ("создай задачу купить свежий хлеб", "create_task", {"title": "купить свежий хлеб"}),
            ("задача: обновить документацию", "create_task", {"title": "обновить документацию"}),
            ("покажи задачи", "list_tasks", {"status": "all"}),
            ("активные задачи", "list_tasks", {"status": "pending"}),
            ("выполненные задачи", "list_tasks", {"status": "completed"}),
            ("выполни задачу 1", "complete_task", {"task_id": "1"}),
            ("отметь сделанной задачу #5", "complete_task", {"task_id": "#5"}),
            ("удали задачу 2", "delete_task", {"task_id": "2"}),
            ("удали последние 3 задачи", "delete_task", {"task_id": "последние 3"}),
        ]
        for cmd, exp_tool, exp_args in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], exp_tool, f"Failed for {cmd}")
            self.assertEqual(res["arguments"], exp_args, f"Failed args for {cmd}")

    def test_note_routing(self):
        cases = [
            ("создай заметку Рецепт: Мука 200г, Сахар 100г", "create_note", {"title": "Рецепт", "content": "Мука 200г, Сахар 100г"}),
            ("создай заметку купить батарейки", "create_note", {"title": "купить батарейки", "content": "купить батарейки"}),
            ("покажи заметки", "list_notes", {}),
            ("найди в заметках Мука", "search_notes", {"query": "Мука"}),
            ("удали заметку 1", "delete_note", {"note_id": "1"}),
            ("удали последние три заметки", "delete_note", {"note_id": "последние три"}),
        ]
        for cmd, exp_tool, exp_args in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], exp_tool, f"Failed for {cmd}")
            self.assertEqual(res["arguments"], exp_args, f"Failed args for {cmd}")

    def test_reminder_routing(self):
        cases = [
            ("напомни позвонить врачу завтра в 10:00", "create_reminder", {"text": "позвонить врачу", "remind_at": "завтра в 10:00"}),
            ("покажи напоминания", "list_reminders", {}),
            ("удали напоминание 1", "delete_reminder", {"reminder_id": "1"}),
            ("удали последнее напоминание", "delete_reminder", {"reminder_id": "последнее"}),
        ]
        for cmd, exp_tool, exp_args in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], exp_tool, f"Failed for {cmd}")
            self.assertEqual(res["arguments"], exp_args, f"Failed args for {cmd}")

    def test_list_routing(self):
        cases = [
            ("покажи списки", "show_list", {}),
            ("открой список Покупки", "show_list", {"name": "Покупки"}),
            ("создай список Покупки", "create_list", {"name": "Покупки"}),
            ("добавь в список Покупки Молоко", "add_list_item", {"list_name": "Покупки", "text": "Молоко"}),
        ]
        for cmd, exp_tool, exp_args in cases:
            res = self.router.choose_tool(cmd)
            self.assertEqual(res["tool"], exp_tool, f"Failed for {cmd}")
            self.assertEqual(res["arguments"], exp_args, f"Failed args for {cmd}")


class TestCommandRouterMemory(unittest.TestCase):
    """3. Проверка распознавания и роутинга команд памяти."""

    def setUp(self):
        self.router = CommandRouter()

    def test_match_memory_remember(self):
        m1 = self.router.match_memory("запомни: Мой любимый напиток кофе")
        self.assertIsNotNone(m1)
        self.assertEqual(m1["action"], "remember")
        self.assertEqual(m1["text"], "Мой любимый напиток кофе")

        m2 = self.router.match_memory("сохрани в память сервер на порту 8080")
        self.assertIsNotNone(m2)
        self.assertEqual(m2["action"], "remember")
        self.assertEqual(m2["text"], "сервер на порту 8080")

        # Проверяем choose_tool для обратной совместимости
        res = self.router.choose_tool("запомни мой любимый чай зеленый")
        self.assertEqual(res["tool"], "remember")
        self.assertEqual(res["arguments"]["text"], "мой любимый чай зеленый")

    def test_match_memory_recall(self):
        recalls = ["что ты помнишь", "что помнишь", "покажи память", "список памяти", "что в памяти"]
        for cmd in recalls:
            m = self.router.match_memory(cmd)
            self.assertIsNotNone(m, f"Failed for {cmd}")
            self.assertEqual(m["action"], "recall")

            t = self.router.choose_tool(cmd)
            self.assertEqual(t["tool"], "recall_memory")

    def test_match_memory_forget(self):
        m1 = self.router.match_memory("забудь: 12345")
        self.assertIsNotNone(m1)
        self.assertEqual(m1["action"], "forget")
        self.assertEqual(m1["target"], "12345")

        m2 = self.router.match_memory("удали из памяти старый токен")
        self.assertIsNotNone(m2)
        self.assertEqual(m2["action"], "forget")
        self.assertEqual(m2["target"], "старый токен")

        t = self.router.choose_tool("забудь токен 999")
        self.assertEqual(t["tool"], "forget_memory")
        self.assertEqual(t["arguments"]["target"], "токен 999")

    def test_match_memory_search(self):
        m = self.router.match_memory("найди в памяти: Шарик")
        self.assertIsNotNone(m)
        self.assertEqual(m["action"], "search")
        self.assertEqual(m["query"], "Шарик")

    def test_match_memory_clear(self):
        clears = ["очисти память", "очистить память", "забудь всё", "сбрось память"]
        for cmd in clears:
            m = self.router.match_memory(cmd)
            self.assertIsNotNone(m, f"Failed for {cmd}")
            self.assertEqual(m["action"], "clear")


class TestCommandRouterPlanning(unittest.TestCase):
    """4. Проверка распознавания и роутинга команд планирования."""

    def setUp(self):
        self.router = CommandRouter()

    def test_match_plan_create(self):
        p1 = self.router.match_plan("план: сделать рефакторинг роутера")
        self.assertIsNotNone(p1)
        self.assertEqual(p1["action"], "create")
        self.assertEqual(p1["request"], "сделать рефакторинг роутера")

        route = self.router.route("план: сделать рефакторинг роутера")
        self.assertEqual(route["type"], "plan")
        self.assertEqual(route["action"], "create")
        self.assertEqual(route["request"], "сделать рефакторинг роутера")

    def test_match_plan_actions(self):
        cases = [
            ("выполни план", "execute"),
            ("выполнить план", "execute"),
            ("запусти план", "execute"),
            ("покажи план", "get"),
            ("текущий план", "get"),
            ("очисти план", "clear"),
            ("удали план", "clear"),
            ("сбрось план", "clear"),
        ]
        for cmd, expected_action in cases:
            p = self.router.match_plan(cmd)
            self.assertIsNotNone(p, f"Failed for {cmd}")
            self.assertEqual(p["action"], expected_action)

            route = self.router.route(cmd)
            self.assertEqual(route["type"], "plan")
            self.assertEqual(route["action"], expected_action)


class TestCommandRouterAgentIntegration(unittest.TestCase):
    """5. Интеграционные тесты конвейера Agent.process() с CommandRouter."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_path = Path(self.temp_dir.name) / "test_mem.json"
        self.household_path = Path(self.temp_dir.name) / "test_household.json"

        self.mem = MemoryManager(storage_path=self.mem_path)
        self.ctx = ContextManager(memory_manager=self.mem)
        self.mock_ai = MagicMock()
        self.agent = Agent(
            memory_manager=self.mem,
            context_manager=self.ctx,
            ai_client=self.mock_ai
        )
        self.agent.router = CommandRouter()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_query(self):
        res = self.agent.process("")
        self.assertEqual(res["type"], "chat")
        self.assertEqual(res["answer"], "Пустой запрос.")

    def test_fastpath_memory_full_cycle(self):
        # 1. Запомнить
        res1 = self.agent.process("запомни: Рабочий порт 7777")
        self.assertEqual(res1["type"], "chat")
        self.assertIn("Запомнил", res1["answer"])
        self.assertEqual(len(self.mem.recall()), 1)

        # 2. Что ты помнишь
        res2 = self.agent.process("что ты помнишь")
        self.assertEqual(res2["type"], "chat")
        self.assertIn("7777", res2["answer"])

        # 3. Поиск в памяти
        res3 = self.agent.process("найди в памяти: 7777")
        self.assertEqual(res3["type"], "chat")
        self.assertIn("7777", res3["answer"])

        # 4. Забыть
        res4 = self.agent.process("забудь: 7777")
        self.assertEqual(res4["type"], "chat")
        self.assertIn("Удалил", res4["answer"])
        self.assertEqual(len(self.mem.recall()), 0)

        # 5. Очистить память
        self.mem.remember("Факт 1")
        res5 = self.agent.process("очисти память")
        self.assertEqual(res5["type"], "chat")
        self.assertIn("очищена", res5["answer"])
        self.assertEqual(len(self.mem.recall()), 0)

        # Ни один LLM-вызов не должен быть сделан!
        self.assertFalse(self.mock_ai.send_chat.called)
        self.assertFalse(self.mock_ai.ask.called)

    def test_fastpath_plan_cycle(self):
        # 1. План без задачи
        res_empty = self.agent.process("план:")
        self.assertEqual(res_empty["type"], "plan")
        self.assertFalse(res_empty["result"]["success"])

        # 2. План с задачей
        self.agent.create_plan = MagicMock(return_value={"success": True, "plan": {"title": "Test"}})
        res_plan = self.agent.process("план: Проверить рефакторинг")
        self.assertEqual(res_plan["type"], "plan")
        self.assertTrue(res_plan["result"]["success"])
        self.agent.create_plan.assert_called_once_with("Проверить рефакторинг")

        # 3. Показать план
        self.agent.planner.current_plan = {"title": "Test"}
        res_get = self.agent.process("покажи план")
        self.assertEqual(res_get["type"], "plan")
        self.assertTrue(res_get["result"]["success"])

        # 4. Очистить план
        res_clear = self.agent.process("очисти план")
        self.assertEqual(res_clear["type"], "tool")
        self.assertEqual(res_clear["tool"], "clear_plan")

    def test_fastpath_household_task(self):
        # Быстрое создание задачи через fast-path
        res = self.agent.process("создай задачу написать документацию R2")
        self.assertEqual(res["type"], "tool")
        self.assertEqual(res["tool"], "create_task")
        self.assertTrue(res["result"]["success"])

        # Быстрый список задач
        res_list = self.agent.process("покажи задачи")
        self.assertEqual(res_list["type"], "tool")
        self.assertEqual(res_list["tool"], "list_tasks")
        self.assertTrue(res_list["result"]["success"])

        # LLM не вызывался
        self.assertFalse(self.mock_ai.send_chat.called)

    def test_latency_is_ultra_low(self):
        """Проверка латентности: fast-path должен отрабатывать < 1 мс."""
        t0 = time.perf_counter()
        route = self.agent.router.route("создай задачу купить свежий хлеб")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(route["tool"], "create_task")
        self.assertLess(elapsed_ms, 1.0, f"Latency {elapsed_ms:.3f} ms exceeds 1.0 ms")


if __name__ == "__main__":
    unittest.main()
