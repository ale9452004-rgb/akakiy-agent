"""
Набор автоматизированных тестов для Sub-Agent Architecture (Этап 1).

Проверяет:
1. Базовый контракт SubAgent (наследование, abstractmethod run, валидация контекста, строковое представление).
2. Реестр AgentRegistry (регистрация валидных, отклонение некорректных типов и пустых имен, unregister, get, has, list_agents, get_all, clear, enable/disable).
3. Потокобезопасность и синглтон AgentRegistry (get_agent_registry, reset_agent_registry).
4. Структуру и фабричные методы AgentResult (AgentResult.ok, AgentResult.fail, created_files, data, error, dict-like совместимость).
5. Контекст задачи AgentContext (инициализация, добавление файлов, get, to_dict, from_dict, связь с parent_agent).
6. Работу эталонного EchoAgent (успешное эхо, mock_files, эмуляция ошибок через метаданные и текст задачи, реакция на disabled).
7. Интеграцию с главным Agent (вызов Agent.run_subagent с параметрами, с готовым AgentContext, обработка несуществующего агента).
8. Сохранение обратной совместимости и отсутствие регрессии существующих Agent/router/plan flows.
"""

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.agents import (
    SubAgent,
    AgentContext,
    AgentResult,
    AgentRegistry,
    get_agent_registry,
    reset_agent_registry,
    EchoAgent
)
from tools.agent import Agent
from tools.router import CommandRouter


class DummyValidAgent(SubAgent):
    """Тестовый валидный SubAgent."""
    name = "dummy"
    description = "Тестовый агент"
    capabilities = ["testing"]

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult.ok(message="dummy result", data={"dummy": True})


class TestSubAgentBaseContract(unittest.TestCase):
    """1. Тестирование базового контракта SubAgent."""

    def test_abstract_run_instantiation_fails_without_run(self):
        """Нельзя инстанцировать SubAgent без реализации метода run()."""
        class IncompleteAgent(SubAgent):
            name = "incomplete"

        with self.assertRaises(TypeError):
            IncompleteAgent()

    def test_subagent_initialization_defaults_and_overrides(self):
        """Проверка инициализации атрибутов по умолчанию и через аргументы конструктора."""
        agent = DummyValidAgent(
            name="custom_dummy",
            description="Кастомное описание",
            capabilities=["cap1", "cap2"],
            enabled=False
        )
        self.assertEqual(agent.name, "custom_dummy")
        self.assertEqual(agent.description, "Кастомное описание")
        self.assertEqual(agent.capabilities, ["cap1", "cap2"])
        self.assertFalse(agent.enabled)
        self.assertIn("custom_dummy", repr(agent))
        self.assertIn("disabled", repr(agent))

    def test_validate_context_default_behavior(self):
        """Проверка дефолтной валидации контекста."""
        agent = DummyValidAgent()
        valid_ctx = AgentContext(task="Тест")
        self.assertTrue(agent.validate_context(valid_ctx))
        self.assertFalse(agent.validate_context("не контекст"))
        self.assertFalse(agent.validate_context(None))


class TestAgentContext(unittest.TestCase):
    """2. Тестирование контейнера AgentContext."""

    def test_context_initialization_and_accessors(self):
        """Проверка инициализации полей контекста и метода get()."""
        ctx = AgentContext(
            task="Сгенерировать отчет",
            files=["report.md", "data.json"],
            previous_results=[{"step": 1, "done": True}],
            metadata={"format": "pdf", "priority": "high"}
        )
        self.assertEqual(ctx.task, "Сгенерировать отчет")
        self.assertEqual(ctx.files, ["report.md", "data.json"])
        self.assertEqual(len(ctx.previous_results), 1)
        self.assertEqual(ctx.get("format"), "pdf")
        self.assertEqual(ctx.get("unknown_key", "default_val"), "default_val")

    def test_context_add_file_deduplication(self):
        """Добавление файлов не должно создавать дубликатов."""
        ctx = AgentContext(task="Тест", files=["file1.txt"])
        ctx.add_file("file2.txt")
        ctx.add_file("file1.txt")  # Дубликат
        self.assertEqual(ctx.files, ["file1.txt", "file2.txt"])

    def test_context_serialization_to_and_from_dict(self):
        """Проверка to_dict() и from_dict()."""
        original_ctx = AgentContext(
            task="Обработка",
            files=["input.txt"],
            previous_results=["result1"],
            metadata={"timeout": 30}
        )
        data = original_ctx.to_dict()
        restored_ctx = AgentContext.from_dict(data)

        self.assertEqual(restored_ctx.task, original_ctx.task)
        self.assertEqual(restored_ctx.files, original_ctx.files)
        self.assertEqual(restored_ctx.previous_results, original_ctx.previous_results)
        self.assertEqual(restored_ctx.metadata, original_ctx.metadata)

    def test_from_dict_invalid_type_raises(self):
        """from_dict с некорректным типом данных вызывает TypeError."""
        with self.assertRaises(TypeError):
            AgentContext.from_dict("не dict")


