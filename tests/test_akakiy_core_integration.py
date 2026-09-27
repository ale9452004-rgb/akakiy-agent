"""
Интеграционные тесты для единого ядра Акакий 2.0 (Этап №20 — Akakiy 2.0 Core).

Проверяет:
1. Сквозной жизненный цикл задачи: Router -> Planner -> Executor -> Sub-Agents -> Self-Healing -> Artifacts.
2. Непрерывность и согласованность AgentContext при передаче Core -> Teamwork -> Sub-Agent.
3. Единообразие моделей AgentResult и Artifacts на всех уровнях конвейера.
4. Централизованный перехват опасных операций через PermissionManager (подтверждение и отмена).
5. Работу Self-Healing внутри конвейера исполнения задач при восстановимых ошибках.
6. Явную фиксацию в Persistent Memory (remember_result) и выживаемость после перезапуска.
7. Интеграцию VoicePipeline с Agent Core (извлечение речевого ответа, артефакты, события).
8. Интеграцию GUI Desktop Hub с Agent Core через record_work_result и общие структуры данных.
"""

import json
import os
from pathlib import Path
import shutil
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from tools.agent import Agent
from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.registry import AgentRegistry
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.dispatcher import set_confirmation_handler
from tools.memory import MemoryManager
from tools.persistent_memory import PersistentMemory, MemoryType, MemorySource
from tools.permissions import PermissionManager, RiskLevel, SecurityPolicy
from tools.planner import Planner, PlanStep, TaskPlan
from tools.plan_executor import PlanExecutor
from tools.router import CommandRouter
from tools.self_healing import SelfHealingManager, ErrorContext, ErrorCategory
from tools.teamwork import TeamworkCoordinator, TeamworkPipeline, PipelineStep
from voice.pipeline import VoicePipeline, extract_speech_text
from gui import AkakiyGUI


class EchoTestAgent(SubAgent):
    """Тестовый детерминированный субагент для проверки сквозной передачи данных."""

    def __init__(self, name="echo"):
        super().__init__(name=name, description="Echo subagent for core testing")

    def run(self, context: AgentContext) -> AgentResult:
        task_text = context.task or context.instruction or "echo"
        art = Artifact(
            name="echo_artifact.txt",
            type=ArtifactType.TEXT,
            content=f"Processed: {task_text}",
            metadata={"source": "EchoTestAgent"}
        )
        return AgentResult.ok(
            message=f"EchoAgent успешно выполнил: {task_text}",
            created_files=["echo_output.txt"],
            artifacts=[art],
            data={"echo_task": task_text, "parent": str(context.parent_agent is not None)}
        )


class FlakyTestAgent(SubAgent):
    """Субагент с контролируемым сбоем на первой попытке (для проверки Self-Healing)."""

    def __init__(self, name="flaky"):
        super().__init__(name=name, description="Flaky subagent")
        self.call_count = 0

    def run(self, context: AgentContext) -> AgentResult:
        self.call_count += 1
        if self.call_count == 1:
            # Первая попытка: восстановимая ошибка
            return AgentResult.fail(
                error="Временный сбой сети timeout",
                message="Ошибка соединения timeout"
            )
        # Вторая попытка: успешное восстановление
        art = Artifact.from_file("recovered_report.txt", type=ArtifactType.DOCUMENT)
        return AgentResult.ok(
            message="Успешно восстановлено после временного сбоя сети",
            created_files=["recovered_report.txt"],
            artifacts=[art]
        )


