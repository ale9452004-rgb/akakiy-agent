"""
Тесты событий жизненного цикла Domain Agent (before_agent, agent_progress, after_agent).

Проверяет:
1. before_agent отправляется перед выполнением агента через AgentExecutor.
2. after_agent отправляется после успешного выполнения с success=True.
3. after_agent отправляется при ошибке/исключении с success=False.
4. В событиях присутствуют agent, display_name и task.
5. AgentContext.report_progress() вызывает progress callback.
6. Без callback report_progress() полностью безопасен.
7. HouseholdAgent отправляет осмысленный progress (например, 'Создаю задачу…').
8. ResearchAgent отправляет прогресс основных этапов ('Исследую запрос…', 'Анализирую результаты…', 'Формирую отчёт…').
9. Существующие вызовы Domain Agent без context (context=None или context={}) не ломаются.
10. Legacy tools / worker agents / Teamwork не отправляют ложные Domain Agent events.
"""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.context import AgentContext
from agents.executor import AgentExecutor
from agents.household import HouseholdAgent
from agents.registry import AgentRegistry
from agents.research import ResearchAgent
from agents.router import AgentRouter
from tools.agents.result import AgentResult, Artifact
from tools.dispatcher import dispatch, get_action_observer, set_action_observer
from tools.household import HouseholdManager