class TestAgentResult(unittest.TestCase):
    """3. Тестирование контейнера AgentResult."""

    def test_agent_result_ok_factory(self):
        """Проверка фабрики AgentResult.ok."""
        res = AgentResult.ok(
            message="Успешно выполнено",
            created_files=["output.png"],
            data={"width": 100, "height": 100}
        )
        self.assertTrue(res.success)
        self.assertEqual(res.message, "Успешно выполнено")
        self.assertIsNone(res.error)
        self.assertEqual(res.created_files, ["output.png"])
        self.assertEqual(res.data, {"width": 100, "height": 100})
        self.assertIn("OK", repr(res))

    def test_agent_result_fail_factory(self):
        """Проверка фабрики AgentResult.fail."""
        res = AgentResult.fail(
            error="Сбой генерации",
            message="Не удалось создать файл",
            data={"attempt": 2}
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error, "Сбой генерации")
        self.assertEqual(res.message, "Не удалось создать файл")
        self.assertEqual(res.created_files, [])
        self.assertEqual(res.data, {"attempt": 2})
        self.assertIn("FAIL", repr(res))

    def test_agent_result_dict_like_access(self):
        """Проверка обратной совместимости с dict-интерфейсом."""
        res = AgentResult.ok(message="Тест", created_files=["a.txt"])
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "Тест")
        self.assertEqual(res["created_files"], ["a.txt"])
        self.assertEqual(res.get("success"), True)
        self.assertIn("message", res)
        self.assertNotIn("non_existent_key", res)


