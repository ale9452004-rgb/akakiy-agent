"""
Тесты для Task Executor v2 (исполнение TaskPlan, TeamworkPipeline, зависимости, артефакты, stop_on_error).
"""

import unittest
from tools.planner import PlanStep, TaskPlan
from tools.plan_executor import PlanExecutor
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.agents.registry import get_agent_registry, reset_agent_registry
from tools.agents.echo import EchoAgent
from tools.summary import format_task_summary


class FailingSubAgent(EchoAgent):
    """Тестовый субагент, гарантированно возвращающий ошибку."""

    name = "failing_agent"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult.fail(
            error="Намеренная ошибка тестового субагента",
            message="Сбой выполнения тестового агента"
        )


class ArtifactSubAgent(EchoAgent):
    """Тестовый субагент, генерирующий специализированный артефакт."""

    name = "artifact_agent"

    def run(self, context: AgentContext) -> AgentResult:
        art = Artifact.from_text(
            content=f"Report content for task: {context.task}",
            name=f"artifact_{context.task}.txt",
            type=ArtifactType.TEXT
        )
        return AgentResult.ok(
            message=f"Создан артефакт для {context.task}",
            artifacts=[art],
            created_files=[art.path] if art.path else []
        )


class TestTaskExecutorV2(unittest.TestCase):
    """Набор тестов для Task Executor v2."""

    def setUp(self):
        reset_agent_registry()
        self.registry = get_agent_registry()
        self.registry.register(EchoAgent())
        self.registry.register(FailingSubAgent())
        self.registry.register(ArtifactSubAgent())

        class MockAgent:
            def __init__(self, registry):
                self.agent_registry = registry

        self.mock_agent = MockAgent(self.registry)
        self.executor = PlanExecutor(agent=self.mock_agent)

    def tearDown(self):
        reset_agent_registry()

    # -------------------------------------------------------------------------
    # 1. Приём TaskPlan и legacy-планов
    # -------------------------------------------------------------------------

    def test_execute_accepts_task_plan_instance(self):
        """PlanExecutor успешно принимает объект TaskPlan."""
        plan = TaskPlan(
            goal="Тест экземпляра TaskPlan",
            steps=[
                PlanStep(id="s1", action="echo", description="Эхо шаг", task="Привет мир"),
            ],
        )
        res = self.executor.execute(plan)
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["subagent"], "echo")

    def test_execute_accepts_legacy_dict(self):
        """PlanExecutor успешно принимает классический словарь плана."""
        legacy_plan = {
            "goal": "План в виде словаря",
            "steps": [
                {"id": 1, "action": "echo", "description": "Словарный шаг", "task": "Тест dict"},
            ],
        }
        res = self.executor.execute(legacy_plan)
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertEqual(res["results"][0]["subagent"], "echo")

    def test_execute_accepts_list_of_steps(self):
        """PlanExecutor успешно принимает список шагов."""
        steps_list = [
            PlanStep(id="s1", action="echo", description="Шаг 1", task="Эхо из списка"),
        ]
        res = self.executor.execute(steps_list)
        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertEqual(len(res["results"]), 1)

    def test_execute_rejects_invalid_plan_types(self):
        """PlanExecutor возвращает fail при некорректном типе плана."""
        res_str = self.executor.execute("строка вместо плана")
        self.assertFalse(res_str.success)
        self.assertIn("некорректный формат", res_str.message)

        res_none = self.executor.execute(None)
        self.assertFalse(res_none.success)

    # -------------------------------------------------------------------------
    # 2. Валидация TaskPlan перед запуском
    # -------------------------------------------------------------------------

    def test_validation_fails_on_empty_plan(self):
        """Валидация прерывает исполнение пустого плана."""
        plan = TaskPlan(goal="Пустой", steps=[])
        res = self.executor.execute(plan)
        self.assertFalse(res.success)
        self.assertIn("отсутствуют шаги", res.message)

    def test_validation_fails_on_duplicate_step_ids(self):
        """Валидация прерывает исполнение плана с дублирующимися ID шагов."""
        plan = TaskPlan(
            goal="Дубликаты",
            steps=[
                PlanStep(id="s1", action="echo", description="Шаг 1"),
                PlanStep(id="s1", action="echo", description="Шаг 2 с тем же ID"),
            ],
        )
        res = self.executor.execute(plan)
        self.assertFalse(res.success)
        self.assertIn("Дублирующийся идентификатор", res.message)

    def test_validation_fails_on_cyclic_dependencies(self):
        """Валидация обнаруживает циклические зависимости до старта шагов."""
        plan = TaskPlan(
            goal="Цикл",
            steps=[
                PlanStep(id="s1", action="echo", description="A", depends_on=["s2"]),
                PlanStep(id="s2", action="echo", description="B", depends_on=["s1"]),
            ],
        )
        res = self.executor.execute(plan)
        self.assertFalse(res.success)
        self.assertIn("циклическая зависимость", res.message.lower())

    def test_validation_fails_on_missing_dependency(self):
        """Валидация обнаруживает ссылки на несуществующие шаги."""
        plan = TaskPlan(
            goal="Несуществующий шаг",
            steps=[
                PlanStep(id="s1", action="echo", description="A", depends_on=["s_missing"]),
            ],
        )
        res = self.executor.execute(plan)
        self.assertFalse(res.success)
        self.assertIn("несуществующую зависимость", res.message)

    # -------------------------------------------------------------------------
    # 3. Исполнение в порядке зависимостей (Topological Sorting)
    # -------------------------------------------------------------------------

    def test_execution_order_respects_dependencies(self):
        """Шаги плана исполняются в порядке графа зависимостей, а не исходного списка."""
        # s3 зависит от s2, s2 зависит от s1.
        # Входной список нарочно перетасован: [s3, s1, s2]
        plan = TaskPlan(
            goal="Топологический конвейер",
            steps=[
                PlanStep(id="s3", action="echo", description="Третий", task="Шаг 3", depends_on=["s2"]),
                PlanStep(id="s1", action="echo", description="Первый", task="Шаг 1"),
                PlanStep(id="s2", action="echo", description="Второй", task="Шаг 2", depends_on=["s1"]),
            ],
        )
        res = self.executor.execute(plan)
        self.assertTrue(res.success)
        executed_ids = [step["id"] for step in res.data["history"]]
        self.assertEqual(executed_ids, ["s1", "s2", "s3"])

    # -------------------------------------------------------------------------
    # 4. Делегирование Sub-Agent шагов в TeamworkPipeline
    # -------------------------------------------------------------------------

    def test_subagent_steps_executed_via_teamwork_pipeline(self):
        """Sub-Agent шаги выполняются через TeamworkPipeline с изоляцией контекста."""
        plan = TaskPlan(
            goal="Цепочка субагентов",
            steps=[
                PlanStep(id="echo_a", action="echo", description="Первое эхо", task="Привет от A"),
                PlanStep(id="echo_b", action="echo", description="Второе эхо", task="Привет от B", depends_on=["echo_a"]),
            ],
        )
        res = self.executor.execute(plan)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data["history"]), 2)
        self.assertEqual(res.data["history"][0]["subagent"], "echo")
        self.assertEqual(res.data["history"][1]["subagent"], "echo")

    # -------------------------------------------------------------------------
    # 5. Накопление результатов и артефактов в AgentContext и AgentResult
    # -------------------------------------------------------------------------

    def test_artifacts_and_files_aggregation(self):
        """Итоговый AgentResult агрегирует артефакты от всех шагов плана."""
        plan = TaskPlan(
            goal="Генерация артефактов",
            steps=[
                PlanStep(id="art_1", action="artifact_agent", description="Артефакт 1", task="task_one"),
                PlanStep(id="art_2", action="artifact_agent", description="Артефакт 2", task="task_two", depends_on=["art_1"]),
            ],
        )
        res = self.executor.execute(plan)
        self.assertTrue(res.success)
        self.assertEqual(len(res.artifacts), 2)
        art_names = [a.name for a in res.artifacts]
        self.assertIn("artifact_task_one.txt", art_names)
        self.assertIn("artifact_task_two.txt", art_names)

    # -------------------------------------------------------------------------
    # 6. Обработка ошибок и stop_on_error
    # -------------------------------------------------------------------------

    def test_stop_on_error_halts_execution(self):
        """При stop_on_error=True сбой на промежуточном шаге останавливает конвейер."""
        plan = TaskPlan(
            goal="Сбойный план с остановкой",
            steps=[
                PlanStep(id="step_1", action="echo", description="Успешный 1", task="Старт"),
                PlanStep(id="step_2", action="failing_agent", description="Сбойный 2", task="Упадёт", depends_on=["step_1"]),
                PlanStep(id="step_3", action="echo", description="Не должен выполниться", task="Хвост", depends_on=["step_2"]),
            ],
        )
        res = self.executor.execute(plan, stop_on_error=True)
        self.assertFalse(res.success)
        self.assertEqual(len(res.data["history"]), 2)  # step_1 и step_2
        self.assertEqual(res.data["failed_step"], "step_2")
        self.assertIn("step_2", res.message)

    def test_continue_on_error_executes_all_steps(self):
        """При stop_on_error=False исполнение продолжается после сбоя."""
        plan = TaskPlan(
            goal="Сбойный план без остановки",
            steps=[
                PlanStep(id="step_1", action="echo", description="Успешный 1", task="Старт"),
                PlanStep(id="step_2", action="failing_agent", description="Сбойный 2", task="Упадёт"),
                PlanStep(id="step_3", action="echo", description="Успешный 3", task="Хвост"),
            ],
        )
        res = self.executor.execute(plan, stop_on_error=False)
        self.assertFalse(res.success)
        self.assertEqual(len(res.data["history"]), 3)
        self.assertEqual(res.data["completed_steps"], 2)

    # -------------------------------------------------------------------------
    # 7. Обратная совместимость PlanExecutor API
    # -------------------------------------------------------------------------

    def test_backward_compatibility_dict_access_and_summary(self):
        """Проверка 100% совместимости с dict-like доступом и format_task_summary."""
        plan = TaskPlan(
            goal="План для сводки",
            steps=[
                PlanStep(id="s1", action="echo", description="Первый шаг", task="Привет"),
            ],
        )
        res = self.executor.execute(plan)

        # 1. Проверка операторов доступа
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "План выполнен успешно.")
        self.assertIn("results", res)
        self.assertEqual(len(res.get("results")), 1)

        # 2. Проверка модификации через квадратные скобки (res["summary"] = ...)
        summary_text = format_task_summary(plan.to_dict(), res)
        res["summary"] = summary_text
        self.assertEqual(res["summary"], summary_text)
        self.assertIn("summary", res)
        self.assertIn("План выполнен успешно.", summary_text)


if __name__ == "__main__":
    unittest.main()