class TestAkakiyCoreIntegration(unittest.TestCase):
    """Интеграционное тестирование единого ядра Акакий 2.0."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="akakiy_core_test_")
        self.memory_file = Path(self.temp_dir) / "test_memory.json"
        self.memory_manager = MemoryManager(storage_file=self.memory_file)
        self.agent_registry = AgentRegistry()
        self.echo_agent = EchoTestAgent("echo")
        self.flaky_agent = FlakyTestAgent("flaky")
        self.agent_registry.register(self.echo_agent)
        self.agent_registry.register(self.flaky_agent)

        self.perm_manager = PermissionManager(
            policy=SecurityPolicy.NORMAL,
            project_path=self.temp_dir
        )
        set_confirmation_handler(None)

        self.agent = Agent(
            memory_manager=self.memory_manager,
            agent_registry=self.agent_registry,
            permission_manager=self.perm_manager
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        set_confirmation_handler(None)

    # =========================================================================
    # 1. Сквозной жизненный цикл: Router -> Planner -> Executor -> Sub-Agent
    # =========================================================================

    def test_e2e_plan_execution_lifecycle_with_subagent(self):
        """Проверка сквозного цикла планирования, выполнения через субагент и формирования отчёта."""
        # 1. Создаем план с шагом субагента
        plan = TaskPlan(goal="Собрать отчёт по проекту")
        step1 = PlanStep(
            id=1,
            action="subagent",
            subagent="echo",
            task="Подготовить первичные данные",
            description="Сбор первичных данных через EchoAgent"
        )
        plan.add_step(step1)

        # 2. Исполняем план через Agent Core
        exec_res = self.agent.execute_plan(plan)

        # 3. Проверяем AgentResult и структуру отчёта
        self.assertTrue(exec_res.success)
        self.assertIn("echo_output.txt", exec_res.created_files)
        self.assertTrue(len(exec_res.artifacts) >= 1)
        self.assertEqual(exec_res.artifacts[0].name, "echo_artifact.txt")
        self.assertIn("## План", exec_res.get("summary", ""))
        self.assertIn("1. Сбор первичных данных через EchoAgent", exec_res.get("summary", ""))
        self.assertEqual(self.agent._last_result, exec_res)

    # =========================================================================
    # 2. Непрерывность AgentContext
    # =========================================================================

    def test_agent_context_continuity_across_subagents(self):
        """Проверка непрерывности контекста: передача parent_agent, metadata и previous_results."""
        parent_ctx = AgentContext(
            task="Комплексная задача",
            parent_agent=self.agent,
            metadata={"session_id": "core_123"}
        )

        res = self.agent.run_subagent("echo", task="Тест контекста", context=parent_ctx)
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("parent"), "True")
        self.assertEqual(parent_ctx.metadata.get("session_id"), "core_123")

    # =========================================================================
    # 3. Интеграция Self-Healing внутри конвейера
    # =========================================================================

    def test_self_healing_within_plan_executor(self):
        """Проверка восстановления восстановимой ошибки субагента внутри PlanExecutor."""
        plan = TaskPlan(goal="Восстанавливаемая задача")
        step = PlanStep(
            id=1,
            action="subagent",
            subagent="flaky",
            task="Сетевая синхронизация",
            description="Синхронизация через FlakyAgent"
        )
        plan.add_step(step)

        # PlanExecutor с включенным self-healing
        executor = PlanExecutor(
            agent=self.agent,
            stop_on_error=True,
            max_retries=2,
            enable_self_healing=True
        )
        self.agent.executor = executor

        exec_res = self.agent.execute_plan(plan)

        self.assertTrue(exec_res.success)
        self.assertEqual(self.flaky_agent.call_count, 2)
        self.assertTrue(exec_res.data.get("recovered"))
        self.assertIn("recovered_report.txt", exec_res.created_files)

    # =========================================================================
    # 4. Permissions & Safety Layer в конвейере
    # =========================================================================

    def test_permission_manager_interception_confirm_and_reject(self):
        """Проверка перехвата опасного действия субагента: отмена пользователем и подтверждение."""
        # Создаем субагент с опасным действием
        class DangerousAgent(SubAgent):
            def __init__(self):
                super().__init__(name="risky", description="Agent for dangerous actions")

            def run(self, context):
                return AgentResult.ok("Опасное действие завершено")

        self.agent_registry.register(DangerousAgent())

        # Случай 1: Пользователь отклоняет запрос
        self.perm_manager.set_confirmation_handler(lambda name, kwargs: False)
        res_rejected = self.agent.run_subagent("risky", task="Удали временные файлы проекта")
        self.assertFalse(res_rejected.success)
        self.assertIn("отменено", res_rejected.message.lower())

        # Случай 2: Пользователь подтверждает запрос
        self.perm_manager.set_confirmation_handler(lambda name, kwargs: True)
        res_approved = self.agent.run_subagent("risky", task="Удали временные файлы проекта")
        self.assertTrue(res_approved.success)
        self.assertEqual(res_approved.message, "Опасное действие завершено")

    # =========================================================================
    # 5. Persistent Memory: remember_result и переживание перезапуска
    # =========================================================================

    def test_persistent_memory_remember_result_and_restart(self):
        """Проверка фиксации результата в PersistentMemory и его восстановления после перезапуска."""
        # 1. Создаем результат с артефактами
        art = Artifact(name="final_spec.docx", type=ArtifactType.DOCUMENT, path="final_spec.docx")
        task_res = AgentResult.ok(
            message="Спецификация архитектуры успешно создана",
            created_files=["final_spec.docx"],
            artifacts=[art]
        )

        # 2. Явно сохраняем результат через фасад Agent Core
        success, msg, entry = self.agent.remember_result(
            task_res,
            title="Архитектура v2",
            tags=["core", "architecture"]
        )
        self.assertTrue(success)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.type, MemoryType.RESULT)
        self.assertIn("final_spec.docx", entry.metadata.get("created_files", []))

        # 3. Проверяем маршрутизацию через текстовую команду "запомни результат"
        self.agent._last_result = task_res
        route_res = self.agent.process("сохрани результат в память")
        self.assertEqual(route_res.get("type"), "memory")
        self.assertTrue(route_res.get("success"))

        # 4. Симуляция перезапуска приложения: создание нового экземпляра MemoryManager
        new_memory_mgr = MemoryManager(storage_file=self.memory_file)
        results = new_memory_mgr.search("Спецификация", type=MemoryType.RESULT)
        self.assertTrue(len(results) >= 1)
        self.assertIn("Архитектура v2", results[0].get("text"))

    # =========================================================================
    # 6. Интеграция VoicePipeline через Agent Core
    # =========================================================================

    def test_voice_pipeline_integration_through_agent_core(self):
        """Проверка работы VoicePipeline через единый Agent Core с извлечением speech text."""
        voice_pipe = VoicePipeline(agent=self.agent)

        # Обрабатываем фразу, маршрутизируемую через детерминированный роутер Core
        pipe_result = voice_pipe.process_phrase("память", speak=False)

        self.assertEqual(pipe_result.status, "success")
        self.assertTrue(pipe_result.is_success)
        self.assertTrue(len(pipe_result.spoken_text) > 0)
        self.assertEqual(pipe_result.agent_result.get("type"), "chat")

    # =========================================================================
    # 7. Интеграция GUI Desktop Hub с Agent Core
    # =========================================================================

    def test_gui_record_work_result_with_core_outputs(self):
        """Проверка корректной обработки всех типов ответов Agent Core в record_work_result GUI."""
        root = tk.Tk()
        root.withdraw()
        gui = None
        try:
            gui = AkakiyGUI(root=root, agent=self.agent, voice=MagicMock())

            # 1. Результат выполнения плана (plan_execution)
            art = Artifact(name="report.pdf", type=ArtifactType.DOCUMENT, path="report.pdf")
            agent_res = AgentResult.ok(
                message="Отчёт успешно скомпилирован",
                created_files=["report.pdf"],
                artifacts=[art]
            )
            plan_exec_payload = {
                "type": "plan_execution",
                "tool": "execute_plan",
                "result": agent_res,
                "success": True,
                "message": "Отчёт успешно скомпилирован",
                "created_files": ["report.pdf"],
                "artifacts": [art.to_dict()]
            }

            entry = gui.record_work_result(plan_exec_payload, query="собери отчёт")
            self.assertTrue(entry.get("success"))
            self.assertEqual(entry.get("type"), "plan_execution")
            self.assertIn("report.pdf", entry.get("created_files"))
            self.assertEqual(len(entry.get("artifacts")), 1)

            # 2. Результат вызова субагента (subagent)
            sub_payload = {
                "type": "subagent",
                "agent": "echo",
                "result": agent_res,
                "success": True,
                "answer": "Echo завершено",
                "created_files": ["report.pdf"],
                "artifacts": [art.to_dict()]
            }
            entry_sub = gui.record_work_result(sub_payload, query="вызови echo")
            self.assertTrue(entry_sub.get("success"))
            self.assertEqual(entry_sub.get("type"), "subagent")
        finally:
            if gui is not None:
                try:
                    gui.destroy()
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass

    # =========================================================================
    # 8. Обратная совместимость: исполнение legacy-планов
    # =========================================================================

    def test_legacy_plan_execution_backward_compatibility(self):
        """Проверка исполнения legacy-плана (список словарей) с формированием AgentResult и summary."""
        legacy_plan = [
            {"id": 1, "action": "subagent", "subagent": "echo", "task": "Legacy шаг 1", "description": "Шаг legacy 1"},
            {"id": 2, "action": "subagent", "subagent": "echo", "task": "Legacy шаг 2", "description": "Шаг legacy 2", "depends_on": [1]}
        ]

        exec_res = self.agent.execute_plan(legacy_plan)
        self.assertTrue(exec_res.success)
        self.assertIsInstance(exec_res, AgentResult)
        self.assertIn("echo_output.txt", exec_res.created_files)
        self.assertIn("## План", exec_res.get("summary", ""))

    # =========================================================================
    # 9. Блокировка деструктивных шагов в плане политикой безопасности
    # =========================================================================

    def test_plan_execution_with_dangerous_step_blocked_by_permissions(self):
        """Проверка, что деструктивная команда в плане блокируется PermissionManager без краша."""
        destructive_plan = TaskPlan(goal="Опасная задача")
        destructive_step = PlanStep(
            id=1,
            action="command",
            command="Remove-Item -Recurse -Force C:\\Windows",
            description="Деструктивная очистка"
        )
        destructive_plan.add_step(destructive_step)

        # Headless режим или отказ пользователя
        self.perm_manager.set_confirmation_handler(lambda name, kwargs: False)

        exec_res = self.agent.execute_plan(destructive_plan)
        self.assertFalse(exec_res.success)
        self.assertIn("отменен", exec_res.message.lower())

    # =========================================================================
    # 10. VoicePipeline: извлечение речевого ответа из plan_execution
    # =========================================================================

    def test_voice_pipeline_speech_extraction_from_plan_execution(self):
        """Проверка, что extract_speech_text корректно форматирует речевой ответ из plan_execution."""
        plan_res = AgentResult.ok(
            message="План успешно завершён. Создано 3 файла.",
            created_files=["a.py", "b.py", "c.py"]
        )
        payload = {
            "type": "plan_execution",
            "tool": "execute_plan",
            "result": plan_res,
            "success": True,
            "answer": "План успешно завершён. Создано 3 файла."
        }

        speech = extract_speech_text(payload)
        self.assertEqual(speech, "План успешно завершён. Создано 3 файла.")

        # Ошибка выполнения плана
        err_plan = AgentResult.fail(
            error="Синтаксическая ошибка в модуле",
            message="Сбой выполнения плана"
        )
        fail_payload = {
            "type": "plan_execution",
            "tool": "execute_plan",
            "result": err_plan,
            "success": False
        }
        speech_fail = extract_speech_text(fail_payload)
        self.assertIn("Ошибка выполнения плана", speech_fail)

    # =========================================================================
    # 11. Стандартизация формата ответов Agent.process
    # =========================================================================

    def test_agent_process_standardized_subagent_and_tool_payloads(self):
        """Проверка, что вызовы через Agent.process возвращают стандартизированный контракт с top-level полями."""
        # Вызов Echo через router
        res = self.agent.process("субагент echo: Тестовая задача")
        self.assertEqual(res.get("type"), "subagent")
        self.assertTrue(res.get("success"))
        self.assertIn("EchoAgent успешно выполнил", res.get("answer"))
        self.assertTrue(len(res.get("created_files", [])) >= 1)
        self.assertTrue(len(res.get("artifacts", [])) >= 1)


if __name__ == "__main__":
    unittest.main()
