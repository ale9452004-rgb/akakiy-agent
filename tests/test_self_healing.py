"""
Тесты контролируемого механизма самовосстановления и обработки ошибок (Self-Healing).
Этап №15.
"""

import unittest
from unittest.mock import MagicMock, patch

from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.registry import AgentRegistry, reset_agent_registry
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.planner import PlanStep, TaskPlan
from tools.plan_executor import PlanExecutor
from tools.self_healing import (
    ErrorCategory,
    ErrorClassifier,
    ErrorContext,
    SelfHealingManager
)


class DummyRecoverableAgent(SubAgent):
    """Тестовый субагент с контролируемым поведением сбоев и восстановления."""

    def __init__(self, name: str = "recoverable_agent", fail_times: int = 1, err_msg: str = "Connection timeout"):
        super().__init__(name=name, description="Test recoverable agent")
        self.fail_times = fail_times
        self.err_msg = err_msg
        self.call_count = 0

    def run(self, context: AgentContext) -> AgentResult:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            return AgentResult.fail(
                error=self.err_msg,
                message=f"Ошибка в {self.name}: {self.err_msg}",
                data={"fatal": False}
            )
        art = Artifact.from_text(f"Recovered output call #{self.call_count}", name="recovered.txt")
        return AgentResult.ok(
            message=f"Успех после {self.call_count} вызовов",
            created_files=["data/recovered.txt"],
            artifacts=[art],
            data={"recovered": True, "call_count": self.call_count}
        )


