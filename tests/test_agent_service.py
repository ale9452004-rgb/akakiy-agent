"""
Targeted tests for AgentService (multi-agent service facade layer).

Проверяет:
1. Household -> Router -> Executor -> AgentResult.
2. Research -> Router -> Executor -> AgentResult с mock worker.
3. no-match: обработка нераспознанного запроса.
4. disabled agent: обработка запроса к отключенному агенту.
5. Исключение агента: безопасный перехват без сбоя вызывающего кода.
6. Сохранение data / artifacts / created_files при сквозном выполнении.
7. Dependency Injection: явная передача router, executor, registry и работа дефолтной конфигурации.
8. Предварительный просмотр маршрутизации через route() и preview_route().
9. Структурированную обработку пустого и некорректного task.
10. Принцип Open-Closed (OCP): отсутствие жестких импортов доменных агентов в agents/service.py.
11. Расширяемость: подключение и исполнение стороннего агента без изменений сервиса.
12. Глобальные синглтон-методы get_agent_service() и reset_agent_service().
"""

import inspect
from pathlib import Path
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
from agents.service import AgentService, get_agent_service, reset_agent_service
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestAgentService(unittest.TestCase):
    """Тестирование фасадного сервиса AgentService."""

    def setUp(self):
        reset_agent_service()
        self.registry = AgentRegistry()
        self.household_agent = HouseholdAgent()
        self.research_agent = ResearchAgent()
        self.registry.register(self.household_agent)
        self.registry.register(self.research_agent)

        self.router = AgentRouter(registry=self.registry)
        self.executor = AgentExecutor(router=self.router)
        self.service = AgentService(
            router=self.router,
            executor=self.executor,
            registry=self.registry
        )

    def tearDown(self):
        reset_agent_service()

    def test_household_router_executor_pipeline(self):
        """1. Household -> Router -> Executor -> AgentResult."""
        result = self.service.execute("создай задачу Купить молоко")

        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertIn("route", result.data)
        self.assertEqual(result.data["route"]["agent"], "household")
        self.assertEqual(result.data["route"]["capability"], "tasks")
        self.assertIn("task", result.data)
        self.assertEqual(result.data["task"]["title"], "Купить молоко")

    def test_research_router_executor_pipeline_with_mock(self):
        """2. Research -> Router -> Executor -> AgentResult с mock worker."""
        mock_worker_result = AgentResult.ok(
            message="Исследование квантовых процессоров успешно завершено.",
            data={"topic": "квантовые процессоры", "metrics": {"qubits": 127}},
            artifacts=[Artifact.from_text("Отчет о квантовых процессорах", name="quantum_report.md")]
        )

        with patch.object(self.research_agent, "execute", return_value=mock_worker_result) as mock_exec:
            result = self.service.execute("исследуй квантовые процессоры")

            self.assertIsInstance(result, AgentResult)
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Исследование квантовых процессоров успешно завершено.")
            self.assertIn("route", result.data)
            self.assertEqual(result.data["route"]["agent"], "research")
            self.assertEqual(result.data["route"]["capability"], "research")
            self.assertEqual(result.data["metrics"]["qubits"], 127)
            self.assertEqual(len(result.artifacts), 1)
            self.assertEqual(result.artifacts[0].name, "quantum_report.md")
            mock_exec.assert_called_once()

    def test_no_match_query(self):
        """3. no-match: обработка нераспознанного запроса."""
        result = self.service.execute("какая сегодня погода в Риме?")

        self.assertIsInstance(result, AgentResult)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Маршрут не найден.")
        self.assertIn("route", result.data)
        self.assertFalse(result.data["route"]["success"])
        self.assertIn("не найден", result.message.lower())

    def test_disabled_agent_handling(self):
        """4. disabled agent: обработка запроса к отключенному агенту."""
        self.registry.disable("household")

        result = self.service.execute("создай задачу Купить чай")

        self.assertIsInstance(result, AgentResult)
        self.assertFalse(result.success)
        self.assertIn("отключен", result.error.lower())
        self.assertIn("route", result.data)
        self.assertTrue(result.data["route"]["is_disabled"])

    def test_agent_exception_safety(self):
        """5. Исключение агента: безопасный перехват без сбоя сервиса."""
        class CrashingAgent(BaseAgent):
            name = "crasher"
            description = "Agent that raises error"
            capabilities = ["crash"]

            def execute(self, task, context=None, **kwargs):
                raise ZeroDivisionError("Деление на ноль внутри агента!")

        crash_agent = CrashingAgent()
        self.registry.register(crash_agent)
        self.router.register_capability_rule("crash", [r"\b(?:краш|упади|crash)\b"])

        result = self.service.execute("сделай краш системы")

        self.assertIsInstance(result, AgentResult)
        self.assertFalse(result.success)
        self.assertIn("Деление на ноль", result.error)
        self.assertEqual(result.data["exception_type"], "ZeroDivisionError")

    def test_data_artifacts_and_files_preservation(self):
        """6. Сохранение data / artifacts / created_files при сквозном вызове."""
        class RichArtifactAgent(BaseAgent):
            name = "rich_producer"
            description = "Agent returning rich artifacts and metadata"
            capabilities = ["produce_rich"]

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="Богатый результат сгенерирован",
                    data={"score": 98.7, "version": "2.0"},
                    created_files=["/data/output.pdf"],
                    artifacts=[
                        Artifact.from_file("/data/output.pdf", type=ArtifactType.DOCUMENT),
                        Artifact.from_text("Текстовая сводка", name="summary.txt")
                    ]
                )

        rich_agent = RichArtifactAgent()
        self.registry.register(rich_agent)
        self.router.register_capability_rule("produce_rich", [r"\b(?:создай\s+богатый|produce_rich)\b"])

        result = self.service.execute("создай богатый отчет")

        self.assertTrue(result.success)
        self.assertEqual(result.data["score"], 98.7)
        self.assertEqual(result.data["version"], "2.0")
        self.assertIn("/data/output.pdf", result.created_files)
        self.assertEqual(len(result.artifacts), 2)
        self.assertEqual(result.artifacts[0].type, ArtifactType.DOCUMENT)
        self.assertEqual(result.artifacts[1].name, "summary.txt")
        self.assertEqual(result.artifacts[1].content, "Текстовая сводка")
        # Метаданные маршрута не перезаписали существующие поля data
        self.assertIn("route", result.data)

    def test_dependency_injection_and_defaults(self):
        """7. Dependency Injection: явная передача зависимостей и дефолтная инициализация."""
        # 1. Явная передача custom компонентов
        custom_reg = AgentRegistry()
        custom_router = AgentRouter(registry=custom_reg)
        custom_executor = AgentExecutor(router=custom_router)

        custom_service = AgentService(
            router=custom_router,
            executor=custom_executor,
            registry=custom_reg
        )

        self.assertIs(custom_service.registry, custom_reg)
        self.assertIs(custom_service.router, custom_router)
        self.assertIs(custom_service.executor, custom_executor)

        # 2. Инициализация без аргументов (использует проектные синглтоны)
        default_service = AgentService()
        self.assertIsNotNone(default_service.registry)
        self.assertIsNotNone(default_service.router)
        self.assertIsNotNone(default_service.executor)
        self.assertIsInstance(default_service.to_dict(), dict)

    def test_route_preview_methods(self):
        """8. Предварительный просмотр маршрутизации через route() и preview_route()."""
        # Маршрут к Household
        route_household = self.service.route("создай заметку Рецепт кофе")
        self.assertIsInstance(route_household, RouteResult)
        self.assertTrue(route_household.success)
        self.assertEqual(route_household.agent_name, "household")
        self.assertEqual(route_household.capability, "notes")

        # Маршрут к Research через preview_route
        route_research = self.service.preview_route("исследуй нейросетевые архитектуры")
        self.assertIsInstance(route_research, RouteResult)
        self.assertTrue(route_research.success)
        self.assertEqual(route_research.agent_name, "research")
        self.assertEqual(route_research.capability, "research")

        # Проверка, что просмотр маршрута не выполняет реальную задачу в хранилище
        res_preview = self.service.route("создай задачу Тест без исполнения")
        self.assertTrue(res_preview.success)
        # Убедимся, что задача фактически не создана в HouseholdManager
        hm = self.household_agent._get_manager()
        task_titles = [t.title for t in hm.list_tasks()]
        self.assertNotIn("Тест без исполнения", task_titles)

    def test_empty_and_invalid_task_handling(self):
        """9. Структурированная обработка пустого и некорректного task."""
        # execute с пустыми строками и None
        for bad_task in ["", "   ", None, 12345]:
            with self.subTest(task=bad_task):
                result = self.service.execute(bad_task)
                self.assertIsInstance(result, AgentResult)
                self.assertFalse(result.success)
                self.assertIn("не может быть пустым", result.error)

        # route / preview_route с пустыми строками и None
        route_empty = self.service.route("")
        self.assertFalse(route_empty.success)
        self.assertIn("пустой запрос", route_empty.reason.lower())

        preview_none = self.service.preview_route(None)
        self.assertFalse(preview_none.success)
        self.assertIn("пустой запрос", preview_none.reason.lower())

    def test_open_closed_principle_no_hardcodes(self):
        """10. OCP: в agents/service.py нет жестких импортов доменных агентов."""
        import agents.service as service_module
        source_code = inspect.getsource(service_module)

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
                f"Нарушение принципа OCP: токен '{token}' найден в agents/service.py!"
            )

    def test_custom_agent_extensibility(self):
        """11. Расширяемость: сторонний агент регистрируется и исполняется через сервис без модификации ядра."""
        class MathAgent(BaseAgent):
            name = "math_solver"
            description = "Agent for math calculations"
            capabilities = ["calculate"]

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="Расчет выполнен: 4",
                    data={"expression": "2 + 2", "answer": 4}
                )

        math_agent = MathAgent()
        self.registry.register(math_agent)
        self.router.register_capability_rule("calculate", [r"\b(?:посчитай|вычисли|calculate)\b"])

        # Проверяем preview
        route = self.service.preview_route("посчитай 2 + 2")
        self.assertTrue(route.success)
        self.assertEqual(route.agent_name, "math_solver")

        # Проверяем исполнение через сервис
        result = self.service.execute("посчитай 2 + 2")
        self.assertTrue(result.success)
        self.assertEqual(result.data["answer"], 4)
        self.assertEqual(result.data["route"]["agent"], "math_solver")

    def test_singleton_mechanics(self):
        """12. Проверка синглтона get_agent_service() и reset_agent_service()."""
        reset_agent_service()

        s1 = get_agent_service()
        s2 = get_agent_service()
        self.assertIs(s1, s2)
        self.assertIsInstance(s1, AgentService)

        reset_agent_service()
        s3 = get_agent_service()
        self.assertIsNot(s1, s3)
        self.assertIsInstance(s3, AgentService)


if __name__ == "__main__":
    unittest.main()