class TestDomainAgentLifecycleEvents(unittest.TestCase):
    """Тестирование сквозных событий жизненного цикла Domain Agent."""

    def setUp(self):
        self.events = []

        def observer(event_type, data):
            self.events.append((event_type, dict(data)))

        self.observer = observer
        set_action_observer(self.observer)

        self.registry = AgentRegistry()
        self.temp_dir = tempfile.mkdtemp()
        self.storage_file = Path(self.temp_dir) / "household.json"
        self.hm = HouseholdManager(storage_path=self.storage_file)

        self.household_agent = HouseholdAgent(household_manager=self.hm)
        self.research_agent = ResearchAgent(output_dir=self.temp_dir)

        self.registry.register(self.household_agent)
        self.registry.register(self.research_agent)
        self.router = AgentRouter(registry=self.registry)
        self.executor = AgentExecutor(router=self.router, observer=self.observer)

    def tearDown(self):
        set_action_observer(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_1_and_2_before_and_after_agent_on_success(self):
        """1 & 2. before_agent отправляется перед выполнением, after_agent — после с success=True."""
        route = self.router.route("создай задачу Купить чай")
        result = self.executor.execute(route, "создай задачу Купить чай")

        self.assertTrue(result.success)

        event_types = [e[0] for e in self.events]
        self.assertIn("before_agent", event_types)
        self.assertIn("after_agent", event_types)

        # Проверяем порядок: before_agent идет перед after_agent
        idx_before = event_types.index("before_agent")
        idx_after = event_types.index("after_agent")
        self.assertLess(idx_before, idx_after)

        # Проверяем after_agent payload
        after_payload = self.events[idx_after][1]
        self.assertTrue(after_payload["success"])

    def test_3_after_agent_on_exception(self):
        """3. after_agent отправляется при ошибке/исключении с success=False."""
        class ExplodingAgent(BaseAgent):
            name = "exploding"
            display_name = "Взрывающийся агент"
            capabilities = ["explode"]

            def execute(self, task, context=None, **kwargs):
                raise RuntimeError("Критический сбой агента!")

        bad_agent = ExplodingAgent()
        res = self.executor.execute(bad_agent, "взорвись")

        self.assertFalse(res.success)
        event_types = [e[0] for e in self.events]
        self.assertIn("before_agent", event_types)
        self.assertIn("after_agent", event_types)

        after_event = [e[1] for e in self.events if e[0] == "after_agent"][-1]
        self.assertFalse(after_event["success"])
        self.assertIn("Критический сбой", after_event.get("error", ""))

    def test_4_events_contain_agent_and_display_name(self):
        """4. В событиях присутствуют agent и display_name."""
        self.executor.execute(self.household_agent, "создай заметку Важная мысль")

        before_events = [e[1] for e in self.events if e[0] == "before_agent"]
        self.assertEqual(len(before_events), 1)
        self.assertEqual(before_events[0]["agent"], "household")
        self.assertEqual(before_events[0]["display_name"], "Домашние дела")
        self.assertEqual(before_events[0]["task"], "создай заметку Важная мысль")

        after_events = [e[1] for e in self.events if e[0] == "after_agent"]
        self.assertEqual(len(after_events), 1)
        self.assertEqual(after_events[0]["agent"], "household")
        self.assertEqual(after_events[0]["display_name"], "Домашние дела")
        self.assertTrue(after_events[0]["success"])

    def test_5_agent_context_report_progress_calls_callback(self):
        """5. AgentContext.report_progress() вызывает callback."""
        captured = []
        ctx = AgentContext(task="Тест", progress_callback=lambda s: captured.append(s))
        ctx.report_progress("Шаг А")
        ctx.report_progress("Шаг Б")

        self.assertEqual(captured, ["Шаг А", "Шаг Б"])

    def test_6_report_progress_without_callback_is_safe(self):
        """6. Без callback report_progress() безопасен."""
        ctx = AgentContext(task="Тест")
        try:
            ctx.report_progress("Некоторый шаг")
        except Exception as e:
            self.fail(f"report_progress() выбросил исключение без callback: {e}")

    def test_7_household_agent_emits_progress(self):
        """7. HouseholdAgent действительно отправляет progress."""
        route = self.router.route("создай задачу Полить цветы")
        result = self.executor.execute(route, "создай задачу Полить цветы")

        self.assertTrue(result.success)
        progress_events = [e[1] for e in self.events if e[0] == "agent_progress"]
        self.assertGreaterEqual(len(progress_events), 1)

        first_step = progress_events[0]
        self.assertEqual(first_step["agent"], "household")
        self.assertEqual(first_step["display_name"], "Домашние дела")
        self.assertIn("Создаю задачу", first_step["step"])

    def test_8_research_agent_emits_progress(self):
        """8. ResearchAgent действительно отправляет progress (основные этапы исследования)."""
        mock_worker_result = AgentResult.ok(
            message="Исследование завершено.",
            data={"summary": "Результаты анализа."},
            artifacts=[Artifact.from_text("Отчет", name="report.md")]
        )

        with patch.object(self.research_agent, "_get_worker") as mock_worker_getter:
            mock_worker = MagicMock()
            mock_worker.run.return_value = mock_worker_result
            mock_worker_getter.return_value = mock_worker

            route = self.router.route("исследуй новые технологии")
            result = self.executor.execute(route, "исследуй новые технологии")

            self.assertTrue(result.success)
            progress_events = [e[1] for e in self.events if e[0] == "agent_progress"]
            steps = [p["step"] for p in progress_events]

            self.assertIn("Исследую запрос…", steps)
            self.assertIn("Анализирую результаты…", steps)
            self.assertIn("Формирую отчёт…", steps)

            for p in progress_events:
                self.assertEqual(p["agent"], "research")
                self.assertEqual(p["display_name"], "Исследования")

    def test_9_calls_without_context_do_not_break(self):
        """9. Существующие вызовы Domain Agent без context не ломаются."""
        # 1. Прямой вызов с context=None
        res1 = self.household_agent.execute("создай задачу Задача без контекста", context=None)
        self.assertTrue(res1.success)

        # 2. Прямой вызов с context={} (обычный dict)
        res2 = self.household_agent.execute("создай задачу Задача с пустым словарем", context={})
        self.assertTrue(res2.success)

        # 3. Вызов ResearchAgent с context=None
        with patch.object(self.research_agent, "_get_worker") as mock_worker_getter:
            mock_worker = MagicMock()
            mock_worker.run.return_value = AgentResult.ok(message="OK")
            mock_worker_getter.return_value = mock_worker

            res3 = self.research_agent.execute("исследуй тему", context=None)
            self.assertTrue(res3.success)

    def test_10_legacy_tools_do_not_emit_domain_agent_events(self):
        """10. Legacy tools / worker agents не отправляют ложные Domain Agent events."""
        self.events.clear()

        # Выполняем обычный legacy tool через dispatcher.dispatch
        res = dispatch("list_files")
        self.assertTrue(res.get("success", True))

        event_types = [e[0] for e in self.events]
        self.assertNotIn("before_agent", event_types)
        self.assertNotIn("agent_progress", event_types)
        self.assertNotIn("after_agent", event_types)
        # Должны быть только legacy tool events
        self.assertIn("before_tool", event_types)
        self.assertIn("after_tool", event_types)

    def test_11_context_progress_callback_restored_on_success(self):
        """11. Исходный progress_callback в AgentContext восстанавливается при успехе."""
        initial_captured = []
        def initial_cb(step, **extra):
            initial_captured.append(step)

        ctx = AgentContext(task="создай задачу Купить чай", progress_callback=initial_cb)
        self.assertIs(ctx.progress_callback, initial_cb)

        route = self.router.route("создай задачу Купить чай")
        result = self.executor.execute(route, "создай задачу Купить чай", context=ctx)

        self.assertTrue(result.success)
        # Исходный callback был вызван во время работы агента
        self.assertGreaterEqual(len(initial_captured), 1)
        self.assertIn("Создаю задачу", initial_captured[0])

        # action_observer также получил события
        progress_events = [e[1] for e in self.events if e[0] == "agent_progress"]
        self.assertGreaterEqual(len(progress_events), 1)

        # После завершения исходный callback остался восстановленным
        self.assertIs(ctx.progress_callback, initial_cb)

    def test_12_context_progress_callback_restored_on_failure(self):
        """12. Исходный progress_callback в AgentContext восстанавливается при success=False."""
        class FailingAgent(BaseAgent):
            name = "failing"
            display_name = "Ошибочный агент"
            capabilities = ["fail_action"]

            def execute(self, task, context=None, **kwargs):
                if context and hasattr(context, "report_progress"):
                    context.report_progress("Начинаю действие...")
                return AgentResult.fail(error="Запланированная ошибка")

        failing_agent = FailingAgent()
        initial_captured = []
        def initial_cb(step, **extra):
            initial_captured.append(step)

        ctx = AgentContext(task="сломайся", progress_callback=initial_cb)
        res = self.executor.execute(failing_agent, "сломайся", context=ctx)

        self.assertFalse(res.success)
        self.assertIn("Начинаю действие...", initial_captured)
        self.assertIs(ctx.progress_callback, initial_cb)

    def test_13_context_progress_callback_restored_on_exception(self):
        """13. Исходный progress_callback в AgentContext восстанавливается при исключении агента."""
        class CrashAgent(BaseAgent):
            name = "crash"
            display_name = "Аварийный агент"
            capabilities = ["crash_action"]

            def execute(self, task, context=None, **kwargs):
                if context and hasattr(context, "report_progress"):
                    context.report_progress("Шаг перед падением")
                raise RuntimeError("Аварийное прерывание!")

        crash_agent = CrashAgent()
        initial_captured = []
        def initial_cb(step, **extra):
            initial_captured.append(step)

        ctx = AgentContext(task="упади", progress_callback=initial_cb)
        res = self.executor.execute(crash_agent, "упади", context=ctx)

        self.assertFalse(res.success)
        self.assertIn("Шаг перед падением", initial_captured)
        self.assertIs(ctx.progress_callback, initial_cb)

    def test_14_context_without_initial_callback_cleans_up_on_finish(self):
        """14. Если callback изначально был None, после завершения контекст очищается (не остаётся замыкания)."""
        ctx = AgentContext(task="создай задачу Починить кран")
        self.assertIsNone(ctx.progress_callback)

        route = self.router.route("создай задачу Починить кран")
        result = self.executor.execute(route, "создай задачу Починить кран", context=ctx)

        self.assertTrue(result.success)
        self.assertIsNone(ctx.progress_callback)


if __name__ == "__main__":
    unittest.main()
