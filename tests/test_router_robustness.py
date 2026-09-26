"""
Тесты укреплённой маршрутизации (Agent Router: robust routing - Task 4).

Проверяет:
1. Нормализацию обращений («Акакий, ...», «Пожалуйста, ...», «Плиз, ...») для всех типов команд:
   - CLI/файлы проекта;
   - Бытовой слой (задачи, заметки, напоминания, списки);
   - Память (remember, recall);
   - Планирование (create, execute, get, clear).
2. Поддержку косвенного местоимения «мне» в бытовых командах и планах.
3. Исключение ложных срабатываний ImageAgent на коде, файлах, скриптах, папках, документах и общих запросах.
4. Явную маршрутизацию специализированных субагентов (Sub-Agent Fast-Path).
5. Интеграцию с Agent.process() для явного вызова субагентов.
6. Сохранение естественного диалога (неперехват приветствий и общих вопросов).
7. Латентность маршрутизации (< 1 мс).
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.router import CommandRouter, strip_call_prefixes
from tools.agent import Agent
from tools.agents.base import SubAgent
from tools.agents.result import AgentResult
from tools.agents.context import AgentContext
from tools.agents.registry import get_agent_registry


class TestRouterPrefixNormalization(unittest.TestCase):
    """1. Проверка нормализации обращений и слов вежливости."""

    def setUp(self):
        self.router = CommandRouter()

    def test_strip_call_prefixes_helper(self):
        self.assertEqual(strip_call_prefixes("Акакий, покажи задачи"), "покажи задачи")
        self.assertEqual(strip_call_prefixes("Акакий: покажи задачи"), "покажи задачи")
        self.assertEqual(strip_call_prefixes("Пожалуйста, покажи задачи"), "покажи задачи")
        self.assertEqual(strip_call_prefixes("Акакий, пожалуйста, покажи задачи"), "покажи задачи")
        self.assertEqual(strip_call_prefixes("плиз покажи заметки"), "покажи заметки")
        # Одиночные слова не должны превращаться в пустую строку
        self.assertEqual(strip_call_prefixes("Акакий"), "Акакий")
        self.assertEqual(strip_call_prefixes("Привет, Акакий"), "Привет, Акакий")

    def test_prefixes_with_tasks(self):
        cases = [
            "Акакий, покажи задачи",
            "Пожалуйста, покажи задачи",
            "Акакий, пожалуйста, покажи задачи",
            "плиз, покажи задачи",
        ]
        for query in cases:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertEqual(route["type"], "tool")
                self.assertEqual(route["tool"], "list_tasks")

    def test_prefixes_with_household_and_files(self):
        # Файлы
        r_file = self.router.route("Акакий, найди файл main.py")
        self.assertEqual(r_file["type"], "tool")
        self.assertEqual(r_file["tool"], "find_file")
        self.assertEqual(r_file["arguments"]["filename"], "main.py")

        # Заметки
        r_notes = self.router.route("Пожалуйста, покажи заметки")
        self.assertEqual(r_notes["type"], "tool")
        self.assertEqual(r_notes["tool"], "list_notes")

        # Напоминания
        r_rem = self.router.route("Акакий, покажи напоминания")
        self.assertEqual(r_rem["type"], "tool")
        self.assertEqual(r_rem["tool"], "list_reminders")

        # Списки
        r_lists = self.router.route("Акакий, покажи списки")
        self.assertEqual(r_lists["type"], "tool")
        self.assertEqual(r_lists["tool"], "show_list")

    def test_prefixes_with_memory_and_plans(self):
        # Память: remember
        r_mem = self.router.route("Акакий, запомни телефон 12345")
        self.assertEqual(r_mem["type"], "memory")
        self.assertEqual(r_mem["action"], "remember")
        self.assertEqual(r_mem["text"], "телефон 12345")

        # Память: recall
        r_rec = self.router.route("Пожалуйста, что ты помнишь")
        self.assertEqual(r_rec["type"], "memory")
        self.assertEqual(r_rec["action"], "recall")

        # План: create
        r_plan = self.router.route("Акакий, создай план: запустить сервис")
        self.assertEqual(r_plan["type"], "plan")
        self.assertEqual(r_plan["action"], "create")
        self.assertEqual(r_plan["request"], "запустить сервис")

        # План: execute
        r_exec = self.router.route("Пожалуйста, выполни план")
        self.assertEqual(r_exec["type"], "plan")
        self.assertEqual(r_exec["action"], "execute")


class TestRouterIndirectPronouns(unittest.TestCase):
    """2. Проверка поддержки местоимения «мне» в бытовых командах и планах."""

    def setUp(self):
        self.router = CommandRouter()

    def test_household_with_mne(self):
        # Задача
        r_task = self.router.route("создай мне задачу купить свежий хлеб")
        self.assertEqual(r_task["type"], "tool")
        self.assertEqual(r_task["tool"], "create_task")
        self.assertEqual(r_task["arguments"]["title"], "купить свежий хлеб")

        # Заметка с двоеточием
        r_note1 = self.router.route("создай мне заметку Идея: новый модуль")
        self.assertEqual(r_note1["type"], "tool")
        self.assertEqual(r_note1["tool"], "create_note")
        self.assertEqual(r_note1["arguments"]["title"], "Идея")
        self.assertEqual(r_note1["arguments"]["content"], "новый модуль")

        # Заметка простая
        r_note2 = self.router.route("создай мне заметку купить батарейки")
        self.assertEqual(r_note2["type"], "tool")
        self.assertEqual(r_note2["tool"], "create_note")
        self.assertEqual(r_note2["arguments"]["title"], "купить батарейки")

        # Напоминание
        r_rem = self.router.route("напомни мне позвонить завтра в 10:00")
        self.assertEqual(r_rem["type"], "tool")
        self.assertEqual(r_rem["tool"], "create_reminder")
        self.assertEqual(r_rem["arguments"]["text"], "позвонить")
        self.assertEqual(r_rem["arguments"]["remind_at"], "завтра в 10:00")

        # Список
        r_list = self.router.route("создай мне список Покупки")
        self.assertEqual(r_list["type"], "tool")
        self.assertEqual(r_list["tool"], "create_list")
        self.assertEqual(r_list["arguments"]["name"], "Покупки")

        # План
        r_plan = self.router.route("создай мне план: разработать бота")
        self.assertEqual(r_plan["type"], "plan")
        self.assertEqual(r_plan["action"], "create")
        self.assertEqual(r_plan["request"], "разработать бота")


class TestRouterFalsePositivePrevention(unittest.TestCase):
    """3. Проверка исключения ложных срабатываний ImageAgent."""

    def setUp(self):
        self.router = CommandRouter()

    def test_coding_and_file_queries_not_routed_to_image(self):
        non_image_queries = [
            "создай файл с картинкой",
            "создай файл картинка.png",
            "создай скрипт для генерации картинок",
            "создай код для работы с изображениями",
            "создай папку для фото",
            "создай директорию для изображений",
            "создай класс для картинок",
            "создай функцию загрузки изображений",
            "создай модуль обработки фото",
            "создай тест для генерации картинок",
            "создай коммит с картинками",
            "создай документ с рисунками",
            "создай таблицу с изображениями",
            "создай проект галереи картинок",
            "создай генератор картинок",
            "сделай кнопку для картинок",
            "сгенерируй html с изображениями",
        ]
        for query in non_image_queries:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertNotEqual(
                    route.get("type"),
                    "image",
                    f"Query '{query}' was falsely routed to image!"
                )

    def test_household_with_draw_verbs_not_routed_to_image(self):
        # Задачи и планы со словами рисования/картинок
        r_task = self.router.route("создай мне задачу нарисовать логотип")
        self.assertEqual(r_task["type"], "tool")
        self.assertEqual(r_task["tool"], "create_task")
        self.assertEqual(r_task["arguments"]["title"], "нарисовать логотип")

        r_plan = self.router.route("создай план: нарисовать дизайн сайта")
        self.assertEqual(r_plan["type"], "plan")
        self.assertEqual(r_plan["action"], "create")

    def test_normal_dialogue_preserved(self):
        dialogue_cases = [
            "Акакий, привет!",
            "Привет, Акакий",
            "Как твои дела?",
            "Что нового в мире?",
            "Расскажи о себе",
        ]
        for query in dialogue_cases:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertIsNone(route.get("type"))
                self.assertIsNone(route.get("tool"))


class TestSubAgentFastPath(unittest.TestCase):
    """4. Проверка явного вызова SubAgent через router и Agent.process()."""

    def setUp(self):
        self.router = CommandRouter()

    def test_match_subagent(self):
        cases = [
            ("субагент echo: тестовое сообщение", "echo", "тестовое сообщение"),
            ("запусти субагента echo: пинг", "echo", "пинг"),
            ("вызови агента my_subagent сделать расчет", "my_subagent", "сделать расчет"),
            ("делегируй субагенту code_review проверить diff", "code_review", "проверить diff"),
        ]
        for query, exp_agent, exp_task in cases:
            with self.subTest(query=query):
                res = self.router.match_subagent(query)
                self.assertIsNotNone(res, f"match_subagent returned None for '{query}'")
                self.assertEqual(res["agent"], exp_agent)
                self.assertEqual(res["task"], exp_task)

                route = self.router.route(query)
                self.assertEqual(route["type"], "subagent")
                self.assertEqual(route["agent"], exp_agent)
                self.assertEqual(route["task"], exp_task)

    def test_explicit_image_subagent(self):
        query = "субагент image: нарисуй средневековый замок"
        route = self.router.route(query)
        self.assertEqual(route["type"], "image")
        self.assertEqual(route["prompt"], "средневековый замок")

        query2 = "субагент image: кот в очках"
        route2 = self.router.route(query2)
        self.assertEqual(route2["type"], "image")
        self.assertEqual(route2["prompt"], "кот в очках")

    def test_agent_process_subagent_dispatch(self):
        registry = get_agent_registry()

        class DummyEchoAgent(SubAgent):
            name = "test_echo"
            description = "Test Echo Agent"

            def run(self, context: AgentContext) -> AgentResult:
                return AgentResult.ok(
                    message=f"Echo: {context.task}",
                    data={"task": context.task}
                )

        dummy = DummyEchoAgent()
        registry.register(dummy)
        try:
            agent = Agent()
            res = agent.process("субагент test_echo: привет из теста")
            self.assertEqual(res["type"], "subagent")
            self.assertEqual(res["agent"], "test_echo")
            self.assertTrue(res["success"])
            self.assertEqual(res["answer"], "Echo: привет из теста")
        finally:
            registry.unregister("test_echo")

    def test_routing_latency(self):
        """Проверка латентности: маршрутизация должна выполняться < 1 мс."""
        t0 = time.perf_counter()
        route = self.router.route("Акакий, пожалуйста, создай мне задачу протестировать роутер")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(route.get("type"), "tool")
        self.assertLess(elapsed_ms, 1.0, f"Latency {elapsed_ms:.3f} ms exceeds 1.0 ms")


if __name__ == "__main__":
    unittest.main()
