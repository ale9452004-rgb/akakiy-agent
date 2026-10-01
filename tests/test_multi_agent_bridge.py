"""
Targeted tests for MultiAgentBridge (transitional bridge layer).

Scenarios covered:
1. Household successfully handled by Bridge ("создай задачу Купить молоко" -> dict with success=True, type="tasks").
2. Research successfully handled by Bridge with mock worker ("исследуй квантовые вычисления" -> dict with success=True, type="research", artifacts).
3. no-match -> None ("какая погода в Париже?").
4. memory bypass (legacy_route={"type": "memory"} -> None).
5. plan bypass (legacy_route={"type": "plan"} -> None).
6. image bypass (legacy_route={"type": "image"} -> None).
7. presentation bypass (legacy_route={"type": "presentation"} -> None).
8. document bypass (legacy_route={"type": "document"} -> None).
9. file bypass (legacy_route={"type": "file"} -> None).
10. subagent bypass (legacy_route={"type": "subagent"} -> None).
11. project tool bypass (legacy_route={"type": "tool", "tool": "list_files"} -> None).
12. disabled agent (default returns dict with success=False).
13. fallback_on_disabled=True returns None.
14. AgentResult failure (agent returns success=False -> bridge returns adapted dict with success=False, error).
15. exception safety (exception in execution -> caught, returns success=False, no crash).
16. artifacts preservation (serialized in artifacts list and present in result.artifacts).
17. created_files preservation (in created_files list).
18. result key contains original AgentResult object.
19. zero hardcoded Domain Agent imports in agents/bridge.py.
20. verification that during bypass, AgentRouter.preview_route is NOT called (0 calls).
21. custom Domain Agent works seamlessly without bridge modification.
22. empty/invalid request handling ("", "   ", None, 12345 -> returns None).
"""

