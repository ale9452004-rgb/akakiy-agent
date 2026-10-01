"""
Targeted tests for AgentRouter (multi-agent routing layer).

Проверяет:
1. Маршрутизацию запросов про задачи к HouseholdAgent.
2. Маршрутизацию запросов про напоминания к HouseholdAgent.
3. Маршрутизацию запросов про заметки к HouseholdAgent.
4. Маршрутизацию запросов про списки к HouseholdAgent.
5. Маршрутизацию общих бытовых запросов к HouseholdAgent.
6. Отклонение явно нерелевантных запросов (погода, код, системные файлы).
7. Защиту от ложного срабатывания на 'список файлов проекта'.
8. Обработку пустого ввода (None, "", пробелы).
9. Поведение при отключённом HouseholdAgent (is_disabled == True).
10. Изоляцию и работу исключительно через AgentRegistry (без жестких связок).
11. Подключение нового стороннего domain agent с новой capability БЕЗ изменения кода Router.
12. Полное отсутствие hardcoded зависимости Router -> HouseholdAgent.
"""

import inspect
from pathlib import Path
import re
import sys
import unittest
from typing import Any, Dict, Optional

# Обеспечиваем импорт из корня проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.household import HouseholdAgent
from agents.research import ResearchAgent
from agents.registry import AgentRegistry
from agents.router import AgentRouter, RouteResult
from tools.agents.result import AgentResult


