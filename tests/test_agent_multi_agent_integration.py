"""
Интеграционные тесты подключения MultiAgentBridge в производственный конвейер Agent.process() (Этап 28).

Проверяет:
1. Household-запрос ("создай задачу купить молоко") -> HouseholdAgent -> AgentResult -> ответ с type="tasks"/CompatibleType, success=True.
2. Research-запрос ("исследуй тему искусственный интеллект") -> ResearchAgent -> worker -> AgentResult с артефактами.
3. Команды памяти ("запомни: ...", "что ты помнишь", "забудь: ...") -> старый chat/memory pipeline без вызова MultiAgentBridge.
4. Команды планов ("создай план ...", "покажи план", "выполни план") -> старый plan pipeline без вызова MultiAgentBridge.
5. Медиа и субагенты ("сгенерируй картинку ...", "сделай презентацию ...", "создай документ ...", "напиши код ...", "субагент: ...") -> старый subagent pipeline без вызова MultiAgentBridge.
6. Проектные инструменты ("покажи список файлов", "найди файл ...", "поиск по проекту ...") -> детерминированный tool fast-path без вызова MultiAgentBridge.
7. Сложный многошаговый запрос -> TeamworkCoordinator имеет приоритет над MultiAgentBridge.
8. Случай, когда Bridge вернул None -> плавный fallback в legacy tool / LLM.
9. Исключение внутри Bridge -> перехватывается, логируется, агент не падает и передает управление в legacy pipeline.
10. Добавление нового Domain Agent через AgentRegistry -> Agent.process() автоматически умеет маршрутизировать к нему без изменения кода tools/agent.py.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.base import BaseAgent
from agents.bridge import MultiAgentBridge
from agents.registry import get_agent_registry, reset_agent_registry
from agents.service import get_agent_service, reset_agent_service
from tools.agent import Agent
from tools.agents import get_agent_registry as get_worker_registry
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.context import ContextManager
from tools.dispatcher import set_confirmation_handler
from tools.household import get_household_manager, reset_household_manager
from tools.memory import MemoryManager
from tools.router import CommandRouter


class TestAgentMultiAgentIntegration(unittest.TestCase):
    """Интеграционные тесты сквозного конвейера Agent.process() с MultiAgentBridge."""

    def setUp(self):
        # 1. Изоляция файловой системы (память и бытовой менеджер во временной папке)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mem_path = Path(self.temp_dir.name) / "test_memory.json"
        self.household_path = Path(self.temp_dir.name) / "test_household.json"

        set_confirmation_handler(lambda tool, kwargs: True)
        reset_household_manager()
        self.household_mgr = get_household_manager(storage_path=self.household_path)

        reset_agent_registry()
        reset_agent_service()

        self.mem = MemoryManager(storage_path=self.mem_path)
        self.ctx = ContextManager(memory_manager=self.mem)
        self.mock_ai = MagicMock()
        self.mock_ai.send_chat.return_value = {"content": "Ответ от LLM", "tool_calls": []}

        # 2. Создание production-агента с дефолтным bridge
        self.agent = Agent(
            memory_manager=self.mem,
            context_manager=self.ctx,
            ai_client=self.mock_ai
        )
        self.agent.router = CommandRouter()

    def tearDown(self):
        set_confirmation_handler(None)
        reset_household_manager()
        reset_agent_registry()
        reset_agent_service()
        self.temp_dir.cleanup()

    def test_01_household_request_routed_via_bridge(self):
        """1. Household-запрос -> MultiAgentBridge -> HouseholdAgent -> AgentResult."""
        res = self.agent.process("создай задачу купить свежее молоко")

        self.assertTrue(res["success"])
        # CompatibleType: type равен и 'tasks', и 'tool'
        self.assertEqual(res["type"], "tasks")
        self.assertEqual(res["type"], "tool")
        self.assertEqual(res["tool"], "create_task")
        self.assertIn("купить свежее молоко", res["answer"])
        self.assertIsInstance(res["result"], AgentResult)

        # Проверяем, что задача действительно создана в HouseholdManager
        tasks = self.household_mgr.list_tasks().get("tasks", [])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "купить свежее молоко")

        # LLM не вызывался
        self.mock_ai.send_chat.assert_not_called()

    def test_02_research_request_routed_via_bridge(self):
        """2. Research-запрос -> MultiAgentBridge -> ResearchAgent -> worker -> AgentResult."""
        mock_result = AgentResult.ok(
            message="Исследование темы 'квантовые вычисления' завершено.",
            artifacts=[Artifact(name="quantum_report.md", type=ArtifactType.TEXT, content="# Отчёт по квантовым вычислениям")]
        )

        with patch("tools.agents.research.ResearchAgent.run", return_value=mock_result) as mock_worker_run:
            res = self.agent.process("исследуй тему квантовые вычисления")

            self.assertTrue(res["success"])
            self.assertEqual(res["type"], "research")
            self.assertIn("квантовые вычисления", res["answer"])
            self.assertEqual(len(res["artifacts"]), 1)
            self.assertEqual(res["artifacts"][0]["name"], "quantum_report.md")
            mock_worker_run.assert_called_once()
            self.mock_ai.send_chat.assert_not_called()

    def test_03_memory_commands_bypass_bridge(self):
        """3. Команды памяти -> старый chat/memory pipeline в обход MultiAgentBridge."""
        with patch.object(self.agent.bridge, "try_process") as mock_bridge_process:
            # 1. Запомнить факт
            res1 = self.agent.process("запомни: Мой пароль от сейфа 987654")
            self.assertEqual(res1["type"], "chat")
            self.assertIn("Запомнил", res1["answer"])
            mock_bridge_process.assert_not_called()

            # 2. Что ты помнишь
            res2 = self.agent.process("что ты помнишь")
            self.assertEqual(res2["type"], "chat")
            self.assertIn("987654", res2["answer"])
            mock_bridge_process.assert_not_called()

            # 3. Забыть факт
            res3 = self.agent.process("забудь: 987654")
            self.assertEqual(res3["type"], "chat")
            self.assertIn("Удалил", res3["answer"])
            mock_bridge_process.assert_not_called()

    def test_04_plan_commands_bypass_bridge(self):
        """4. Команды планов -> старый plan pipeline в обход MultiAgentBridge."""
        with patch.object(self.agent.bridge, "try_process") as mock_bridge_process:
            # 1. Создать план
            self.agent.create_plan = MagicMock(return_value={"success": True, "plan": {"title": "Рефакторинг"}})
            res_plan = self.agent.process("создай план протестировать интеграцию")
            self.assertEqual(res_plan["type"], "plan")
            self.assertTrue(res_plan["result"]["success"])
            mock_bridge_process.assert_not_called()

            # 2. Показать план
            self.agent.planner.current_plan = {"title": "Рефакторинг"}
            res_get = self.agent.process("покажи план")
            self.assertEqual(res_get["type"], "plan")
            mock_bridge_process.assert_not_called()

            # 3. Очистить план
            res_clear = self.agent.process("очисти план")
            self.assertEqual(res_clear["type"], "tool")
            self.assertEqual(res_clear["tool"], "clear_plan")
            mock_bridge_process.assert_not_called()

    def test_05_media_and_subagents_bypass_bridge(self):
        """5. Медиа и субагенты -> старый fast-path pipeline в обход MultiAgentBridge."""
        with patch.object(self.agent.bridge, "try_process") as mock_bridge_process:
            self.agent.run_subagent = MagicMock(return_value=AgentResult.ok(
                message="Субагент успешно выполнил работу",
                created_files=["output.png"]
            ))

            # 1. Генерация картинки
            res_img = self.agent.process("сгенерируй изображение заката в горах")
            self.assertEqual(res_img["type"], "image")
            self.assertTrue(res_img["success"])

            # 2. Презентация
            res_pres = self.agent.process("создай презентацию про искусственный интеллект")
            self.assertEqual(res_pres["type"], "presentation")
            self.assertTrue(res_pres["success"])

            # 3. Документ
            res_doc = self.agent.process("создай документ технический отчёт")
            self.assertEqual(res_doc["type"], "document")
            self.assertTrue(res_doc["success"])

            # 4. Код (Coding Sub-Agent)
            res_code = self.agent.process("код: напиши функцию вычисления факториала")
            self.assertEqual(res_code["type"], "coding")
            self.assertTrue(res_code["success"])

            # 5. Файл (File Sub-Agent)
            res_file = self.agent.process("файл: прочитай config.py")
            self.assertEqual(res_file["type"], "file")
            self.assertTrue(res_file["success"])

            # 6. Явный вызов субагента
            res_sub = self.agent.process("субагент echo: тестовая задача")
            self.assertEqual(res_sub["type"], "subagent")
            self.assertTrue(res_sub["success"])

            # Bridge ни разу не должен был вызываться
            mock_bridge_process.assert_not_called()

    def test_06_project_tools_bypass_bridge(self):
        """6. Проектные инструменты -> проектный fast-path в обход MultiAgentBridge."""
        with patch.object(self.agent.bridge, "try_process") as mock_bridge_process:
            # 1. list_files
            res_list = self.agent.process("покажи список файлов проекта")
            self.assertEqual(res_list["type"], "tool")
            self.assertEqual(res_list["tool"], "list_files")
            self.assertTrue(res_list["result"]["success"])

            # 2. find_file
            res_find = self.agent.process("найди файл main.py")
            self.assertEqual(res_find["type"], "tool")
            self.assertEqual(res_find["tool"], "find_file")
            self.assertTrue(res_find["result"]["success"])

            # 3. search_files
            res_search = self.agent.process("поиск по проекту CommandRouter")
            self.assertEqual(res_search["type"], "tool")
            self.assertEqual(res_search["tool"], "search_files")
            self.assertTrue(res_search["result"]["success"])

            # MultiAgentBridge не вызывался для проектных инструментов
            mock_bridge_process.assert_not_called()

    def test_07_complex_task_teamwork_priority_over_bridge(self):
        """7. Сложный многошаговый запрос -> TeamworkCoordinator имеет безусловный приоритет."""
        with patch.object(self.agent.bridge, "try_process") as mock_bridge_process:
            self.agent.teamwork.is_complex_task = MagicMock(return_value=True)
            self.agent.teamwork.run = MagicMock(return_value={
                "success": True,
                "message": "План сложной задачи успешно скоординирован и выполнен.",
                "artifacts": [],
                "created_files": []
            })

            res = self.agent.process("сделай масштабное исследование и составь детальный отчет")

            self.assertEqual(res["type"], "plan_execution")
            self.assertTrue(res["success"])
            self.assertIn("скоординирован", res["message"])
            self.agent.teamwork.run.assert_called_once()
            # Bridge не вызывался, так как Teamwork перехватил выполнение
            mock_bridge_process.assert_not_called()

    def test_08_bridge_returns_none_falls_back_to_legacy(self):
        """8. Если Bridge возвращает None -> плавный переход в legacy pipeline (LLM/инструменты)."""
        # Свободный диалоговый запрос, не относящийся к доменным агентам
        res = self.agent.process("Привет! Расскажи интересную историю про освоение космоса.")

        self.assertEqual(res["type"], "chat")
        self.assertEqual(res["answer"], "Ответ от LLM")
        self.mock_ai.send_chat.assert_called_once()

    def test_09_bridge_exception_safely_caught_and_fallback(self):
        """9. Исключение внутри Bridge перехватывается, логируется и происходит fallback в legacy."""
        # Моделируем непредвиденную критическую ошибку внутри bridge.try_process
        self.agent.bridge.try_process = MagicMock(side_effect=RuntimeError("Критический сбой моста!"))

        # Запрос не должен уронить Agent.process(), а должен завершиться через legacy fallback
        res = self.agent.process("Какая столица Франции?")

        self.assertEqual(res["type"], "chat")
        self.assertEqual(res["answer"], "Ответ от LLM")
        self.mock_ai.send_chat.assert_called_once()

    def test_10_custom_domain_agent_extensibility(self):
        """10. OCP: Новый Domain Agent регистрируется в реестре и исполняется через Agent.process() без правок agent.py."""
        class WeatherDomainAgent(BaseAgent):
            name = "weather"
            description = "Агент для предоставления сводок погоды"
            capabilities = ["weather", "forecast"]

            def can_handle(self, task: str) -> float:
                return 1.0 if "погода" in task.lower() else 0.0

            def execute(self, task, context=None, **kwargs):
                return AgentResult.ok(
                    message="В Сочи сегодня ясно, температура +24°C, штиль.",
                    data={"city": "Сочи", "temp": 24, "condition": "sunny"}
                )

        weather_agent = WeatherDomainAgent()
        domain_registry = get_agent_registry()
        domain_registry.register(weather_agent)

        res = self.agent.process("какая сейчас погода в городе Сочи?")

        self.assertTrue(res["success"])
        self.assertEqual(res["type"], "weather")
        self.assertIn("В Сочи сегодня ясно", res["answer"])
        self.assertEqual(res["data"]["temp"], 24)
        self.mock_ai.send_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
