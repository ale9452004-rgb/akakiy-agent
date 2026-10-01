"""
Тестирование высокоуровневого доменного агента ResearchAgent (Domain Layer, agents/research.py).
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.registry import AgentRegistry as DomainAgentRegistry
from agents.research import ResearchAgent as DomainResearchAgent
from tools.agents.result import AgentResult, Artifact


class TestDomainResearchAgent(unittest.TestCase):
    """Тестирование высокоуровневого доменного агента ResearchAgent (Domain Layer)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = DomainResearchAgent(output_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_domain_metadata_and_inheritance(self):
        """Проверка наследования от BaseAgent, метаданных и атрибутов."""
        self.assertIsInstance(self.agent, BaseAgent)
        self.assertEqual(self.agent.name, "research")
        self.assertTrue(len(self.agent.description) > 0)
        self.assertTrue(self.agent.enabled)

    def test_domain_capabilities_and_tools(self):
        """Проверка заявленных возможностей и инструментов доменного агента."""
        expected_caps = ["research", "search", "analysis", "investigation", "information"]
        for cap in expected_caps:
            self.assertIn(cap, self.agent.capabilities)
            self.assertTrue(self.agent.has_capability(cap))

        expected_tools = ["research", "gather_information", "generate_report", "search"]
        for tool in expected_tools:
            self.assertIn(tool, self.agent.tools)
            self.assertTrue(self.agent.has_tool(tool))

        d = self.agent.to_dict()
        self.assertEqual(d["name"], "research")
        self.assertIn("analysis", d["capabilities"])

    def test_execute_success_creates_report_and_artifact(self):
        """Успешный запуск execute() делегирует сбор воркеру и возвращает AgentResult."""
        res = self.agent.execute("исследуй архитектуру проекта Акакий")

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("успешно выполнено", res.message)
        self.assertEqual(len(res.created_files), 1)

        saved_file = Path(res.created_files[0])
        self.assertTrue(saved_file.exists())
        self.assertTrue(saved_file.name.endswith(".md"))

        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertIsInstance(art, Artifact)
        self.assertTrue(art.is_research)
        self.assertEqual(res.data.get("domain_agent"), "research")

    def test_execute_with_context_and_kwargs(self):
        """Запуск с явно переданными метаданными и вопросами."""
        res = self.agent.execute(
            "исследование памяти",
            context={"topic": "Подсистема памяти"},
            questions=["Как работает MemoryManager?"]
        )
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("topic"), "Подсистема памяти")

    def test_unsupported_and_foreign_queries(self):
        """Отклонение пустого запроса, неподдерживаемого действия и чужого домена."""
        # 1. Пустой запрос
        res1 = self.agent.execute("")
        self.assertFalse(res1.success)
        self.assertIn("пустым", res1.message.lower())

        # 2. Неподдерживаемое действие в action
        res2 = self.agent.execute("какой-то запрос", action="delete_task")
        self.assertFalse(res2.success)
        self.assertIn("не поддерживается", res2.message.lower())

        # 3. Запрос из чужого (бытового) домена без исследовательского контекста
        res3 = self.agent.execute("создай задачу Купить молоко")
        self.assertFalse(res3.success)
        self.assertIn("другому домену", res3.message.lower())

    def test_worker_error_handling(self):
        """Обработка ошибок и исключений worker-слоя."""
        mock_worker = MagicMock()
        mock_worker.run.side_effect = RuntimeError("Worker out of memory")

        agent_with_mock = DomainResearchAgent(worker=mock_worker)
        res = agent_with_mock.execute("исследуй тему искусственного интеллекта")

        self.assertIsInstance(res, AgentResult)
        self.assertFalse(res.success)
        self.assertIn("Worker out of memory", res.error)

    def test_registry_integration(self):
        """Регистрация и выполнение через AgentRegistry (multi-agent registry)."""
        reg = DomainAgentRegistry()
        reg.register(self.agent)

        self.assertTrue(reg.has("research"))
        self.assertIs(reg.get("research"), self.agent)

        # Поиск по capability
        found = reg.find_by_capability("research")
        self.assertEqual(len(found), 1)
        self.assertIs(found[0], self.agent)

        found_analysis = reg.find_by_capability("analysis")
        self.assertEqual(len(found_analysis), 1)

        # Выполнение через реестр
        res = reg.execute("research", "исследуй подсистему субагентов")
        self.assertTrue(res.success)
        self.assertEqual(len(res.created_files), 1)

        # Блокировка отключенного агента
        reg.disable("research")
        res_dis = reg.execute("research", "исследуй тему")
        self.assertFalse(res_dis.success)
        self.assertIn("отключен", res_dis.error)


if __name__ == "__main__":
    unittest.main()
