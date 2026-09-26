"""
Тесты для Task Planner v2 (структурированный план, граф зависимостей и интеграция с Teamwork).
"""

import unittest
from tools.planner import PlanStep, TaskPlan, Planner
from tools.teamwork import PipelineStep, TeamworkPipeline
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.agents.registry import get_agent_registry, reset_agent_registry
from tools.agents.echo import EchoAgent
from tools.plan_executor import PlanExecutor


class TestTaskPlannerV2(unittest.TestCase):
    """Набор тестов для Task Planner v2."""

    def setUp(self):
        reset_agent_registry()
        self.registry = get_agent_registry()
        self.registry.register(EchoAgent())

    def tearDown(self):
        reset_agent_registry()

    # -------------------------------------------------------------------------
    # 1. PlanStep tests
    # -------------------------------------------------------------------------

    def test_plan_step_creation_and_dict_access(self):
        """Проверка создания PlanStep и dict-like интерфейса для обратной совместимости."""
        step = PlanStep(
            id="step_1",
            action="research",
            description="Собрать данные",
            details="Исследовать тему ИИ",
            depends_on=[],
            subagent="research",
            task="Изучить новые подходы",
            metadata={"priority": "high"},
        )

        self.assertEqual(step.id, "step_1")
        self.assertEqual(step.action, "research")
        self.assertEqual(step.description, "Собрать данные")
        self.assertEqual(step.subagent, "research")
        self.assertEqual(step.metadata["priority"], "high")

        # Dict-like access
        self.assertEqual(step["id"], "step_1")
        self.assertEqual(step["action"], "research")
        self.assertEqual(step.get("description"), "Собрать данные")
        self.assertIn("details", step)
        self.assertIsNone(step.get("non_existent"))

    def test_plan_step_serialization(self):
        """Проверка сериализации to_dict и from_dict."""
        step = PlanStep(
            id="s1",
            action="coding",
            description="Изменить функцию",
            target="app.py",
            depends_on=["s0"],
            files=["app.py"],
            metadata={"key": "val"},
        )
        d = step.to_dict()
        self.assertEqual(d["id"], "s1")
        self.assertEqual(d["target"], "app.py")
        self.assertEqual(d["depends_on"], ["s0"])

        restored = PlanStep.from_dict(d)
        self.assertEqual(restored.id, step.id)
        self.assertEqual(restored.action, step.action)
        self.assertEqual(restored.target, step.target)
        self.assertEqual(restored.depends_on, ["s0"])
        self.assertEqual(restored.files, ["app.py"])

    def test_plan_step_to_pipeline_step(self):
        """Проверка преобразования PlanStep в PipelineStep."""
        # 1. Явный subagent
        step1 = PlanStep(
            id="s1",
            action="custom_action",
            description="Шаг 1",
            subagent="echo",
            task="Сказать привет",
        )
        p1 = step1.to_pipeline_step(registry=self.registry)
        self.assertEqual(p1.agent_name, "echo")
        self.assertEqual(p1.step_id, "s1")
        self.assertEqual(p1.task, "Сказать привет")

        # 2. Action совпадает с зарегистрированным субагентом
        step2 = PlanStep(
            id="s2",
            action="echo",
            description="Шаг 2",
            details="Детали эхо",
        )
        p2 = step2.to_pipeline_step(registry=self.registry)
        self.assertEqual(p2.agent_name, "echo")
        self.assertEqual(p2.step_id, "s2")
        self.assertEqual(p2.task, "Детали эхо")

        # 3. action не субагент, а файловое действие
        step3 = PlanStep(
            id="s3",
            action="search",
            description="Поиск файлов",
            query="*.py",
        )
        p3 = step3.to_pipeline_step(registry=self.registry)
        self.assertEqual(p3.agent_name, "file")
        self.assertEqual(p3.step_id, "s3")
        self.assertEqual(p3.metadata["query"], "*.py")

    # -------------------------------------------------------------------------
    # 2. TaskPlan validation tests
    # -------------------------------------------------------------------------

    def test_plan_validation_valid(self):
        """Корректный план успешно проходит валидацию."""
        plan = TaskPlan(
            goal="Исследовать и подготовить отчёт",
            steps=[
                PlanStep(id="s1", action="search", description="Найти файлы", query="*.py"),
                PlanStep(id="s2", action="echo", description="Эхо результат", depends_on=["s1"]),
            ],
        )
        is_valid, err = plan.validate()
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_plan_validation_empty_steps(self):
        """План без шагов невалиден."""
        plan = TaskPlan(goal="Пустой план", steps=[])
        is_valid, err = plan.validate()
        self.assertFalse(is_valid)
        self.assertIn("отсутствуют шаги", err)

    def test_plan_validation_duplicate_ids(self):
        """Дублирующиеся ID шагов вызывают ошибку валидации."""
        plan = TaskPlan(
            goal="Дубликаты",
            steps=[
                PlanStep(id="step_1", action="echo", description="Первый"),
                PlanStep(id="step_1", action="echo", description="Второй"),
            ],
        )
        is_valid, err = plan.validate()
        self.assertFalse(is_valid)
        self.assertIn("Дублирующийся идентификатор", err)

    def test_plan_validation_missing_action_or_desc(self):
        """Отсутствие action или description вызывает ошибку."""
        step = PlanStep(id="s1", action="", description="")
        plan = TaskPlan(goal="Тест", steps=[step])
        is_valid, err = plan.validate()
        self.assertFalse(is_valid)
        self.assertTrue("не указано действие" in err or "отсутствует описание" in err)

    def test_plan_validation_action_requirements(self):
        """Валидация обязательных полей для специфических действий."""
        # search требует query
        p_search = TaskPlan(goal="G", steps=[PlanStep(id="s1", action="search", description="D")])
        self.assertFalse(p_search.validate()[0])

        # read / edit требует target
        p_read = TaskPlan(goal="G", steps=[PlanStep(id="s1", action="read", description="D")])
        self.assertFalse(p_read.validate()[0])

        p_edit = TaskPlan(goal="G", steps=[PlanStep(id="s1", action="edit", description="D")])
        self.assertFalse(p_edit.validate()[0])

        # command / git требует command
        p_cmd = TaskPlan(goal="G", steps=[PlanStep(id="s1", action="command", description="D")])
        self.assertFalse(p_cmd.validate()[0])

    def test_plan_validation_dependencies(self):
        """Проверка валидации зависимостей: самозависимость и несуществующие ID."""
        # Самозависимость
        p_self = TaskPlan(
            goal="G",
            steps=[PlanStep(id="s1", action="echo", description="D", depends_on=["s1"])],
        )
        is_valid, err = p_self.validate()
        self.assertFalse(is_valid)
        self.assertIn("зависит от самого себя", err)

        # Несуществующая зависимость
        p_missing = TaskPlan(
            goal="G",
            steps=[PlanStep(id="s1", action="echo", description="D", depends_on=["s_unknown"])],
        )
        is_valid, err = p_missing.validate()
        self.assertFalse(is_valid)
        self.assertIn("несуществующую зависимость", err)

    def test_plan_validation_cycle_detection(self):
        """Обнаружение циклических зависимостей в плане."""
        # Простой цикл A -> B -> A
        p_cycle = TaskPlan(
            goal="Цикл",
            steps=[
                PlanStep(id="A", action="echo", description="A", depends_on=["B"]),
                PlanStep(id="B", action="echo", description="B", depends_on=["A"]),
            ],
        )
        is_valid, err = p_cycle.validate()
        self.assertFalse(is_valid)
        self.assertIn("циклическая зависимость", err.lower())

        # Длинный цикл A -> B -> C -> A
        p_long_cycle = TaskPlan(
            goal="Длинный цикл",
            steps=[
                PlanStep(id="A", action="echo", description="A", depends_on=["C"]),
                PlanStep(id="B", action="echo", description="B", depends_on=["A"]),
                PlanStep(id="C", action="echo", description="C", depends_on=["B"]),
            ],
        )
        is_valid, err = p_long_cycle.validate()
        self.assertFalse(is_valid)
        self.assertIn("циклическая зависимость", err.lower())

    # -------------------------------------------------------------------------
    # 3. Topological sorting / Execution order
    # -------------------------------------------------------------------------

    def test_topological_sort_execution_order(self):
        """Шаги должны быть отсортированы с учётом зависимостей."""
        # Определение: C зависит от B, B зависит от A
        # Порядок в списке нарочно перемешан: [C, A, B]
        plan = TaskPlan(
            goal="Сортировка",
            steps=[
                PlanStep(id="C", action="echo", description="Step C", depends_on=["B"]),
                PlanStep(id="A", action="echo", description="Step A", depends_on=[]),
                PlanStep(id="B", action="echo", description="Step B", depends_on=["A"]),
            ],
        )
        order = plan.get_execution_order()
        ordered_ids = [s.id for s in order]
        self.assertEqual(ordered_ids, ["A", "B", "C"])

    def test_topological_sort_preserves_independent_order(self):
        """Для независимых шагов сохраняется исходный порядок объявления."""
        plan = TaskPlan(
            goal="Независимые шаги",
            steps=[
                PlanStep(id="s1", action="echo", description="1"),
                PlanStep(id="s2", action="echo", description="2"),
                PlanStep(id="s3", action="echo", description="3"),
            ],
        )
        order = plan.get_execution_order()
        self.assertEqual([s.id for s in order], ["s1", "s2", "s3"])

    # -------------------------------------------------------------------------
    # 4. Teamwork bridge (to_pipeline_steps, to_pipeline)
    # -------------------------------------------------------------------------

    def test_to_pipeline_steps_and_pipeline(self):
        """Преобразование TaskPlan в шаги Teamwork и создание TeamworkPipeline."""
        plan = TaskPlan(
            goal="Пайплайн из плана",
            steps=[
                PlanStep(id="s2", action="echo", description="Шаг 2", depends_on=["s1"]),
                PlanStep(id="s1", action="echo", description="Шаг 1"),
            ],
        )
        steps = plan.to_pipeline_steps(registry=self.registry)
        self.assertEqual(len(steps), 2)
        # s1 должен идти перед s2 из-за зависимости
        self.assertEqual(steps[0].step_id, "s1")
        self.assertEqual(steps[1].step_id, "s2")

        pipeline = plan.to_pipeline(registry=self.registry)
        self.assertIsInstance(pipeline, TeamworkPipeline)
        self.assertEqual(len(pipeline.steps), 2)

    def test_teamwork_pipeline_accepts_task_plan(self):
        """TeamworkPipeline принимает объект TaskPlan напрямую в конструктор."""
        plan = TaskPlan(
            goal="Прямой пайплайн",
            steps=[
                PlanStep(id="step_a", action="echo", description="A"),
                PlanStep(id="step_b", action="echo", description="B", depends_on=["step_a"]),
            ],
        )
        pipeline = TeamworkPipeline(steps=plan, registry=self.registry)
        self.assertEqual(len(pipeline.steps), 2)
        self.assertEqual(pipeline.steps[0].step_id, "step_a")
        self.assertEqual(pipeline.steps[1].step_id, "step_b")

    def test_pipeline_execution_from_task_plan(self):
        """Выполнение TeamworkPipeline, созданного из TaskPlan."""
        plan = TaskPlan(
            goal="Выполнить эхо-цепочку",
            steps=[
                PlanStep(id="echo_1", action="echo", description="Привет 1", task="Первый привет"),
                PlanStep(id="echo_2", action="echo", description="Привет 2", task="Второй привет", depends_on=["echo_1"]),
            ],
        )
        pipeline = plan.to_pipeline(registry=self.registry)
        result = pipeline.run(initial_task="Старт цепочки")

        self.assertTrue(result.success)
        self.assertIn("успешно выполнен", result.message.lower())
        self.assertEqual(len(result.data["history"]), 2)
        self.assertEqual(result.data["history"][0]["step_id"], "echo_1")
        self.assertEqual(result.data["history"][1]["step_id"], "echo_2")

    # -------------------------------------------------------------------------
    # 5. Planner class v2 methods
    # -------------------------------------------------------------------------

    def test_planner_create_structured_plan(self):
        """Проверка фабричного метода Planner.create_structured_plan."""
        planner = Planner()
        plan = planner.create_structured_plan(
            steps=[
                {"id": "s1", "action": "echo", "description": "Сказать привет"},
                {"id": "s2", "action": "search", "description": "Найти файлы", "query": "*.txt", "depends_on": ["s1"]},
            ],
            goal="Тестовая цель",
        )
        self.assertIsInstance(plan, TaskPlan)
        self.assertEqual(plan.goal, "Тестовая цель")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].id, "s1")
        self.assertEqual(plan.steps[1].depends_on, ["s1"])

        is_valid, err = planner.validate_plan(plan)
        self.assertTrue(is_valid)
        self.assertIsNone(err)

    def test_planner_to_pipeline_helper(self):
        """Проверка вспомогательных методов Planner.to_pipeline_steps и to_pipeline."""
        planner = Planner()
        plan = planner.create_structured_plan(
            steps=[
                {"id": "s1", "action": "echo", "description": "Эхо шаг"},
            ],
            goal="Цель",
        )
        steps = planner.to_pipeline_steps(plan, registry=self.registry)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].agent_name, "echo")

        pipeline = planner.to_pipeline(plan, registry=self.registry)
        self.assertIsInstance(pipeline, TeamworkPipeline)

    # -------------------------------------------------------------------------
    # 6. PlanExecutor with TaskPlan and SubAgents
    # -------------------------------------------------------------------------

    def test_plan_executor_with_task_plan_and_subagent(self):
        """PlanExecutor выполняет TaskPlan с subagent-шагами."""
        class MockAgent:
            def __init__(self, registry):
                self.agent_registry = registry

        mock_agent = MockAgent(self.registry)
        executor = PlanExecutor(agent=mock_agent)

        plan = TaskPlan(
            goal="Выполнить субагента через Executor",
            steps=[
                PlanStep(id="s1", action="echo", description="Эхо тест", task="Выполни тестовую задачу"),
            ],
        )

        res = executor.execute(plan)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["subagent"], "echo")
        self.assertTrue(res["results"][0]["success"])

    # -------------------------------------------------------------------------
    # 7. Backward compatibility
    # -------------------------------------------------------------------------

    def test_backward_compatibility_legacy_plan_dict(self):
        """Проверка обратной совместимости с классическими словарями планов."""
        legacy_plan = {
            "goal": "Старый план",
            "steps": [
                {"id": 1, "action": "search", "query": "test", "description": "Поиск"},
                {"id": 2, "action": "echo", "description": "Эхо", "subagent": "echo"},
            ],
            "expected_result": "Успех",
            "verification": "Проверка",
        }

        # TaskPlan.from_dict принимает legacy формат с int id
        plan = TaskPlan.from_dict(legacy_plan)
        self.assertEqual(plan.steps[0].id, 1)
        self.assertEqual(plan.steps[1].id, 2)
        is_valid, err = plan.validate()
        self.assertTrue(is_valid)

        # Planner._validate_plan работает с dict
        planner = Planner()
        self.assertTrue(planner._validate_plan(legacy_plan))

        # PlanExecutor принимает классический словарь
        class MockAgent:
            def __init__(self, registry):
                self.agent_registry = registry

        executor = PlanExecutor(agent=MockAgent(self.registry))
        res = executor.execute(legacy_plan)
        self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
