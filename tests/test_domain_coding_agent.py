"""
Тесты доменного агента разработки (Domain CodingAgent, agents/coding.py).

Покрывает:
1. Создание CodingAgent;
2. Атрибут name ("coding");
3. Атрибут display_name ("Разработка");
4. Capabilities агента;
5. Делегирование существующему coding worker (tools/agents/coding.py);
6. Корректный AgentResult и артефакты;
7. Progress callback (только реальные этапы: анализ, изменения, проверка);
8. Вызов execute() без context;
9. Обработка ошибки worker (success=False);
10. Обработка исключения worker (exception handling);
11. MultiAgentBridge: "coding" больше не находится в bypass;
12. Простой coding request попадает в CodingAgent через MultiAgentBridge;
13. "list_files" остаётся Project Tool (не перехватывается CodingAgent);
14. "find_file" остаётся Project Tool (не перехватывается CodingAgent);
15. Сложная составная coding-задача попадает в Teamwork (не обходит Teamwork);
16. Обычный разговор (chat) не попадает в CodingAgent.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agents.base import BaseAgent
from agents.bootstrap import ensure_default_domain_agents
from agents.bridge import MultiAgentBridge, DEFAULT_BYPASS_ROUTE_TYPES
from agents.coding import CodingAgent
from agents.registry import AgentRegistry, reset_agent_registry
from agents.router import AgentRouter
from agents.service import AgentService
from tools.agents.context import AgentContext
from tools.agents.coding import CodingAgent as SubAgentCodingWorker
from tools.agents.result import AgentResult, Artifact, ArtifactType


class TestDomainCodingAgentUnit(unittest.TestCase):
    """Модульные тесты доменного агента CodingAgent (пункты 1-10)."""

    def setUp(self):
        self.agent = CodingAgent()

    def test_01_creation(self):
        """1. Создание экземпляра CodingAgent."""
        self.assertIsInstance(self.agent, BaseAgent)
        self.assertIsInstance(self.agent, CodingAgent)

    def test_02_name(self):
        """2. Проверка имени агента."""
        self.assertEqual(self.agent.name, "coding")

    def test_03_display_name(self):
        """3. Проверка человекочитаемого display_name."""
        self.assertEqual(self.agent.display_name, "Разработка")

    def test_04_capabilities(self):
        """4. Проверка capabilities доменного агента."""
        for cap in ["coding", "code", "edit", "patch", "refactor", "verify"]:
            self.assertIn(cap, self.agent.capabilities)
            self.assertTrue(self.agent.has_capability(cap))

    def test_05_delegation_to_worker(self):
        """5. Проверка делегирования задачи существующему coding worker."""
        mock_worker = MagicMock(spec=SubAgentCodingWorker)
        mock_worker.run.return_value = AgentResult.ok(
            message="Код успешно проанализирован.",
            created_files=[],
            data={"mode": "analyze"}
        )

        agent = CodingAgent(worker=mock_worker)
        res = agent.execute("проанализируй код в файле demo.py")

        mock_worker.run.assert_called_once()
        self.assertTrue(res.success)
        self.assertEqual(res.message, "Код успешно проанализирован.")

    def test_06_correct_agent_result(self):
        """6. Корректный AgentResult и сохранение данных/артефактов."""
        mock_worker = MagicMock(spec=SubAgentCodingWorker)
        test_artifact = Artifact.from_code(
            path="demo.py",
            name="demo.py",
            content="print(1)",
            language="python"
        )
        mock_worker.run.return_value = AgentResult.ok(
            message="Изменения внесены.",
            created_files=["demo.py"],
            artifacts=[test_artifact],
            data={"mode": "edit"}
        )

        agent = CodingAgent(worker=mock_worker)
        res = agent.execute("исправь код в файле demo.py")

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertEqual(res.created_files, ["demo.py"])
        self.assertEqual(len(res.artifacts), 1)
        self.assertEqual(res.data.get("domain_agent"), "coding")
        self.assertEqual(res.data.get("display_name"), "Разработка")

    def test_07_progress_callback(self):
        """7. Progress callback вызывается для реальных этапов работы."""
        events = []

        def on_progress(step, **kwargs):
            events.append(step)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir).resolve()
            test_file = tmp_path / "sample.py"
            test_file.write_text("x = 1\n", encoding="utf-8")

            worker = SubAgentCodingWorker(project_path=tmp_path)
            agent = CodingAgent(worker=worker, project_path=tmp_path)

            ctx = AgentContext(
                task=f"замени 'x = 1' на 'x = 2' в файле {test_file.name}",
                progress_callback=on_progress
            )

            res = agent.execute(ctx.task, context=ctx)
            self.assertTrue(res.success)

            # Проверяем, что реальные этапы были вызваны
            self.assertIn("Анализирую код…", events)
            self.assertIn("Применяю изменения…", events)
            self.assertIn("Проверяю результат…", events)

    def test_08_execute_without_context(self):
        """8. Вызов execute() без context (None)."""
        mock_worker = MagicMock(spec=SubAgentCodingWorker)
        mock_worker.run.return_value = AgentResult.ok(message="OK")

        agent = CodingAgent(worker=mock_worker)
        res = agent.execute("проанализируй код", context=None)

        self.assertTrue(res.success)
        mock_worker.run.assert_called_once()

    def test_09_worker_failure(self):
        """9. Корректная обработка ошибки worker (success=False)."""
        mock_worker = MagicMock(spec=SubAgentCodingWorker)
        mock_worker.run.return_value = AgentResult.fail(
            error="Синтаксическая ошибка",
            message="Ошибка валидации синтаксиса"
        )

        agent = CodingAgent(worker=mock_worker)
        res = agent.execute("исправь код")

        self.assertFalse(res.success)
        self.assertEqual(res.error, "Синтаксическая ошибка")
        self.assertEqual(res.data.get("domain_agent"), "coding")

    def test_10_worker_exception(self):
        """10. Безопасная обработка исключения внутри worker."""
        mock_worker = MagicMock(spec=SubAgentCodingWorker)
        mock_worker.run.side_effect = RuntimeError("Диск переполнен")

        agent = CodingAgent(worker=mock_worker)
        res = agent.execute("проанализируй код")

        self.assertFalse(res.success)
        self.assertIn("RuntimeError", res.error)
        self.assertIn("Диск переполнен", res.message)


class TestDomainCodingRoutingAndBridge(unittest.TestCase):
    """Интеграционные тесты маршрутизации и моста (пункты 11-16)."""

    def setUp(self):
        reset_agent_registry()
        self.reg = ensure_default_domain_agents()
        self.router = AgentRouter(registry=self.reg)
        self.service = AgentService(router=self.router, registry=self.reg)
        self.bridge = MultiAgentBridge(service=self.service)

    def tearDown(self):
        reset_agent_registry()

    def test_11_coding_not_in_bypass(self):
        """11. Проверка, что 'coding' больше не входит в DEFAULT_BYPASS_ROUTE_TYPES."""
        self.assertNotIn("coding", DEFAULT_BYPASS_ROUTE_TYPES)
        self.assertNotIn("coding", self.bridge.bypass_route_types)

    def test_12_simple_coding_request_routes_to_coding_agent(self):
        """12. Простой запрос по коду попадает в CodingAgent через MultiAgentBridge."""
        query = "кодинг: проверь синтаксис в tools/agent.py"
        preview = self.service.preview_route(query)

        self.assertTrue(preview.success)
        self.assertEqual(preview.agent_name, "coding")

        can_h = self.bridge.can_handle(query, legacy_route={"type": "coding"})
        self.assertTrue(can_h)

        res = self.bridge.try_process(
            user_input=query,
            legacy_route={"type": "coding"}
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "coding")
        self.assertTrue(res["success"])

    def test_13_list_files_remains_project_tool(self):
        """13. 'list_files' остаётся Project Tool и не перехватывается CodingAgent."""
        from tools.agent import Agent

        agent = Agent()
        # "покажи файлы проекта" должно обработаться через fast-path project tools
        route = agent.router.route("покажи файлы проекта")
        self.assertEqual(route["type"], "tool")
        self.assertEqual(route["tool"], "list_files")

        # MultiAgentBridge не должен обрабатывать этот запрос
        self.assertFalse(agent.bridge.can_handle("покажи файлы проекта", legacy_route=route))

    def test_14_find_file_remains_project_tool(self):
        """14. 'find_file' остаётся Project Tool и не перехватывается CodingAgent."""
        from tools.agent import Agent

        agent = Agent()
        route = agent.router.route("найди файл agent.py")
        self.assertEqual(route["type"], "tool")
        self.assertEqual(route["tool"], "find_file")

        self.assertFalse(agent.bridge.can_handle("найди файл agent.py", legacy_route=route))

    def test_15_complex_task_stays_in_teamwork(self):
        """15. Сложная составная задача по коду остаётся в Teamwork и не обходит её."""
        from tools.agent import Agent

        agent = Agent()
        complex_query = "кодинг: проанализируй tools/agent.py, исправь ошибку и запусти тесты"

        # Проверяем, что teamwork считает задачу сложной
        is_complex = agent.teamwork.is_complex_task(complex_query)
        self.assertTrue(is_complex, "Сложная задача с 'и запусти тесты' должна определяться Teamwork")

        with patch.object(agent.teamwork, "run", return_value={"success": True, "message": "Teamwork executed"}) as mock_tw:
            res = agent.process(complex_query)
            mock_tw.assert_called_once()
            self.assertEqual(res["type"], "plan_execution")

    def test_16_chat_fallback_not_routed_to_coding(self):
        """16. Обычный разговорный запрос (chat) не попадает в CodingAgent."""
        chat_queries = [
            "Привет, как дела?",
            "Кто такой Наполеон?",
            "Какая сегодня погода?",
            "Что ты умеешь делать?",
        ]
        for q in chat_queries:
            preview = self.service.preview_route(q)
            self.assertFalse(
                preview.success,
                f"Разговорный запрос '{q}' не должен сопоставляться с доменным агентом (получено: {preview.agent_name})"
            )
            self.assertFalse(
                self.bridge.can_handle(q),
                f"Bridge не должен обрабатывать chat-запрос '{q}'"
            )


if __name__ == "__main__":
    unittest.main()