import ast
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
from agents.bridge import MultiAgentBridge, DEFAULT_BYPASS_ROUTE_TYPES, DEFAULT_BYPASS_TOOLS
from agents.executor import AgentExecutor
from agents.household import HouseholdAgent
from agents.registry import AgentRegistry
from agents.research import ResearchAgent
from agents.router import AgentRouter, RouteResult
from agents.service import AgentService, reset_agent_service
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestMultiAgentBridge(unittest.TestCase):
    """Тестирование переходного слоя MultiAgentBridge."""

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
        self.bridge = MultiAgentBridge(service=self.service)

    def tearDown(self):
        reset_agent_service()

    def test_01_household_handled_successfully(self):
        """1. Household успешно обрабатывается через Bridge."""
        task = "создай задачу Купить молоко"
        self.assertTrue(self.bridge.can_handle(task))

        result = self.bridge.try_process(task)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["type"], "tasks")
        self.assertIn("Купить молоко", result["answer"])
        self.assertEqual(result["answer"], result["message"])
        self.assertIsInstance(result["result"], AgentResult)
        self.assertTrue(result["result"].success)
        self.assertEqual(result["result"].data["task"]["title"], "Купить молоко")

    def test_02_research_handled_with_mock_worker(self):
        """2. Research успешно обрабатывается через Bridge с mock worker."""
        task = "исследуй квантовые вычисления"
        self.assertTrue(self.bridge.can_handle(task))

        mock_worker_result = AgentResult.ok(
            message="Исследование квантовых вычислений завершено.",
            data={"topic": "квантовые вычисления", "depth": "advanced"},
            created_files=["docs/quantum.md"],
            artifacts=[Artifact.from_text("Квантовый отчет", name="quantum.md", path="docs/quantum.md")]
        )

        with patch.object(self.research_agent, "execute", return_value=mock_worker_result):
            result = self.bridge.try_process(task)

            self.assertIsInstance(result, dict)
            self.assertTrue(result["success"])
            self.assertEqual(result["type"], "research")
            self.assertEqual(result["answer"], "Исследование квантовых вычислений завершено.")
            self.assertEqual(result["created_files"], ["docs/quantum.md"])
            self.assertEqual(len(result["artifacts"]), 1)
            self.assertEqual(result["artifacts"][0]["name"], "quantum.md")
            self.assertIsInstance(result["result"], AgentResult)

    def test_03_no_match_returns_none(self):
        """3. no-match: нераспознанный запрос возвращает None."""
        task = "какая погода в Париже?"
        self.assertFalse(self.bridge.can_handle(task))
        self.assertIsNone(self.bridge.try_process(task))

    def test_04_memory_bypass(self):
        """4. memory bypass: запросы с legacy_route type=memory возвращают None."""
        legacy_route = {"type": "memory", "action": "remember", "query": "мой город Москва"}
        task = "запомни что я живу в Москве"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_05_plan_bypass(self):
        """5. plan bypass: запросы с legacy_route type=plan возвращают None."""
        legacy_route = {"type": "plan", "steps": ["step 1", "step 2"]}
        task = "составь план переезда"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_06_image_bypass(self):
        """6. image bypass: запросы с legacy_route type=image возвращают None."""
        legacy_route = {"type": "image", "prompt": "котик на траве"}
        task = "нарисуй котика на траве"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_07_presentation_bypass(self):
        """7. presentation bypass: запросы с legacy_route type=presentation возвращают None."""
        legacy_route = {"type": "presentation", "topic": "Machine Learning"}
        task = "сделай презентацию по машинному обучению"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_08_document_bypass(self):
        """8. document bypass: запросы с legacy_route type=document возвращают None."""
        legacy_route = {"type": "document", "topic": "Отчет"}
        task = "создай документ отчета"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_09_file_bypass(self):
        """9. file bypass: запросы с legacy_route type=file возвращают None."""
        legacy_route = {"type": "file", "action": "read"}
        task = "прочитай файл test.txt"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_10_subagent_bypass(self):
        """10. subagent bypass: запросы с legacy_route type=subagent возвращают None."""
        legacy_route = {"type": "subagent", "agent": "worker"}
        task = "запусти воркер"

        self.assertFalse(self.bridge.can_handle(task, legacy_route=legacy_route))
        self.assertIsNone(self.bridge.try_process(task, legacy_route=legacy_route))

    def test_11_project_tool_bypass(self):
        """11. project tool bypass: инструменты проекта возвращают None."""
        tools_to_test = ["list_files", "find_file", "structure", "search_files"]
        for tool_name in tools_to_test:
            legacy_route = {"type": "tool", "tool": tool_name}
            task = f"выполни команду {tool_name}"

            self.assertFalse(
                self.bridge.can_handle(task, legacy_route=legacy_route),
                f"Tool {tool_name} should be bypassed in can_handle"
            )
            self.assertIsNone(
                self.bridge.try_process(task, legacy_route=legacy_route),
                f"Tool {tool_name} should return None in try_process"
            )

    def test_12_disabled_agent_default_returns_error_dict(self):
        """12. disabled agent: по умолчанию возвращается словарь ошибки (success=False)."""
        self.registry.disable("household")
        task = "создай задачу Купить чай"

        # can_handle возвращает True, так как мост перехватывает и формирует структурированное сообщение об ошибке
        self.assertTrue(self.bridge.can_handle(task))

        result = self.bridge.try_process(task)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("отключен", result["error"].lower())
        self.assertIn("отключен", result["answer"].lower())
        self.assertIsInstance(result["result"], AgentResult)
        self.assertFalse(result["result"].success)

    def test_13_disabled_agent_fallback_on_disabled_returns_none(self):
        """13. fallback_on_disabled=True возвращает None для отключенного агента."""
        self.registry.disable("household")
        fallback_bridge = MultiAgentBridge(service=self.service, fallback_on_disabled=True)
        task = "создай задачу Купить чай"

        self.assertFalse(fallback_bridge.can_handle(task))
        self.assertIsNone(fallback_bridge.try_process(task))

    def test_14_agent_result_failure_adaptation(self):
        """14. AgentResult failure адаптируется в словарь с success=False и error."""
        task = "создай задачу Сломать базу данных"
        failed_result = AgentResult.fail(
            error="Database locked exception",
            message="Не удалось сохранить задачу в базу данных.",
            data={"reason": "locked"}
        )

        with patch.object(self.household_agent, "execute", return_value=failed_result):
            result = self.bridge.try_process(task)

            self.assertIsInstance(result, dict)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "Database locked exception")
            self.assertEqual(result["answer"], "Не удалось сохранить задачу в базу данных.")
            self.assertEqual(result["message"], result["answer"])
            self.assertEqual(result["data"]["reason"], "locked")
            self.assertEqual(result["result"], failed_result)

    def test_15_exception_safety(self):
        """15. Безопасность при исключениях: сбой в сервисе перехватывается без падения."""
        task = "создай задачу Проверить сбой"

        with patch.object(self.service, "execute", side_effect=RuntimeError("Критический сбой сервиса!")):
            result = self.bridge.try_process(task)

            self.assertIsInstance(result, dict)
            self.assertFalse(result["success"])
            self.assertIn("RuntimeError", result["error"])
            self.assertIn("Критический сбой сервиса!", result["error"])
            self.assertIn("произошла ошибка", result["answer"])
            self.assertIsInstance(result["result"], AgentResult)
            self.assertFalse(result["result"].success)

    def test_16_artifacts_preservation(self):
        """16. Сохранение артефактов: сериализация в список словарей и сохранение в result."""
        task = "исследуй мультиагентные системы"

        art1 = Artifact.from_text("# Multi-agent report", name="report.md")
        art2 = Artifact.from_file("/tmp/diag.png", type=ArtifactType.IMAGE)
        rich_result = AgentResult.ok(
            message="Исследование готово",
            artifacts=[art1, art2]
        )

        with patch.object(self.research_agent, "execute", return_value=rich_result):
            result = self.bridge.try_process(task)

            self.assertIsInstance(result, dict)
            self.assertTrue(result["success"])
            self.assertEqual(len(result["artifacts"]), 2)
            # Проверяем сериализацию первого артефакта
            self.assertEqual(result["artifacts"][0]["name"], "report.md")
            self.assertEqual(result["artifacts"][0]["content"], "# Multi-agent report")
            # Проверяем сохранение исходных объектов в result
            self.assertEqual(len(result["result"].artifacts), 2)
            self.assertEqual(result["result"].artifacts[0].name, "report.md")

    def test_17_created_files_preservation(self):
        """17. Сохранение created_files в адаптированном словаре."""
        task = "создай заметку Закупки"
        rich_result = AgentResult.ok(
            message="Заметка сохранена",
            created_files=["/data/notes/purchases.json", "/data/notes/purchases.txt"]
        )

        with patch.object(self.household_agent, "execute", return_value=rich_result):
            result = self.bridge.try_process(task)

            self.assertIsInstance(result, dict)
            self.assertTrue(result["success"])
            self.assertEqual(
                result["created_files"],
                ["/data/notes/purchases.json", "/data/notes/purchases.txt"]
            )
            self.assertEqual(result["result"].created_files, result["created_files"])

    def test_18_result_key_contains_original_agent_result(self):
        """18. Ключ result содержит точный исходный объект AgentResult."""
        task = "создай задачу Полить цветы"
        result = self.bridge.try_process(task)

        self.assertIn("result", result)
        self.assertIsInstance(result["result"], AgentResult)
        self.assertTrue(result["result"].success)
        self.assertEqual(result["result"].data["task"]["title"], "Полить цветы")

    def test_19_zero_hardcoded_domain_agent_imports(self):
        """19. Принцип OCP: в agents/bridge.py отсутствуют жесткие импорты доменных агентов."""
        bridge_file = PROJECT_ROOT / "agents" / "bridge.py"
        self.assertTrue(bridge_file.exists())

        source = bridge_file.read_text(encoding="utf-8")
        parsed = ast.parse(source)

        forbidden_names = {
            "HouseholdAgent",
            "ResearchAgent",
            "CodingAgent",
            "MemoryAgent",
            "household",
            "research",
        }

        imported_names = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[0])
                    if alias.asname:
                        imported_names.add(alias.asname)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[-1])
                for alias in node.names:
                    imported_names.add(alias.name)
                    if alias.asname:
                        imported_names.add(alias.asname)

        intersection = imported_names.intersection(forbidden_names)
        self.assertEqual(
            intersection,
            set(),
            f"agents/bridge.py violates OCP by importing domain agents: {intersection}"
        )

    def test_20_bypass_does_not_call_preview_route(self):
        """20. При bypass AgentRouter.preview_route / service.preview_route НЕ вызывается (0 вызовов)."""
        legacy_routes = [
            {"type": "memory"},
            {"type": "plan"},
            {"type": "image"},
            {"type": "presentation"},
            {"type": "document"},
            {"type": "file"},
            {"type": "subagent"},
            {"type": "tool", "tool": "list_files"},
        ]

        with patch.object(self.service, "preview_route") as mock_preview:
            for leg_route in legacy_routes:
                res_can = self.bridge.can_handle("создай задачу Тест", legacy_route=leg_route)
                res_proc = self.bridge.try_process("создай задачу Тест", legacy_route=leg_route)

                self.assertFalse(res_can)
                self.assertIsNone(res_proc)

            mock_preview.assert_not_called()

    def test_21_custom_domain_agent_seamless_extension(self):
        """21. Подключение стороннего Custom Domain Agent без модификации MultiAgentBridge."""
        class WeatherAgent(BaseAgent):
            name = "weather"
            description = "Agent for weather forecasts"
            capabilities = ["weather_forecast"]

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="В Париже сейчас +22°C, солнечно.",
                    data={"city": "Париж", "temperature": 22, "condition": "sunny"}
                )

        weather_agent = WeatherAgent()
        self.registry.register(weather_agent)
        self.router.register_capability_rule("weather_forecast", [r"\b(?:погода|прогноз|weather)\b"])

        task = "какая погода в Париже?"
        self.assertTrue(self.bridge.can_handle(task))

        result = self.bridge.try_process(task)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertEqual(result["type"], "weather_forecast")
        self.assertEqual(result["answer"], "В Париже сейчас +22°C, солнечно.")
        self.assertEqual(result["data"]["temperature"], 22)
        self.assertIsInstance(result["result"], AgentResult)

    def test_22_empty_and_invalid_inputs(self):
        """22. Пустые и некорректные входные данные возвращают None."""
        invalid_inputs = ["", "   ", "\n\t", None, 12345, [], {}]

        for inp in invalid_inputs:
            self.assertFalse(
                self.bridge.can_handle(inp),  # type: ignore
                f"can_handle({repr(inp)}) should be False"
            )
            self.assertIsNone(
                self.bridge.try_process(inp),  # type: ignore
                f"try_process({repr(inp)}) should be None"
            )


if __name__ == "__main__":
    unittest.main()