class TestSelfHealingComponents(unittest.TestCase):
    """Тестирование отдельных компонентов Self-Healing: ErrorContext, ErrorClassifier, SelfHealingManager."""

    def setUp(self):
        self.classifier = ErrorClassifier()

    def test_error_context_serialization(self):
        """Проверка структуры, сериализации и десериализации ErrorContext."""
        ctx = ErrorContext(
            step_id="step_1",
            action="read",
            error="File locked by process",
            message="Read failed",
            target="test.txt",
            attempt=1,
            max_attempts=3,
            is_recoverable=True,
            category=ErrorCategory.FILE_LOCKED,
            strategy="retry",
            metadata={"hint": "wait and retry"}
        )
        self.assertEqual(ctx.step_id, "step_1")
        self.assertEqual(ctx.action, "read")
        self.assertTrue(ctx.is_recoverable)
        self.assertEqual(ctx.category, ErrorCategory.FILE_LOCKED)
        self.assertEqual(ctx.strategy, "retry")
        self.assertIn("<ErrorContext", repr(ctx))

        d = ctx.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["step_id"], "step_1")
        self.assertEqual(d["target"], "test.txt")
        self.assertEqual(d["category"], ErrorCategory.FILE_LOCKED)

        restored = ErrorContext.from_dict(d)
        self.assertEqual(restored.step_id, ctx.step_id)
        self.assertEqual(restored.action, ctx.action)
        self.assertEqual(restored.is_recoverable, ctx.is_recoverable)
        self.assertEqual(restored.category, ctx.category)

    def test_classify_user_cancellation(self):
        """Отмена пользователем должна классифицироваться как non-recoverable USER_CANCELLED."""
        step = {"id": 1, "action": "command", "command": "run"}
        res = {"success": False, "message": "Действие отменено пользователем", "error": "отменил"}
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertFalse(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.USER_CANCELLED)
        self.assertEqual(err_ctx.strategy, "abort")

    def test_classify_security_violation(self):
        """Нарушения безопасности (path traversal) классифицируются как non-recoverable SECURITY_VIOLATION."""
        step = {"id": 2, "action": "read", "target": "../../../secret"}
        res = {"success": False, "error": "Path traversal detected: доступ за пределы рабочей директории запрещен"}
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertFalse(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.SECURITY_VIOLATION)
        self.assertEqual(err_ctx.strategy, "abort")

    def test_classify_unsupported_action_or_missing_params(self):
        """Неизвестные действия или отсутствующие параметры классифицируются как non-recoverable UNSUPPORTED."""
        step = {"id": 3, "action": "unknown_action"}
        res = {"success": False, "message": "Неизвестное действие: unknown_action"}
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertFalse(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.UNSUPPORTED)
        self.assertEqual(err_ctx.strategy, "abort")

    def test_classify_file_locked(self):
        """Блокировка файла (PermissionError, file locked) классифицируется как recoverable FILE_LOCKED."""
        step = {"id": 4, "action": "read", "target": "data.bin"}
        res = {"success": False, "error": "PermissionError: The process cannot access the file because it is being used by another process."}
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertTrue(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.FILE_LOCKED)
        self.assertEqual(err_ctx.strategy, "retry")

    def test_classify_transient_network_or_busy(self):
        """Временные сетевые сбои и таймауты классифицируются как recoverable TRANSIENT."""
        step = {"id": 5, "action": "subagent", "subagent": "research"}
        res = AgentResult.fail(error="Connection reset by peer: timeout waiting for response")
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertTrue(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.TRANSIENT)
        self.assertEqual(err_ctx.strategy, "retry")

    def test_classify_resource_busy(self):
        """Занятость VRAM/GPU классифицируется как recoverable RESOURCE_BUSY."""
        step = {"id": 6, "action": "image"}
        res = {"success": False, "error": "CUDA out of memory; resource busy"}
        err_ctx = self.classifier.classify(step, res, attempt=1, max_attempts=2)

        self.assertTrue(err_ctx.is_recoverable)
        self.assertEqual(err_ctx.category, ErrorCategory.RESOURCE_BUSY)
        self.assertEqual(err_ctx.strategy, "retry")

    def test_classify_explicit_flags(self):
        """Проверка явных флагов recoverable/retryable и fatal."""
        # Явный non-recoverable
        step_fatal = {"id": 7, "action": "custom", "metadata": {"recoverable": False}}
        res_fatal = {"success": False, "error": "Any error"}
        ctx_fatal = self.classifier.classify(step_fatal, res_fatal, attempt=1, max_attempts=2)
        self.assertFalse(ctx_fatal.is_recoverable)
        self.assertEqual(ctx_fatal.category, ErrorCategory.FATAL)

        # Явный retryable
        step_retry = {"id": 8, "action": "custom", "metadata": {"retryable": True}}
        res_retry = {"success": False, "error": "Custom unclassified failure"}
        ctx_retry = self.classifier.classify(step_retry, res_retry, attempt=1, max_attempts=2)
        self.assertTrue(ctx_retry.is_recoverable)
        self.assertEqual(ctx_retry.strategy, "retry")

    def test_classify_attempt_exhausted(self):
        """При достижении max_attempts ошибка классифицируется как EXHAUSTED и non-recoverable."""
        step = {"id": 9, "action": "search", "query": "test"}
        res = {"success": False, "error": "Connection timeout"}
        ctx = self.classifier.classify(step, res, attempt=2, max_attempts=2)

        self.assertFalse(ctx.is_recoverable)
        self.assertEqual(ctx.category, ErrorCategory.EXHAUSTED)
        self.assertEqual(ctx.strategy, "exhausted")

    def test_agent_context_recovery_history(self):
        """Проверка записи и сохранения recovery_history в AgentContext."""
        ctx = AgentContext(task="Test recovery context")
        self.assertEqual(ctx.recovery_history, [])

        ctx.record_recovery_attempt({
            "step_id": 1,
            "action": "read",
            "attempt": 1,
            "category": "file_locked"
        })
        self.assertEqual(len(ctx.recovery_history), 1)
        self.assertEqual(ctx.recovery_history[0]["step_id"], 1)

        d = ctx.to_dict()
        self.assertIn("recovery_history", d)
        self.assertEqual(len(d["recovery_history"]), 1)

        restored = AgentContext.from_dict(d)
        self.assertEqual(len(restored.recovery_history), 1)
        self.assertEqual(restored.recovery_history[0]["category"], "file_locked")


