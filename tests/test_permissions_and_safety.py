"""
Тесты единого слоя разрешений и безопасности (Permissions & Safety Layer).
Проверяют:
1. Классификацию уровней риска (RiskLevel) и политик (SecurityPolicy).
2. Оценку инструментов: безопасные, умеренные, критические, контекстный анализ (перезапись файлов, опасные команды).
3. Блокировку защищенных файлов (.env, .git) и политику READ_ONLY.
4. Оценку Sub-Agent'ов (FileAgent, CodingAgent, ResearchAgent, PresentationAgent).
5. Интеграцию с Dispatcher и mock confirmation handler (одобрение, отмена, observer).
6. Интеграцию с TeamworkPipeline (проверка и отмена ДО выполнения опасного субагента).
7. Интеграцию с PlanExecutor (остановка плана при отмене пользователем).
8. Интеграцию с Agent.execute_subagent.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.permissions import (
    PermissionManager,
    RiskLevel,
    SecurityPolicy,
    PermissionAssessment,
    get_permission_manager,
    reset_permission_manager
)
from tools.dispatcher import (
    dispatch,
    set_confirmation_handler,
    get_confirmation_handler,
    get_confirmation_details_text
)
from tools.registry import get_tool_risk_level
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult
from tools.agents.registry import AgentRegistry
from tools.agents.echo import EchoAgent
from tools.agents.research import ResearchAgent
from tools.agents.file import FileAgent
from tools.agents.coding import CodingAgent
from tools.teamwork import TeamworkPipeline, PipelineStep
from tools.planner import TaskPlan, PlanStep
from tools.plan_executor import PlanExecutor
from tools.agent import Agent


class TestRiskLevelAndPolicy(unittest.TestCase):
    """1. Проверка моделей RiskLevel и SecurityPolicy."""

    def test_risk_level_ordering_and_helpers(self):
        self.assertTrue(RiskLevel.SAFE.is_safe())
        self.assertTrue(RiskLevel.LOW.is_safe())
        self.assertFalse(RiskLevel.MEDIUM.is_safe())
        self.assertTrue(RiskLevel.MEDIUM.is_dangerous())
        self.assertTrue(RiskLevel.HIGH.is_dangerous())
        self.assertTrue(RiskLevel.CRITICAL.is_dangerous())

        self.assertLess(RiskLevel.SAFE.rank, RiskLevel.LOW.rank)
        self.assertLess(RiskLevel.LOW.rank, RiskLevel.MEDIUM.rank)
        self.assertLess(RiskLevel.MEDIUM.rank, RiskLevel.HIGH.rank)
        self.assertLess(RiskLevel.HIGH.rank, RiskLevel.CRITICAL.rank)

    def test_security_policy_values(self):
        self.assertEqual(SecurityPolicy.NORMAL.value, "normal")
        self.assertEqual(SecurityPolicy.STRICT.value, "strict")
        self.assertEqual(SecurityPolicy.PERMISSIVE.value, "permissive")
        self.assertEqual(SecurityPolicy.READ_ONLY.value, "read_only")


class TestToolPermissionsAssessment(unittest.TestCase):
    """2. Оценка безопасности инструментов и контекстный анализ."""

    def setUp(self):
        reset_permission_manager()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mgr = PermissionManager(project_path=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()
        reset_permission_manager()

    def test_safe_read_only_tools(self):
        safe_tools = ["list_files", "find_file", "read_file", "search_files", "analyze_file", "git_status", "git_diff", "git_log", "daily_briefing"]
        for t in safe_tools:
            assessment = self.mgr.assess_tool(t)
            self.assertEqual(assessment.risk_level, RiskLevel.SAFE, f"Инструмент {t} должен быть SAFE")
            self.assertFalse(assessment.requires_confirmation)
            self.assertTrue(assessment.allowed)

    def test_low_risk_local_creations(self):
        low_tools = ["create_task", "create_reminder", "create_note", "create_list", "add_list_item", "remember"]
        for t in low_tools:
            assessment = self.mgr.assess_tool(t)
            self.assertEqual(assessment.risk_level, RiskLevel.LOW)
            self.assertFalse(assessment.requires_confirmation)  # в NORMAL не требует
            self.assertTrue(assessment.allowed)

        # В STRICT режиме LOW требует подтверждения
        self.mgr.set_policy(SecurityPolicy.STRICT)
        assessment = self.mgr.assess_tool("create_task")
        self.assertTrue(assessment.requires_confirmation)

    def test_medium_risk_mutations_and_deletions(self):
        assessment = self.mgr.assess_tool("edit_file", {"filename": "main.py", "old_text": "a", "new_text": "b"})
        self.assertEqual(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertTrue(assessment.requires_confirmation)

        assessment = self.mgr.assess_tool("git_commit", {"message": "feat: test"})
        self.assertEqual(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertTrue(assessment.requires_confirmation)

        assessment = self.mgr.assess_tool("delete_task", {"task_id": "1"})
        self.assertEqual(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertTrue(assessment.requires_confirmation)
        self.assertTrue(assessment.is_destructive)

    def test_high_risk_push_and_list_delete(self):
        assessment = self.mgr.assess_tool("git_push")
        self.assertEqual(assessment.risk_level, RiskLevel.HIGH)
        self.assertTrue(assessment.requires_confirmation)

        assessment = self.mgr.assess_tool("delete_list", {"name": "покупки"})
        self.assertEqual(assessment.risk_level, RiskLevel.HIGH)
        self.assertTrue(assessment.requires_confirmation)
        self.assertTrue(assessment.is_destructive)

    def test_contextual_write_file_new_vs_overwrite(self):
        # 1. Новый файл -> MEDIUM
        new_file = Path(self.temp_dir.name) / "new_module.py"
        assessment = self.mgr.assess_tool("write_file", {"filename": str(new_file), "content": "x = 1"})
        self.assertEqual(assessment.risk_level, RiskLevel.MEDIUM)
        self.assertFalse(assessment.is_destructive)
        self.assertIn("Создание нового файла", assessment.details)

        # 2. Файл существует -> HIGH (перезапись!)
        new_file.write_text("x = 0", encoding="utf-8")
        assessment2 = self.mgr.assess_tool("write_file", {"filename": str(new_file), "content": "x = 2"})
        self.assertEqual(assessment2.risk_level, RiskLevel.HIGH)
        self.assertTrue(assessment2.is_destructive)
        self.assertIn("перезаписан", assessment2.details.lower())

    def test_protected_files_blocked(self):
        for protected in [".env", ".env.production", "certs/server.pem", "id_rsa", ".git/config"]:
            assessment = self.mgr.assess_tool("write_file", {"filename": protected, "content": "secret"})
            self.assertFalse(assessment.allowed)
            self.assertEqual(assessment.risk_level, RiskLevel.CRITICAL)
            self.assertIn("защищённый", assessment.reason.lower())

    def test_contextual_powershell_commands(self):
        # 1. Безопасная проверочная команда -> SAFE
        assessment = self.mgr.assess_tool("run_command", {"command": "git status"})
        self.assertEqual(assessment.risk_level, RiskLevel.SAFE)
        self.assertFalse(assessment.requires_confirmation)

        assessment = self.mgr.assess_tool("run_command", {"command": "python -m unittest tests/test_security.py"})
        self.assertEqual(assessment.risk_level, RiskLevel.SAFE)

        # 2. Обычная команда PowerShell -> HIGH
        assessment = self.mgr.assess_tool("run_command", {"command": "Get-Process | Select-Object -First 5"})
        self.assertEqual(assessment.risk_level, RiskLevel.HIGH)
        self.assertTrue(assessment.requires_confirmation)

        # 3. Деструктивная системная команда -> CRITICAL
        assessment = self.mgr.assess_tool("run_command", {"command": "Remove-Item -Recurse -Force C:\\temp"})
        self.assertEqual(assessment.risk_level, RiskLevel.CRITICAL)
        self.assertTrue(assessment.is_destructive)
        self.assertIn("ВНИМАНИЕ", assessment.details)

        assessment2 = self.mgr.assess_tool("run_command", {"command": "git reset --hard HEAD~1"})
        self.assertEqual(assessment2.risk_level, RiskLevel.CRITICAL)

    def test_read_only_policy_blocks_mutations(self):
        self.mgr.set_policy(SecurityPolicy.READ_ONLY)

        # Read-only инструмент разрешён
        self.assertTrue(self.mgr.assess_tool("read_file", {"filename": "main.py"}).allowed)

        # Мутации и команды заблокированы
        self.assertFalse(self.mgr.assess_tool("write_file", {"filename": "a.txt", "content": "1"}).allowed)
        self.assertFalse(self.mgr.assess_tool("run_command", {"command": "dir"}).allowed)
        self.assertFalse(self.mgr.assess_tool("create_task", {"title": "Задача"}).allowed)


class TestSubAgentPermissionsAssessment(unittest.TestCase):
    """3. Оценка безопасности Sub-Agent действий."""

    def setUp(self):
        reset_permission_manager()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mgr = PermissionManager(project_path=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()
        reset_permission_manager()

    def test_echo_and_research_subagents_safe(self):
        ctx = AgentContext(task="Изучи архитектуру проекта")
        a_echo = self.mgr.assess_subagent("echo", context=ctx)
        self.assertEqual(a_echo.risk_level, RiskLevel.SAFE)
        self.assertFalse(a_echo.requires_confirmation)

        a_research = self.mgr.assess_subagent("research", context=ctx)
        self.assertEqual(a_research.risk_level, RiskLevel.SAFE)
        self.assertFalse(a_research.requires_confirmation)

    def test_artifact_generators_low_risk(self):
        ctx = AgentContext(task="Сделай презентацию о проекте")
        for ag in ["presentation", "document", "image"]:
            a = self.mgr.assess_subagent(ag, context=ctx)
            self.assertEqual(a.risk_level, RiskLevel.LOW)
            self.assertFalse(a.requires_confirmation)

    def test_file_agent_actions(self):
        # 1. Поиск / чтение -> SAFE
        ctx_read = AgentContext(task="Прочитай файл notes.txt", metadata={"action": "read", "filename": "notes.txt"})
        self.assertEqual(self.mgr.assess_subagent("file", context=ctx_read).risk_level, RiskLevel.SAFE)

        # 2. Создание нового файла -> MEDIUM
        ctx_create = AgentContext(task="Создай файл output.txt", metadata={"action": "create", "filename": "output.txt"})
        self.assertEqual(self.mgr.assess_subagent("file", context=ctx_create).risk_level, RiskLevel.MEDIUM)

        # 3. Перезапись существующего файла -> HIGH
        existing = Path(self.temp_dir.name) / "existing.txt"
        existing.write_text("old", encoding="utf-8")
        ctx_overwrite = AgentContext(task="Перезапиши existing.txt", metadata={"action": "create", "filename": str(existing)})
        a_over = self.mgr.assess_subagent("file", context=ctx_overwrite)
        self.assertEqual(a_over.risk_level, RiskLevel.HIGH)
        self.assertTrue(a_over.is_destructive)

        # 4. Перемещение -> HIGH
        ctx_move = AgentContext(task="Перемести a.txt в b.txt", metadata={"action": "move", "source": "a.txt", "destination": "b.txt"})
        self.assertEqual(self.mgr.assess_subagent("file", context=ctx_move).risk_level, RiskLevel.HIGH)

        # 5. Удаление -> CRITICAL и BLOCKED
        ctx_del = AgentContext(task="Удали файл notes.txt", metadata={"action": "delete", "filename": "notes.txt"})
        a_del = self.mgr.assess_subagent("file", context=ctx_del)
        self.assertFalse(a_del.allowed)
        self.assertEqual(a_del.risk_level, RiskLevel.CRITICAL)

    def test_coding_agent_actions(self):
        # 1. Анализ кода -> SAFE
        ctx_analyze = AgentContext(task="Проанализируй синтаксис в file.py", metadata={"mode": "analyze", "target_files": ["file.py"]})
        self.assertEqual(self.mgr.assess_subagent("coding", context=ctx_analyze).risk_level, RiskLevel.SAFE)

        # 2. Применение правок -> MEDIUM
        ctx_edit = AgentContext(
            task="Исправь опечатку в file.py",
            metadata={"edits": [{"file": "file.py", "old": "x", "new": "y"}]}
        )
        a_edit = self.mgr.assess_subagent("coding", context=ctx_edit)
        self.assertEqual(a_edit.risk_level, RiskLevel.MEDIUM)
        self.assertTrue(a_edit.requires_confirmation)


class TestDispatcherSecurityIntegration(unittest.TestCase):
    """4. Интеграция PermissionManager с tools/dispatcher.py."""

    def setUp(self):
        reset_permission_manager()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        set_confirmation_handler(None)
        reset_permission_manager()

    def test_dispatcher_safe_tool_no_prompt(self):
        res = dispatch("list_files")
        self.assertTrue(res.get("success"))

    def test_dispatcher_approved_confirmation(self):
        set_confirmation_handler(lambda tool, kwargs: True)
        res = dispatch("run_command", command="Get-Date")
        self.assertTrue(res.get("success"))

    def test_dispatcher_rejected_confirmation(self):
        set_confirmation_handler(lambda tool, kwargs: False)
        res = dispatch("run_command", command="Get-Date")
        self.assertFalse(res.get("success"))
        self.assertIn("отменил", res.get("error", "").lower())

    def test_dispatcher_blocked_protected_file(self):
        set_confirmation_handler(lambda tool, kwargs: True)
        res = dispatch("write_file", filename=".env", content="SECRET=123")
        self.assertFalse(res.get("success"))
        self.assertIn("заблокировано", res.get("error", "").lower())

    def test_get_confirmation_details_text_integration(self):
        details = get_confirmation_details_text("run_command", {"command": "git push"})
        self.assertIn("PowerShell", details)
        self.assertIn("git push", details)
        self.assertIn("HIGH", details)

    def test_get_tool_risk_level_helper(self):
        self.assertEqual(get_tool_risk_level("read_file"), "safe")
        self.assertEqual(get_tool_risk_level("edit_file"), "medium")
        self.assertEqual(get_tool_risk_level("git_push"), "high")


class TestPipelineAndPlanExecutorSecurity(unittest.TestCase):
    """5. Проверка разрешений в TeamworkPipeline и PlanExecutor."""

    def setUp(self):
        reset_permission_manager()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = AgentRegistry()
        self.registry.register(EchoAgent())
        self.registry.register(FileAgent(project_path=self.temp_dir.name))
        self.registry.register(CodingAgent(project_path=self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()
        set_confirmation_handler(None)
        reset_permission_manager()

    def test_teamwork_pipeline_safe_agents_no_prompt(self):
        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(PipelineStep(agent="echo", task="Привет!"))
        res = pipeline.run()
        self.assertTrue(res.success)

    def test_teamwork_pipeline_subagent_cancelled_before_execution(self):
        # Задаем отказ пользователя
        set_confirmation_handler(lambda tool, kwargs: False)

        target_file = Path(self.temp_dir.name) / "blocked_file.txt"

        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(PipelineStep(
            agent="file",
            task=f"Создай файл {target_file.name}",
            metadata={"action": "create", "filename": str(target_file), "content": "данные"}
        ))

        res = pipeline.run()
        self.assertFalse(res.success)
        self.assertIn("отменил", res.error.lower())
        # Проверяем, что файл НЕ был создан на диске
        self.assertFalse(target_file.exists())

    def test_teamwork_pipeline_subagent_approved_and_executed(self):
        set_confirmation_handler(lambda tool, kwargs: True)

        target_file = Path(self.temp_dir.name) / "approved_file.txt"

        pipeline = TeamworkPipeline(registry=self.registry)
        pipeline.add_step(PipelineStep(
            agent="file",
            task=f"Создай файл {target_file.name}",
            metadata={"action": "create", "filename": str(target_file), "content": "тест"}
        ))

        res = pipeline.run()
        self.assertTrue(res.success)
        self.assertTrue(target_file.exists())
        self.assertEqual(target_file.read_text(encoding="utf-8"), "тест")

    def test_plan_executor_halts_when_subagent_cancelled(self):
        set_confirmation_handler(lambda tool, kwargs: False)

        plan = TaskPlan(
            goal="Создать файл и эхо",
            steps=[
                PlanStep(id=1, action="file", subagent="file", task="Создай test.txt", metadata={"action": "create", "filename": "test.txt"}),
                PlanStep(id=2, action="echo", subagent="echo", task="Шаг 2", depends_on=[1])
            ]
        )

        executor = PlanExecutor()
        res = executor.execute(plan)
        self.assertFalse(res.success)
        self.assertIn("отменено пользователем", res.message)
        self.assertEqual(len(res.data.get("results", [])), 1)

    def test_agent_execute_subagent_check(self):
        agent = Agent(agent_registry=self.registry)

        # Отклонение
        set_confirmation_handler(lambda tool, kwargs: False)
        res_reject = agent.execute_subagent("file", task="Создай test2.txt", metadata={"action": "create", "filename": "test2.txt"})
        self.assertFalse(res_reject.success)
        self.assertIn("отменил", res_reject.error.lower())

        # Одобрение
        set_confirmation_handler(lambda tool, kwargs: True)
        res_approve = agent.execute_subagent("file", task="Создай test2.txt", metadata={"action": "create", "filename": "test2.txt", "content": "ok"})
        self.assertTrue(res_approve.success)


if __name__ == "__main__":
    unittest.main()