class TestAgentRegistry(unittest.TestCase):
    """4. Тестирование реестра AgentRegistry."""

    def setUp(self):
        reset_agent_registry()

    def tearDown(self):
        reset_agent_registry()

    def test_register_and_get_agent(self):
        """Регистрация и получение агента по имени."""
        reg = AgentRegistry()
        agent = DummyValidAgent()
        reg.register(agent)

        self.assertTrue(reg.has("dummy"))
        self.assertIs(reg.get("dummy"), agent)
        self.assertEqual(len(reg.list_agents()), 1)

    def test_register_invalid_agent_raises(self):
        """Регистрация не-SubAgent вызывает TypeError."""
        reg = AgentRegistry()
        with self.assertRaises(TypeError):
            reg.register("не агент")

    def test_register_empty_name_raises(self):
        """Агент с пустым именем вызывает ValueError."""
        reg = AgentRegistry()
        agent = DummyValidAgent(name="")
        with self.assertRaises(ValueError):
            reg.register(agent)

    def test_unregister_agent(self):
        """Удаление агента из реестра."""
        reg = AgentRegistry()
        agent = DummyValidAgent()
        reg.register(agent)
        removed = reg.unregister("dummy")

        self.assertIs(removed, agent)
        self.assertFalse(reg.has("dummy"))
        self.assertIsNone(reg.get("dummy"))

    def test_enable_and_disable_agent(self):
        """Динамическое включение и отключение агента в реестре."""
        reg = AgentRegistry()
        agent = DummyValidAgent()
        reg.register(agent)

        self.assertTrue(reg.disable("dummy"))
        self.assertFalse(agent.enabled)
        # enabled_only=True возвращает только включенные
        self.assertEqual(len(reg.list_agents(enabled_only=True)), 0)
        self.assertEqual(len(reg.list_agents(enabled_only=False)), 1)

        self.assertTrue(reg.enable("dummy"))
        self.assertTrue(agent.enabled)
        self.assertEqual(len(reg.list_agents(enabled_only=True)), 1)

    def test_singleton_get_agent_registry_initializes_echo(self):
        """Глобальный синглтон инициализирует встроенного EchoAgent."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("echo"))
        echo_agent = reg.get("echo")
        self.assertIsInstance(echo_agent, EchoAgent)

    def test_thread_safety_concurrent_registration(self):
        """Проверка потокобезопасности при конкурентной регистрации."""
        reg = AgentRegistry()

        def worker(idx):
            class WorkerAgent(SubAgent):
                name = f"agent_{idx}"
                def run(self, ctx):
                    return AgentResult.ok()
            reg.register(WorkerAgent())

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(reg.list_agents()), 20)


class TestEchoAgent(unittest.TestCase):
    """5. Тестирование поведения EchoAgent."""

    def setUp(self):
        self.agent = EchoAgent()

    def test_echo_agent_successful_run(self):
        """Успешное выполнение EchoAgent с возвратом переданного контекста."""
        ctx = AgentContext(
            task="Проверить эхо-ответ",
            files=["foo.py", "bar.py"],
            metadata={"user": "developer"}
        )
        res = self.agent.run(ctx)

        self.assertTrue(res.success)
        self.assertIn("Проверить эхо-ответ", res.message)
        self.assertEqual(res.data["echo_task"], "Проверить эхо-ответ")
        self.assertEqual(res.data["echo_files"], ["foo.py", "bar.py"])
        self.assertEqual(res.data["echo_metadata"], {"user": "developer"})

    def test_echo_agent_mock_files_generation(self):
        """EchoAgent возвращает созданные файлы при указании mock_files в metadata."""
        ctx = AgentContext(
            task="Создать эхо-файлы",
            metadata={"mock_files": ["gen1.txt", "gen2.png"]}
        )
        res = self.agent.run(ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.created_files, ["gen1.txt", "gen2.png"])

    def test_echo_agent_simulated_error_via_metadata(self):
        """EchoAgent возвращает fail при metadata['fail'] = True."""
        ctx = AgentContext(
            task="Тестовая задача",
            metadata={"fail": True, "error_text": "Имитация сбоя системы"}
        )
        res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertEqual(res.error, "Имитация сбоя системы")
        self.assertIn("EchoAgent завершился с ошибкой", res.message)

    def test_echo_agent_simulated_error_via_task_keyword(self):
        """EchoAgent возвращает fail при наличии ключевого слова simulate_error в task."""
        ctx = AgentContext(task="Тест с ключевым словом simulate_error")
        res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertIn("Симуляция ошибки", res.error)

    def test_echo_agent_disabled_fails(self):
        """Отключенный EchoAgent возвращает ошибку при вызове."""
        self.agent.enabled = False
        ctx = AgentContext(task="Задача")
        res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)


class TestAgentSubAgentIntegration(unittest.TestCase):
    """6. Тестирование интеграции SubAgent с главным Agent."""

    def setUp(self):
        reset_agent_registry()
        self.mock_ai = MagicMock()
        self.agent = Agent(ai_client=self.mock_ai)

    def tearDown(self):
        reset_agent_registry()

    def test_agent_has_agent_registry(self):
        """У Agent есть атрибут agent_registry с зарегистрированным EchoAgent."""
        self.assertIsNotNone(self.agent.agent_registry)
        self.assertTrue(self.agent.agent_registry.has("echo"))

    def test_agent_run_subagent_success(self):
        """Вызов Agent.run_subagent('echo', task=...) успешно отрабатывает."""
        res = self.agent.run_subagent(
            name="echo",
            task="Тестовая интеграция",
            files=["main.py"],
            custom_param=42
        )

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("Тестовая интеграция", res.message)
        self.assertEqual(res.data["echo_files"], ["main.py"])
        self.assertEqual(res.data["echo_metadata"]["custom_param"], 42)

    def test_agent_run_subagent_with_explicit_context(self):
        """Вызов Agent.run_subagent с готовым AgentContext."""
        ctx = AgentContext(
            task="Интеграция с готовым контекстом",
            files=["tools/agent.py"]
        )
        res = self.agent.run_subagent(name="echo", context=ctx)

        self.assertTrue(res.success)
        self.assertEqual(res.data["echo_task"], "Интеграция с готовым контекстом")
        self.assertIs(ctx.parent_agent, self.agent)

    def test_agent_run_subagent_unknown_agent_fails(self):
        """Вызов несуществующего агента возвращает AgentResult.fail."""
        res = self.agent.run_subagent(name="non_existent_agent", task="Привет")

        self.assertFalse(res.success)
        self.assertIn("не найден в реестре", res.error)

    def test_agent_run_subagent_empty_name_fails(self):
        """Вызов с пустым именем агента возвращает AgentResult.fail."""
        res = self.agent.run_subagent(name="", task="Привет")

        self.assertFalse(res.success)
        self.assertIn("Не указано имя", res.error)


class TestRegressionExistingAgentFlows(unittest.TestCase):
    """7. Регрессионная проверка существующих потоков Agent/Router."""

    def setUp(self):
        self.mock_ai = MagicMock()
        self.mock_mem = MagicMock()
        self.mock_mem.recall.return_value = []
        self.mock_mem.format_memories_summary.return_value = "Память пуста."
        self.agent = Agent(ai_client=self.mock_ai, memory_manager=self.mock_mem)

    def test_empty_request_returns_empty_chat_response(self):
        """Пустой запрос возвращает штатный ответ chat."""
        res = self.agent.process("   ")
        self.assertEqual(res["type"], "chat")
        self.assertIn("Пустой запрос", res["answer"])

    def test_deterministic_router_memory_fastpath_intact(self):
        """Детерминированный роутинг памяти не сломан."""
        res = self.agent.process("что ты помнишь")
        self.assertEqual(res["type"], "chat")
        self.assertEqual(res["answer"], "Память пуста.")

    def test_deterministic_router_plan_fastpath_intact(self):
        """Команда получения плана не сломана."""
        res = self.agent.process("покажи план")
        self.assertEqual(res["type"], "plan")


if __name__ == "__main__":
    unittest.main()
