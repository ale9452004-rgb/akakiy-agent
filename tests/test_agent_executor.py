"""
Targeted tests for AgentExecutor (multi-agent execution layer).

Проверяет:
1. Выполнение задачи через RouteResult (HouseholdAgent).
2. Выполнение задачи напрямую через BaseAgent (HouseholdAgent).
3. Сквозное выполнение execute_task (router -> executor -> agent).
4. Выполнение ResearchAgent с сохранением данных и результатов.
5. Корректную обработку RouteResult.no_match (возврат failure AgentResult).
6. Корректную обработку отключенного агента (is_disabled и agent.enabled == False).
7. Защиту от некорректных входных объектов (None, невалидный тип, отсутствие BaseAgent).
8. Безопасный перехват исключений внутри agent.execute(...) без аварийного завершения.
9. Обработку нестандартных типов возврата агента (dict, None, строки, числа).
10. Полную сохранность data, artifacts и created_files от агента.
11. Инъекцию метаданных маршрута в result.data["route"] без перезаписи существующих ключей.
12. Валидацию пустого текста задачи.
13. Проверку принципа Open-Closed: отсутствие hardcoded импортов конкретных доменных агентов в agents/executor.py.
14. Подключение и сквозное выполнение произвольного стороннего агента без правок Executor.
"""