class TestAgentRouterWithHousehold(unittest.TestCase):
    """Тестирование маршрутизации к HouseholdAgent через AgentRegistry."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.household_agent = HouseholdAgent()
        self.registry.register(self.household_agent)
        self.router = AgentRouter(registry=self.registry)

    def test_task_queries(self):
        queries = [
            "создай задачу Купить хлеб и молоко",
            "добавь задачу Позвонить родителям",
            "покажи задачи",
            "активные задачи",
            "выполни задачу 1",
            "удали задачу 2",
            "список дел на сегодня",
            "задача: проверить почту"
        ]
        for q in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertTrue(res.success, f"Запрос '{q}' должен был успешно смаршрутизироваться.")
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, "tasks")
                self.assertIs(res.agent, self.household_agent)
                self.assertTrue(res.confidence > 0.0)

    def test_reminder_queries(self):
        queries = [
            "напомни в 16:00 выпить таблетку",
            "напомни мне завтра купить подарок",
            "создай напоминание на вечер",
            "покажи напоминания",
            "список напоминаний",
            "поставь напоминание на 19:30"
        ]
        for q in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertTrue(res.success, f"Запрос '{q}' должен был успешно смаршрутизироваться.")
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, "reminders")
                self.assertIs(res.agent, self.household_agent)

    def test_note_queries(self):
        queries = [
            "создай заметку Рецепт шарлотки: яблоки и корица",
            "запиши в заметки адрес сервисного центра",
            "покажи заметки",
            "список заметок",
            "найди в заметках рецепт",
            "новая заметка идеи для отпуска"
        ]
        for q in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertTrue(res.success, f"Запрос '{q}' должен был успешно смаршрутизироваться.")
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, "notes")
                self.assertIs(res.agent, self.household_agent)

    def test_list_queries(self):
        queries = [
            "создай список покупки",
            "список покупок",
            "добавь в список покупок творог",
            "покажи список продуктов",
            "списки",
            "покажи списки",
            "очисти список покупки"
        ]
        for q in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertTrue(res.success, f"Запрос '{q}' должен был успешно смаршрутизироваться.")
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, "lists")
                self.assertIs(res.agent, self.household_agent)

    def test_general_household_queries(self):
        queries = [
            "дела по дому",
            "бытовые дела",
            "уборка в доме"
        ]
        for q in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertTrue(res.success, f"Запрос '{q}' должен был смапиться на household.")
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, "household")

    def test_irrelevant_queries_no_match(self):
        irrelevant = [
            "какая сейчас погода в Токио?",
            "напиши функцию сортировки слиянием на C++",
            "найди файл main.py",
            "что такое квантовая механика?",
            "расскажи анекдот",
            "сделай коммит в git"
        ]
        for q in irrelevant:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertFalse(res.success, f"Запрос '{q}' НЕ должен маршрутизироваться в household.")
                self.assertIsNone(res.agent)
                self.assertIn("не найден", res.reason.lower())

    def test_code_project_exclusion_on_lists(self):
        # Слово "список" в контексте проекта или кода не должно матчиться на Household списки
        code_list_queries = [
            "список файлов проекта",
            "покажи список файлов",
            "список коммитов в репозитории",
            "список функций в модуле"
        ]
        for q in code_list_queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertFalse(res.success, f"Кодовый запрос '{q}' не должен вести в household списки.")
                self.assertIsNone(res.agent)

    def test_empty_query(self):
        for empty_val in ["", "   ", "\n\t", None]:
            res = self.router.route(empty_val)
            self.assertFalse(res.success)
            self.assertIsNone(res.agent)
            self.assertIn("пустой", res.reason.lower())

    def test_disabled_household_agent(self):
        self.household_agent.enabled = False

        res = self.router.route("создай задачу Купить сыр")
        self.assertFalse(res.success)
        self.assertTrue(res.is_disabled)
        self.assertEqual(res.agent_name, "household")
        self.assertIn("отключен", res.reason.lower())

    def test_result_contract_to_dict_and_repr(self):
        res = self.router.route("создай задачу Тест контракта")
        d = res.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["agent"], "household")
        self.assertEqual(d["capability"], "tasks")
        self.assertIn("agent='household'", repr(res))


class TestAgentRouterExtensibilityAndIsolation(unittest.TestCase):
    """Тестирование независимости Router от конкретных классов агентов."""

    def test_no_hardcoded_import_of_household_agent(self):
        # Проверяем, что в agents/router.py нет жесткого импорта HouseholdAgent
        import agents.router as router_module
        source_code = inspect.getsource(router_module)

        self.assertNotIn("HouseholdAgent", source_code,
                         "В agents/router.py НЕ должно быть hardcoded упоминания или импорта HouseholdAgent!")
        self.assertNotIn("from agents.household", source_code)
        self.assertNotIn("import HouseholdAgent", source_code)

        # Проверяем, что в agents/router.py нет жесткого импорта ResearchAgent
        self.assertNotIn("ResearchAgent", source_code,
                         "В agents/router.py НЕ должно быть hardcoded упоминания или импорта ResearchAgent!")
        self.assertNotIn("from agents.research", source_code)
        self.assertNotIn("import ResearchAgent", source_code)

    def test_router_works_with_custom_domain_agent_in_registry(self):
        # Проверяем, что если в реестре зарегистрирован сторонний CustomTaskAgent (НЕ HouseholdAgent),
        # Router корректно находит его через capability "tasks"
        class CustomTaskAgent(BaseAgent):
            name = "custom_tasker"
            capabilities = ["tasks"]
            tools = ["custom_add_task"]

            def execute(self, task: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> AgentResult:
                return AgentResult.ok("Кастомная задача выполнена")

        custom_registry = AgentRegistry()
        custom_agent = CustomTaskAgent()
        custom_registry.register(custom_agent)

        router = AgentRouter(registry=custom_registry)
        res = router.route("создай задачу Проверить кастомного агента")

        self.assertTrue(res.success)
        self.assertEqual(res.agent_name, "custom_tasker")
        self.assertEqual(res.capability, "tasks")
        self.assertIs(res.agent, custom_agent)

    def test_add_new_capability_without_router_code_change(self):
        # Проверяем, что добавление нового domain agent с новой capability
        # (например, "weather" или "analytics") НЕ требует изменения кода AgentRouter.
        class WeatherAgent(BaseAgent):
            name = "weather"
            description = "Погодный агент"
            capabilities = ["weather"]
            tools = ["get_weather"]

            def can_handle(self, task: str) -> float:
                return 1.0 if "погод" in task.lower() or "прогноз" in task.lower() else 0.0

            def execute(self, task: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> AgentResult:
                return AgentResult.ok(message="Погода ясная")

        reg = AgentRegistry()
        weather_agent = WeatherAgent()
        reg.register(weather_agent)

        router = AgentRouter(registry=reg)

        # 1. Проверяем маршрутизацию через can_handle агента
        res = router.route("какая сегодня погода в Москве?")
        self.assertTrue(res.success)
        self.assertEqual(res.agent_name, "weather")
        self.assertIs(res.agent, weather_agent)

        # 2. Проверяем регистрацию нового правила capability на лету
        router.register_capability_rule("weather", [r"\bдожд[ьяеию]\b", r"\bснегопад\b"])
        res2 = router.route("будет ли дождь сегодня?")
        self.assertTrue(res2.success)
        self.assertEqual(res2.agent_name, "weather")
        self.assertEqual(res2.capability, "weather")

    def test_empty_registry_produces_no_match(self):
        empty_reg = AgentRegistry()
        router = AgentRouter(registry=empty_reg)

        res = router.route("создай задачу Купить хлеб")
        self.assertFalse(res.success)
        self.assertIsNone(res.agent)
        self.assertIn("не найден", res.reason.lower())


class TestAgentRouterMultiAgents(unittest.TestCase):
    """Тестирование маршрутизации при наличии нескольких активных доменных агентов (household + research)."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.household_agent = HouseholdAgent()
        self.research_agent = ResearchAgent()
        self.registry.register(self.household_agent)
        self.registry.register(self.research_agent)
        self.router = AgentRouter(registry=self.registry)

    def test_research_queries(self):
        queries = [
            ("исследуй архитектуру проекта Акакий", "research"),
            ("проведи исследование на тему нейросетей", "research"),
            ("найди информацию про микросервисы", "research"),
            ("исследование: паттерны проектирования", "research"),
            ("аналитический отчет по производительности системы", "research"),
        ]
        for q, expected_cap in queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertIsInstance(res, RouteResult)
                self.assertTrue(res.success, f"Запрос '{q}' должен был успешно смаршрутизироваться в research.")
                self.assertEqual(res.agent_name, "research")
                self.assertEqual(res.capability, expected_cap)
                self.assertIs(res.agent, self.research_agent)

    def test_household_queries_still_route_to_household(self):
        household_queries = [
            ("создай задачу Купить молоко", "tasks"),
            ("напомни в 17:00 позвонить в банк", "reminders"),
            ("создай заметку Рецепт блинов", "notes"),
            ("список покупок", "lists"),
            ("уборка в доме", "household")
        ]
        for q, expected_cap in household_queries:
            with self.subTest(query=q):
                res = self.router.route(q)
                self.assertTrue(res.success)
                self.assertEqual(res.agent_name, "household")
                self.assertEqual(res.capability, expected_cap)
                self.assertIs(res.agent, self.household_agent)

    def test_conflicting_queries(self):
        # 1. Задача, содержащая исследовательские слова, но являющаяся созданием задачи -> HouseholdAgent
        res1 = self.router.route("создай задачу исследовать производительность")
        self.assertTrue(res1.success)
        self.assertEqual(res1.agent_name, "household")
        self.assertEqual(res1.capability, "tasks")

        # 2. Исследовательский запрос со словом 'список' -> ResearchAgent (не перехватывается списками)
        res2 = self.router.route("исследуй список задач проекта")
        self.assertTrue(res2.success)
        self.assertEqual(res2.agent_name, "research")
        self.assertEqual(res2.capability, "research")

        # 3. Поиск в заметках темы исследования -> HouseholdAgent (notes)
        res3 = self.router.route("найди в заметках исследование рынка")
        self.assertTrue(res3.success)
        self.assertEqual(res3.agent_name, "household")
        self.assertEqual(res3.capability, "notes")

        # 4. Поиск информации по заметкам (исследовательский запрос) -> ResearchAgent
        res4 = self.router.route("найди информацию по архитектуре заметок")
        self.assertTrue(res4.success)
        self.assertEqual(res4.agent_name, "research")
        self.assertEqual(res4.capability, "research")

    def test_disabled_research_agent(self):
        self.registry.disable("research")

        res = self.router.route("исследуй квантовые компьютеры")
        self.assertFalse(res.success)
        self.assertTrue(res.is_disabled)
        self.assertEqual(res.agent_name, "research")
        self.assertIn("отключен", res.reason.lower())


if __name__ == "__main__":
    unittest.main()