class TestPlanExecutorSelfHealing(unittest.TestCase):
    """Тестирование интеграции Self-Healing в Task Executor v2."""

    def setUp(self):
        reset_agent_registry()
        self.registry = AgentRegistry()

    def test_step_successful_on_first_try(self):
        """Если шаг сразу успешен, попыток восстановления не производится."""
        executor = PlanExecutor(stop_on_error=True, max_retries=2)
        plan = TaskPlan(
            goal="Test successful step",
            steps=[
                PlanStep(id=1, action="search", query="Akakiy", description="Search project")
            ]
        )

        with patch("tools.plan_executor.dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"success": True, "files": ["main.py"]}
            res = executor.execute(plan)

        self.assertTrue(res.success)
        self.assertEqual(res.data["results"][0]["attempts"], 1)
        self.assertFalse(res.data["results"][0]["recovered"])
        self.assertEqual(res.data["results"][0]["recovery_attempts"], 0)
        self.assertFalse(res.was_recovered)
        self.assertEqual(res.recovery_history, [])

    def test_tool_step_recovers_on_second_attempt(self):
        """Шаг инструмента падает с recoverable ошибкой на 1-й попытке и успешно восстанавливается на 2-й."""
        executor = PlanExecutor(stop_on_error=True, max_retries=2)
        plan = TaskPlan(
            goal="Test recovery on retry",
            steps=[
                PlanStep(id=1, action="read", target="config.json", description="Read config")
            ]
        )

        call_count = 0

        def fake_dispatch(name, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "success": False,
                    "error": "The process cannot access the file because it is being used by another process."
                }
            return {
                "success": True,
                "result": {"content": "{\"key\": \"val\"}"}
            }

        with patch("tools.plan_executor.dispatch", side_effect=fake_dispatch):
            res = executor.execute(plan)

        self.assertTrue(res.success)
        self.assertEqual(call_count, 2)
        step_res = res.data["results"][0]
        self.assertTrue(step_res["recovered"])
        self.assertEqual(step_res["attempts"], 2)
        self.assertEqual(step_res["recovery_attempts"], 1)
        self.assertTrue(res.was_recovered)
        self.assertEqual(len(res.recovery_history), 1)
        self.assertEqual(res.recovery_history[0]["category"], ErrorCategory.FILE_LOCKED)

    def test_subagent_step_recovers_via_teamwork_pipeline(self):
        """Шаг SubAgent через TeamworkPipeline падает на 1-й попытке (timeout) и восстанавливается на 2-й."""
        agent = DummyRecoverableAgent(name="recoverable_agent", fail_times=1, err_msg="Server connection timed out")
        self.registry.register(agent)

        mock_main_agent = MagicMock()
        mock_main_agent.agent_registry = self.registry
        executor = PlanExecutor(agent=mock_main_agent, stop_on_error=True, max_retries=2)

        plan = TaskPlan(
            goal="Test subagent recovery",
            steps=[
                PlanStep(id=1, action="subagent", subagent="recoverable_agent", description="Run recoverable")
            ]
        )

        res = executor.execute(plan)
        self.assertTrue(res.success)
        self.assertEqual(agent.call_count, 2)
        self.assertTrue(res.was_recovered)
        self.assertTrue(res.has_artifacts)
        self.assertEqual(res.primary_artifact.name, "recovered.txt")
        self.assertEqual(len(res.recovery_history), 1)
        self.assertEqual(res.recovery_history[0]["category"], ErrorCategory.TRANSIENT)

    def test_retries_exhausted_with_stop_on_error(self):
        """Если лимит попыток исчерпан и stop_on_error=True, выполнение останавливается с полной историей."""
        executor = PlanExecutor(stop_on_error=True, max_retries=1)
        plan = TaskPlan(
            goal="Test exhausted retries",
            steps=[
                PlanStep(id=1, action="read", target="missing.txt", metadata={"retryable": True}),
                PlanStep(id=2, action="search", query="should not run", depends_on=[1])
            ]
        )

        with patch("tools.plan_executor.dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"success": False, "error": "Temporary failure on device"}
            res = executor.execute(plan)

        self.assertFalse(res.success)
        self.assertEqual(len(res.data["results"]), 1)
        step_res = res.data["results"][0]
        self.assertEqual(step_res["attempts"], 2)  # 1 исходная + 1 retry
        self.assertFalse(step_res["recovered"])
        self.assertEqual(len(res.recovery_history), 2)  # 2 попытки зафиксированы
        self.assertEqual(res.data["failed_step"], 1)

    def test_retries_exhausted_with_continue_on_error(self):
        """Если лимит исчерпан и stop_on_error=False, следующие независимые шаги выполняются."""
        executor = PlanExecutor(stop_on_error=False, max_retries=1)
        plan = TaskPlan(
            goal="Test continue on error after exhausted retries",
            steps=[
                PlanStep(id=1, action="read", target="busy.txt", metadata={"retryable": True}),
                PlanStep(id=2, action="search", query="independent search")
            ]
        )

        def fake_dispatch(name, **kwargs):
            if name == "read_file":
                return {"success": False, "error": "Resource busy"}
            return {"success": True, "files": ["result.txt"]}

        with patch("tools.plan_executor.dispatch", side_effect=fake_dispatch):
            res = executor.execute(plan)

        self.assertFalse(res.success)  # Общий статус - fail
        self.assertEqual(len(res.data["results"]), 2)  # Но оба шага попытались выполниться
        self.assertFalse(res.data["results"][0]["success"])
        self.assertTrue(res.data["results"][1]["success"])
        self.assertEqual(len(res.recovery_history), 2)

    def test_non_recoverable_error_does_not_retry(self):
        """Невосстановимые ошибки (отмена пользователем, path traversal) не делают повторных попыток."""
        executor = PlanExecutor(stop_on_error=True, max_retries=2)
        plan = TaskPlan(
            goal="Test non-recoverable cancel",
            steps=[
                PlanStep(id=1, action="command", command="dangerous_op")
            ]
        )

        call_count = 0

        def fake_dispatch(name, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"success": False, "message": "Действие отменено пользователем."}

        with patch("tools.plan_executor.dispatch", side_effect=fake_dispatch):
            res = executor.execute(plan)

        self.assertFalse(res.success)
        self.assertEqual(call_count, 1)  # Ровно 1 попытка, без retry!
        self.assertEqual(res.data["results"][0]["attempts"], 1)
        self.assertEqual(len(res.recovery_history), 1)
        self.assertEqual(res.recovery_history[0]["category"], ErrorCategory.USER_CANCELLED)

    def test_global_max_total_recoveries_guard(self):
        """Глобальный лимит max_total_recoveries предотвращает бесконечные циклы восстановления между шагами."""
        executor = PlanExecutor(stop_on_error=False, max_retries=2, max_total_recoveries=2)
        plan = TaskPlan(
            goal="Test global recoveries limit",
            steps=[
                PlanStep(id=1, action="read", target="f1.txt", metadata={"retryable": True}),
                PlanStep(id=2, action="read", target="f2.txt", metadata={"retryable": True}),
                PlanStep(id=3, action="read", target="f3.txt", metadata={"retryable": True}),
            ]
        )

        with patch("tools.plan_executor.dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"success": False, "error": "Temporary network timeout"}
            res = executor.execute(plan)

        self.assertFalse(res.success)
        # Шаг 1: попытка 1 (fail) -> retry 1 (потрачен 1 глобальный recovery) -> попытка 2 (fail) -> exhausted
        # Шаг 2: попытка 1 (fail) -> retry 2 (потрачен 2 глобальный recovery) -> попытка 2 (fail) -> exhausted
        # Шаг 3: попытка 1 (fail) -> глобальный лимит (2) исчерпан! Retry не выполняется!
        step3_res = res.data["results"][2]
        self.assertEqual(step3_res["attempts"], 1)

    def test_disable_self_healing(self):
        """При enable_self_healing=False или max_retries=0 повторных попыток не производится."""
        executor = PlanExecutor(stop_on_error=True, enable_self_healing=False)
        plan = TaskPlan(
            goal="Test disabled self-healing",
            steps=[
                PlanStep(id=1, action="read", target="busy.txt", metadata={"retryable": True})
            ]
        )

        call_count = 0

        def fake_dispatch(name, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"success": False, "error": "Resource temporarily busy"}

        with patch("tools.plan_executor.dispatch", side_effect=fake_dispatch):
            res = executor.execute(plan)

        self.assertFalse(res.success)
        self.assertEqual(call_count, 1)
        self.assertEqual(res.data["results"][0]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