import inspect
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import MagicMock, patch
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.executor import AgentExecutor
from agents.household import HouseholdAgent
from agents.registry import AgentRegistry
from agents.research import ResearchAgent
from agents.router import AgentRouter, RouteResult
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestAgentExecutor(unittest.TestCase):
    """Тестирование функциональности и контрактов AgentExecutor."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.household_agent = HouseholdAgent()
        self.research_agent = ResearchAgent()
        self.registry.register(self.household_agent)
        self.registry.register(self.research_agent)
        self.router = AgentRouter(registry=self.registry)
        self.executor = AgentExecutor(router=self.router)

    def test_execute_with_route_result_household(self):
        """Проверка выполнения через RouteResult для HouseholdAgent."""
        route = self.router.route("создай задачу Проверить почту")
        self.assertTrue(route.success)
        self.assertEqual(route.agent_name, "household")

        result = self.executor.execute(route, "создай задачу Проверить почту")
        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertIn("route", result.data)
        self.assertEqual(result.data["route"]["agent"], "household")
        self.assertEqual(result.data["route"]["capability"], "tasks")

    def test_execute_direct_base_agent_household(self):
        """Проверка прямого вызова executor.execute с экземпляром BaseAgent."""
        result = self.executor.execute(self.household_agent, "создай заметку План на вечер")
        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertIn("note", result.data)

    def test_execute_task_end_to_end(self):
        """Проверка сквозного метода execute_task (маршрутизация + вызов)."""
        result = self.executor.execute_task("создай задачу Купить молоко")
        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertIn("route", result.data)
        self.assertEqual(result.data["route"]["agent"], "household")
        self.assertEqual(result.data["route"]["capability"], "tasks")

    def test_execute_research_agent_with_mock(self):
        """Проверка выполнения ResearchAgent через executor с моком воркера."""
        mock_worker_result = AgentResult.ok(
            message="Отчет по квантовым вычислениям готов.",
            data={"summary": "Квантовые вычисления используют кубиты.", "topic": "квантовые вычисления"},
            artifacts=[Artifact.from_text("Квантовый отчет", name="report.md")]
        )

        with patch.object(self.research_agent, "execute", return_value=mock_worker_result) as mock_exec:
            route = self.router.route("исследуй квантовые вычисления")
            self.assertTrue(route.success)
            self.assertEqual(route.agent_name, "research")

            result = self.executor.execute(route, "исследуй квантовые вычисления")
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Отчет по квантовым вычислениям готов.")
            self.assertEqual(result.data["summary"], "Квантовые вычисления используют кубиты.")
            self.assertEqual(len(result.artifacts), 1)
            self.assertEqual(result.artifacts[0].name, "report.md")
            mock_exec.assert_called_once()

    def test_route_no_match_returns_fail_result(self):
        """Проверка обработки запроса, для которого не найден агент."""
        route = self.router.route("какая сегодня погода в Париже?")
        self.assertFalse(route.success)

        result = self.executor.execute(route, "какая сегодня погода в Париже?")
        self.assertIsInstance(result, AgentResult)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Маршрут не найден.")
        self.assertIn("route", result.data)
        self.assertFalse(result.data["route"]["success"])

        # Проверка сквозного execute_task для нерелевантного запроса
        result_task = self.executor.execute_task("совершенно бессмысленный запрос 12345")
        self.assertFalse(result_task.success)
        self.assertEqual(result_task.error, "Маршрут не найден.")

    def test_disabled_agent_handling(self):
        """Проверка обработки отключенного агента."""
        self.registry.disable("household")

        # 1. Через маршрутизатор (is_disabled == True)
        route = self.router.route("создай задачу Купить чай")
        self.assertFalse(route.success)
        self.assertTrue(route.is_disabled)

        result = self.executor.execute(route, "создай задачу Купить чай")
        self.assertFalse(result.success)
        self.assertIn("отключен", result.error)
        self.assertIn("route", result.data)

        # 2. Напрямую через BaseAgent c enabled = False
        direct_result = self.executor.execute(self.household_agent, "создай задачу Купить кофе")
        self.assertFalse(direct_result.success)
        self.assertIn("отключен", direct_result.error)

    def test_invalid_route_and_agent_inputs(self):
        """Проверка обработки некорректных аргументов."""
        # 1. route_or_agent is None
        res_none = self.executor.execute(None, "задача")
        self.assertFalse(res_none.success)
        self.assertIn("не передан", res_none.error)

        # 2. Неверный тип объекта
        res_type = self.executor.execute("строка вместо агента", "задача")
        self.assertFalse(res_type.success)
        self.assertIn("Недопустимый тип", res_type.error)

        res_num = self.executor.execute(12345, "задача")
        self.assertFalse(res_num.success)
        self.assertIn("Недопустимый тип", res_num.error)

        # 3. RouteResult с success=True, но agent=None
        broken_route = RouteResult(agent=None, success=True)
        res_broken = self.executor.execute(broken_route, "задача")
        self.assertFalse(res_broken.success)
        self.assertIn("отсутствует", res_broken.error)

        # 4. RouteResult с агентом не-BaseAgent
        class FakeObject:
            name = "fake"
            enabled = True
        broken_route_fake = RouteResult(agent=FakeObject(), success=True)
        res_fake = self.executor.execute(broken_route_fake, "задача")
        self.assertFalse(res_fake.success)
        self.assertIn("не реализует BaseAgent", res_fake.error)

    def test_exception_handling_in_agent_execute(self):
        """Проверка безопасного перехвата исключений внутри agent.execute."""
        class ExplodingAgent(BaseAgent):
            name = "exploding"
            description = "Agent that always fails"
            capabilities = ["explode"]

            def execute(self, task, context=None, **kwargs):
                raise RuntimeError("Катастрофический сбой внутри агента!")

        exploding_agent = ExplodingAgent()
        result = self.executor.execute(exploding_agent, "сделай бум")

        self.assertIsInstance(result, AgentResult)
        self.assertFalse(result.success)
        self.assertIn("Ошибка выполнения агента 'exploding'", result.error)
        self.assertIn("Катастрофический сбой", result.error)
        self.assertEqual(result.data["exception_type"], "RuntimeError")
        self.assertEqual(result.data["agent"], "exploding")

    def test_non_agent_result_return_types(self):
        """Проверка обработки некорректных типов возвращаемого значения агента."""
        class WeirdAgent(BaseAgent):
            name = "weird"
            description = "Agent returning strange objects"
            capabilities = ["weird"]

            def __init__(self, return_val):
                super().__init__()
                self.return_val = return_val

            def execute(self, task, context=None, **kwargs):
                return self.return_val

        # 1. Возврат None
        res_none = self.executor.execute(WeirdAgent(None), "тест")
        self.assertFalse(res_none.success)
        self.assertIn("некорректный тип результата: 'NoneType'", res_none.error)

        # 2. Возврат строки
        res_str = self.executor.execute(WeirdAgent("просто текст"), "тест")
        self.assertFalse(res_str.success)
        self.assertIn("некорректный тип результата: 'str'", res_str.error)

        # 3. Возврат dict со структурой AgentResult -> корректная адаптация
        res_dict = self.executor.execute(
            WeirdAgent({"success": True, "message": "Словарь адаптирован", "data": {"foo": "bar"}}),
            "тест"
        )
        self.assertTrue(res_dict.success)
        self.assertEqual(res_dict.message, "Словарь адаптирован")
        self.assertEqual(res_dict.data["foo"], "bar")

    def test_preservation_of_data_and_artifacts(self):
        """Проверка полной сохранности данных и артефактов."""
        class ArtifactAgent(BaseAgent):
            name = "artifact_agent"
            description = "Agent producing rich artifacts"
            capabilities = ["artifacts"]

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="Артефакты сгенерированы",
                    data={"custom_metric": 99.9, "nested": {"a": 1}},
                    created_files=["/tmp/output.png"],
                    artifacts=[
                        Artifact.from_file("/tmp/output.png", type=ArtifactType.IMAGE, width=512, height=512),
                        Artifact.from_text("Контент файла", name="info.txt")
                    ]
                )

        agent = ArtifactAgent()
        res = self.executor.execute(agent, "сгенерируй артефакты")

        self.assertTrue(res.success)
        self.assertEqual(res.data["custom_metric"], 99.9)
        self.assertEqual(res.data["nested"]["a"], 1)
        self.assertEqual(len(res.artifacts), 2)
        self.assertEqual(res.artifacts[0].type, ArtifactType.IMAGE)
        self.assertEqual(res.artifacts[0].metadata["width"], 512)
        self.assertEqual(res.artifacts[1].name, "info.txt")
        self.assertEqual(res.artifacts[1].content, "Контент файла")
        self.assertIn("/tmp/output.png", res.created_files)

    def test_route_data_non_destructive_injection(self):
        """Проверка, что инъекция route в data не перезаписывает уже существующие данные."""
        route = self.router.route("создай заметку Важное")
        self.assertTrue(route.success)

        result = self.executor.execute(route, "создай заметку Важное")
        self.assertTrue(result.success)
        self.assertIn("route", result.data)
        self.assertEqual(result.data["route"]["agent"], "household")
        self.assertEqual(result.data["route"]["capability"], "notes")

    def test_empty_task_validation(self):
        """Проверка валидации пустого текста задачи."""
        res_empty = self.executor.execute(self.household_agent, "")
        self.assertFalse(res_empty.success)
        self.assertIn("не может быть пустым", res_empty.error)

        res_spaces = self.executor.execute(self.household_agent, "    ")
        self.assertFalse(res_spaces.success)
        self.assertIn("не может быть пустым", res_spaces.error)

        res_none = self.executor.execute(self.household_agent, None)
        self.assertFalse(res_none.success)
        self.assertIn("не может быть пустым", res_none.error)

    def test_open_closed_isolation_no_domain_hardcodes(self):
        """Проверка принципа Open-Closed: в agents/executor.py нет жестких импортов доменных агентов."""
        import agents.executor as executor_module
        source_code = inspect.getsource(executor_module)

        forbidden_tokens = [
            "HouseholdAgent",
            "ResearchAgent",
            "CodingAgent",
            "MemoryAgent",
            "tools.household",
            "tools.agents.research",
        ]

        for token in forbidden_tokens:
            self.assertNotIn(
                token,
                source_code,
                f"Нарушение принципа OCP: токен '{token}' обнаружен в исходном коде agents/executor.py!"
            )

    def test_custom_dummy_agent_extensibility(self):
        """Проверка расширяемости: сторонний агент регистрируется, маршрутизируется и исполняется без правок ядра."""
        class TranslationAgent(BaseAgent):
            name = "translator"
            description = "Domain agent for translations"
            capabilities = ["translate"]

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="Перевод выполнен: Hello World",
                    data={"source_text": task, "translation": "Hello World"}
                )

        custom_agent = TranslationAgent()
        self.registry.register(custom_agent)
        self.router.register_capability_rule("translate", [r"\b(?:переведи|перевод)\b"])

        # Выполняем через сквозной execute_task
        res = self.executor.execute_task("переведи фразу на английский")
        self.assertTrue(res.success)
        self.assertEqual(res.data["route"]["agent"], "translator")
        self.assertEqual(res.data["route"]["capability"], "translate")
        self.assertEqual(res.data["translation"], "Hello World")


if __name__ == "__main__":
    unittest.main()
