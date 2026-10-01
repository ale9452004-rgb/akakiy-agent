"""
Targeted tests for multi-agent architecture: BaseAgent and AgentRegistry.
"""

import os
import sys
import unittest
from typing import Any, Dict, Optional

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from agents.base import BaseAgent
from agents.registry import AgentRegistry, get_agent_registry, reset_agent_registry
from tools.agents.result import AgentResult, Artifact, ArtifactType


class DummyHouseholdAgent(BaseAgent):
    """Тестовый агент для бытовых задач (Household)."""
    name = "household"
    description = "Управление задачами, списками и напоминаниями."
    capabilities = ["household", "tasks", "reminders", "lists"]
    tools = ["create_task", "complete_task", "list_tasks"]

    def execute(self, task: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> AgentResult:
        if "ошибка" in task.lower():
            raise RuntimeError("Искусственная ошибка бытового агента")
        return AgentResult.ok(
            message=f"Бытовая задача выполнена: {task}",
            data={"agent": self.name, "task": task, "extra": kwargs}
        )


class DummyResearchAgent(BaseAgent):
    """Тестовый агент для исследовательских задач (Research)."""
    name = "research"
    description = "Поиск и аналитика данных."
    capabilities = ["research", "search", "analytics"]
    tools = ["web_search", "read_url", "extract_summary"]

    def execute(self, task: str, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> AgentResult:
        art = Artifact(name="report.txt", type=ArtifactType.TEXT, content="Результаты анализа")
        return AgentResult.ok(
            message=f"Исследование завершено: {task}",
            artifacts=[art]
        )


class TestBaseAgentInterface(unittest.TestCase):
    """Тестирование базового интерфейса BaseAgent."""

    def test_base_agent_attributes(self):
        agent = DummyHouseholdAgent()
        self.assertEqual(agent.name, "household")
        self.assertIn("household", agent.capabilities)
        self.assertIn("tasks", agent.capabilities)
        self.assertIn("create_task", agent.tools)
        self.assertTrue(agent.enabled)

    def test_has_capability_case_insensitive(self):
        agent = DummyHouseholdAgent()
        self.assertTrue(agent.has_capability("household"))
        self.assertTrue(agent.has_capability("HOUSEHOLD"))
        self.assertTrue(agent.has_capability("  tasks  "))
        self.assertFalse(agent.has_capability("coding"))

    def test_has_tool_case_insensitive(self):
        agent = DummyHouseholdAgent()
        self.assertTrue(agent.has_tool("create_task"))
        self.assertTrue(agent.has_tool("CREATE_TASK"))
        self.assertFalse(agent.has_tool("non_existent_tool"))

    def test_to_dict_and_repr(self):
        agent = DummyHouseholdAgent()
        d = agent.to_dict()
        self.assertEqual(d["name"], "household")
        self.assertEqual(d["tools"], ["create_task", "complete_task", "list_tasks"])
        self.assertIn("household", repr(agent))

    def test_execute_returns_agent_result(self):
        agent = DummyHouseholdAgent()
        res = agent.execute("Купить продукты")
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("Купить продукты", res.message)


class TestAgentRegistry(unittest.TestCase):
    """Тестирование функциональности AgentRegistry."""

    def setUp(self):
        self.registry = AgentRegistry()
        self.household = DummyHouseholdAgent()
        self.research = DummyResearchAgent()

    def tearDown(self):
        self.registry.clear()
        reset_agent_registry()

    def test_register_and_get_by_name(self):
        self.registry.register(self.household)
        self.assertTrue(self.registry.has("household"))
        self.assertTrue(self.registry.has("HOUSEHOLD"))

        retrieved = self.registry.get("household")
        self.assertIs(retrieved, self.household)

        retrieved_upper = self.registry.get("  HOUSEHOLD  ")
        self.assertIs(retrieved_upper, self.household)

    def test_register_invalid_agent_raises(self):
        with self.assertRaises(TypeError):
            self.registry.register("not_an_agent")  # type: ignore[arg-type]

        class NamelessAgent(BaseAgent):
            name = ""
            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok()

        with self.assertRaises(ValueError):
            self.registry.register(NamelessAgent())

    def test_unregister(self):
        self.registry.register(self.household)
        self.assertEqual(len(self.registry), 1)

        removed = self.registry.unregister("household")
        self.assertIs(removed, self.household)
        self.assertFalse(self.registry.has("household"))
        self.assertIsNone(self.registry.get("household"))

    def test_list_agents(self):
        self.registry.register(self.household)
        self.registry.register(self.research)

        all_agents = self.registry.list_agents()
        self.assertEqual(len(all_agents), 2)

        # Отключаем одного агента
        self.registry.disable("household")
        enabled_agents = self.registry.list_agents(enabled_only=True)
        self.assertEqual(len(enabled_agents), 1)
        self.assertEqual(enabled_agents[0].name, "research")

    def test_find_by_capability(self):
        self.registry.register(self.household)
        self.registry.register(self.research)

        # Поиск по общей или специфичной capability
        research_agents = self.registry.find_by_capability("research")
        self.assertEqual(len(research_agents), 1)
        self.assertEqual(research_agents[0].name, "research")

        household_agents = self.registry.find_by_capability("tasks")
        self.assertEqual(len(household_agents), 1)
        self.assertEqual(household_agents[0].name, "household")

        unknown = self.registry.find_by_capability("quantum_computing")
        self.assertEqual(len(unknown), 0)

    def test_find_by_tool(self):
        self.registry.register(self.household)
        self.registry.register(self.research)

        agents_with_tool = self.registry.find_by_tool("web_search")
        self.assertEqual(len(agents_with_tool), 1)
        self.assertEqual(agents_with_tool[0].name, "research")

    def test_enable_disable(self):
        self.registry.register(self.household)
        self.assertTrue(self.household.enabled)

        self.assertTrue(self.registry.disable("household"))
        self.assertFalse(self.household.enabled)

        self.assertTrue(self.registry.enable("household"))
        self.assertTrue(self.household.enabled)

        self.assertFalse(self.registry.enable("non_existent"))

    def test_execute_via_registry_success(self):
        self.registry.register(self.household)
        res = self.registry.execute("household", "Запланировать встречу")
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("Запланировать встречу", res.message)

    def test_execute_via_registry_unknown_agent(self):
        res = self.registry.execute("unknown_agent", "Некая задача")
        self.assertIsInstance(res, AgentResult)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error)

    def test_execute_via_registry_disabled_agent(self):
        self.registry.register(self.household)
        self.registry.disable("household")

        res = self.registry.execute("household", "Какая-то задача")
        self.assertIsInstance(res, AgentResult)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_execute_via_registry_handles_exceptions_gracefully(self):
        self.registry.register(self.household)
        res = self.registry.execute("household", "Произошла ошибка при выполнении")
        self.assertIsInstance(res, AgentResult)
        self.assertFalse(res.success)
        self.assertIn("Исключение при выполнении", res.error)

    def test_singleton_get_and_reset(self):
        reg1 = get_agent_registry()
        reg2 = get_agent_registry()
        self.assertIs(reg1, reg2)

        reset_agent_registry()
        reg3 = get_agent_registry()
        self.assertIsNot(reg1, reg3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
