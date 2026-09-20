"""
Набор автоматизированных тестов для Skills Architecture 1.0 (Task 35).

Проверяет:
1. Регистрацию валидных навыков и отклонение невалидных (пустое имя, неизвестные инструменты).
2. Поиск и получение навыков в SkillRegistry.
3. Выбор и сопоставление навыка 'project' для проектных запросов.
4. Выбор и сопоставление навыка 'memory' для запросов к памяти.
5. Отсутствие дублирования инструментов (инструменты и схемы берутся из tools.registry).
6. Общий ContextManager (отсутствие собственной истории, единый трекинг контекста).
7. Отсутствие второго OllamaClient (навыки не создают клиентов).
8. Обычный разговорный чат без привязки к навыкам и без искажения системного промпта.
9. Native Tool Calling с навыком: передача скоупированных инструментов и контекста навыка.
10. Контроль подтверждений (requires_confirmation в Dispatcher сохраняется).
11. Обработку отмены пользователем при выполнении инструмента.
12. Динамическое включение и отключение навыков без изменения ядра Agent.
13. Потокобезопасность SkillRegistry при конкурентных операциях.
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.registry import TOOLS, get_tools_schema
from tools.context import ContextManager
from tools.memory import MemoryManager
from tools.dispatcher import set_confirmation_handler, get_confirmation_handler
from tools.agent import Agent

from skills.base import BaseSkill
from skills.registry import SkillRegistry, get_skill_registry, reset_skill_registry
from skills.project import ProjectSkill
from skills.memory import MemorySkill


class TestSkillRegistrationAndValidation(unittest.TestCase):
    """1. Регистрация и валидация навыков."""

    def setUp(self):
        reset_skill_registry()

    def tearDown(self):
        reset_skill_registry()

    def test_skill_registration_valid(self):
        registry = SkillRegistry()
        skill = ProjectSkill()
        registry.register(skill)

        self.assertIs(registry.get("project"), skill)
        self.assertEqual(len(registry.get_all()), 1)

    def test_skill_registration_empty_name(self):
        registry = SkillRegistry()
        skill = BaseSkill(name="", tools=["list_files"])

        with self.assertRaises(ValueError):
            registry.register(skill)

    def test_skill_registration_unknown_tool(self):
        registry = SkillRegistry()
        skill = BaseSkill(name="alien", tools=["unknown_nonexistent_tool_xyz"])

        with self.assertRaises(ValueError):
            registry.register(skill)

    def test_skill_unregister(self):
        registry = SkillRegistry()
        skill = ProjectSkill()
        registry.register(skill)
        self.assertIsNotNone(registry.get("project"))

        removed = registry.unregister("project")
        self.assertIs(removed, skill)
        self.assertIsNone(registry.get("project"))


class TestToolReusabilityAndSchemas(unittest.TestCase):
    """2. Отсутствие дублирования инструментов и проверка схем."""

    def test_skills_tools_exist_in_registry(self):
        project_skill = ProjectSkill()
        memory_skill = MemorySkill()

        # Все инструменты навыков обязаны существовать в tools.registry.TOOLS
        for t in project_skill.tools:
            self.assertIn(t, TOOLS, f"Инструмент {t} отсутствует в TOOLS")

        for t in memory_skill.tools:
            self.assertIn(t, TOOLS, f"Инструмент {t} отсутствует в TOOLS")

    def test_get_tools_schema_filtering(self):
        project_skill = ProjectSkill()
        memory_skill = MemorySkill()

        all_schemas = get_tools_schema()
        project_schemas = project_skill.get_tools_schema()
        memory_schemas = memory_skill.get_tools_schema()

        self.assertEqual(len(project_schemas), len(project_skill.tools))
        self.assertEqual(len(memory_schemas), len(memory_skill.tools))
        self.assertEqual(len(all_schemas), len(TOOLS))

        proj_names = {s["function"]["name"] for s in project_schemas}
        self.assertEqual(proj_names, set(project_skill.tools))

        mem_names = {s["function"]["name"] for s in memory_schemas}
        self.assertEqual(mem_names, set(memory_skill.tools))


class TestSkillMatchingAndRouting(unittest.TestCase):
    """3. Детерминированный выбор 'project' и 'memory', и пропуск обычного чата."""

    def setUp(self):
        reset_skill_registry()
        self.registry = get_skill_registry()

    def tearDown(self):
        reset_skill_registry()

    def test_matching_project_skill(self):
        project_queries = [
            "Найди в проекте функцию validate_project",
            "Покажи структуру проекта",
            "Прочитай файл config.py",
            "В каком файле находится класс Agent?",
            "Поиск по проекту слова ContextManager",
            "Проанализируй файл tools/agent.py"
        ]

        for q in project_queries:
            matched = self.registry.find_matching_skill(q)
            self.assertIsNotNone(matched, f"Запрос '{q}' должен был сопоставиться с навыком")
            self.assertEqual(matched.name, "project", f"Запрос '{q}' сопоставился с '{matched.name}'")

    def test_matching_memory_skill(self):
        memory_queries = [
            "Запомни что я люблю чай с мятой",
            "Что ты помнишь обо мне?",
            "Покажи список памяти",
            "Вспомни какой у меня пароль",
            "Забудь запись номер 1",
            "Что сохранено в памяти?"
        ]

        for q in memory_queries:
            matched = self.registry.find_matching_skill(q)
            self.assertIsNotNone(matched, f"Запрос '{q}' должен был сопоставиться с навыком")
            self.assertEqual(matched.name, "memory", f"Запрос '{q}' сопоставился с '{matched.name}'")

    def test_casual_chat_matches_no_skill(self):
        casual_queries = [
            "Привет, как твои дела?",
            "Какая сегодня погода?",
            "Расскажи интересную шутку",
            "Кто открыл закон всемирного тяготения?",
            "Что такое гравитация?",
            "Спасибо за помощь!"
        ]

        for q in casual_queries:
            matched = self.registry.find_matching_skill(q)
            self.assertIsNone(matched, f"Обычный диалог '{q}' не должен сопоставляться с навыком")


class TestDynamicSkillToggling(unittest.TestCase):
    """4. Динамическое включение и отключение навыков."""

    def setUp(self):
        reset_skill_registry()
        self.registry = get_skill_registry()

    def tearDown(self):
        reset_skill_registry()

    def test_dynamic_enable_disable(self):
        query = "Найди в проекте файл main.py"

        matched = self.registry.find_matching_skill(query)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.name, "project")

        # Отключаем навык
        self.registry.disable("project")
        self.assertIsNone(self.registry.find_matching_skill(query))

        # Включаем обратно
        self.registry.enable("project")
        matched_again = self.registry.find_matching_skill(query)
        self.assertIsNotNone(matched_again)
        self.assertEqual(matched_again.name, "project")


class TestArchitectureIsolationAndContext(unittest.TestCase):
    """5. Отсутствие отдельного клиента/истории и общий ContextManager."""

    def test_skills_have_no_client_or_history(self):
        project_skill = ProjectSkill()
        memory_skill = MemorySkill()

        self.assertFalse(hasattr(project_skill, "ai"))
        self.assertFalse(hasattr(project_skill, "client"))
        self.assertFalse(hasattr(project_skill, "history"))
        self.assertFalse(hasattr(project_skill, "messages"))

        self.assertFalse(hasattr(memory_skill, "ai"))
        self.assertFalse(hasattr(memory_skill, "client"))
        self.assertFalse(hasattr(memory_skill, "history"))
        self.assertFalse(hasattr(memory_skill, "messages"))

    def test_unified_context_manager_with_skill(self):
        mem_mgr = MemoryManager(storage_path=None)
        ctx = ContextManager(memory_manager=mem_mgr)

        # Запрос без навыка (обычный)
        msgs_normal = ctx.build_messages_for_llm("Привет, Акакий")
        self.assertEqual(len(msgs_normal), 2)
        self.assertNotIn("project", msgs_normal[0]["content"])

        # Запрос с контекстом навыка project
        project_skill = ProjectSkill()
        msgs_skill = ctx.build_messages_for_llm(
            "Найди файл main.py",
            extra_system_instruction=project_skill.system_prompt
        )
        self.assertEqual(len(msgs_skill), 2)
        self.assertIn("project", msgs_skill[0]["content"])
        self.assertIn("list_files", msgs_skill[0]["content"])

        # Базовый системный промпт не изменился
        self.assertEqual(ctx.get_system_prompt(), ctx.base_system_prompt)


class TestAgentSkillIntegration(unittest.TestCase):
    """6. Интеграция с Agent, Native Tool Calling и безопасность."""

    def setUp(self):
        reset_skill_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_mem.json"
        self.mem_mgr = MemoryManager(storage_path=self.storage_path)
        self.ctx = ContextManager(memory_manager=self.mem_mgr)

    def tearDown(self):
        self.temp_dir.cleanup()
        reset_skill_registry()

    def test_agent_scopes_tools_when_skill_selected(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {
            "content": "Точка входа находится в main.py",
            "tool_calls": []
        }

        agent = Agent(memory_manager=self.mem_mgr, context_manager=self.ctx, ai_client=mock_ai)

        resp = agent.process("Подскажи, в каком файле проекта находится точка входа?")
        self.assertEqual(resp["type"], "chat")
        self.assertEqual(resp["answer"], "Точка входа находится в main.py")

        self.assertTrue(mock_ai.send_chat.called)
        call_args = mock_ai.send_chat.call_args
        passed_tools = call_args[1]["tools"]
        passed_messages = call_args[0][0]

        # Схема должна содержать только инструменты project
        passed_names = {t["function"]["name"] for t in passed_tools}
        self.assertEqual(passed_names, set(ProjectSkill().tools))
        self.assertNotIn("git_commit", passed_names)
        self.assertNotIn("remember", passed_names)

        # Системное сообщение содержит инструкции навыка
        self.assertIn("project", passed_messages[0]["content"])

    def test_agent_uses_all_tools_for_ambiguous_query(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {
            "content": "Готов помочь.",
            "tool_calls": []
        }

        agent = Agent(memory_manager=self.mem_mgr, context_manager=self.ctx, ai_client=mock_ai)

        resp = agent.process("Сделай что-нибудь полезное для системы")
        self.assertEqual(resp["type"], "chat")

        call_args = mock_ai.send_chat.call_args
        passed_tools = call_args[1]["tools"]
        passed_names = {t["function"]["name"] for t in passed_tools}

        # Все инструменты из TOOLS должны быть доступны
        self.assertEqual(len(passed_names), len(TOOLS))

    def test_agent_casual_chat_unaffected(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {
            "content": "Привет! Чем могу помочь?",
            "tool_calls": []
        }

        agent = Agent(memory_manager=self.mem_mgr, context_manager=self.ctx, ai_client=mock_ai)

        resp = agent.process("Привет, Акакий!")
        self.assertEqual(resp["type"], "chat")
        self.assertIn("Привет!", resp["answer"])

        call_args = mock_ai.send_chat.call_args
        passed_messages = call_args[0][0]
        # Нет навязывания инструкций навыка в системный промпт
        self.assertNotIn("навык 'project'", passed_messages[0]["content"])
        self.assertNotIn("навык 'memory'", passed_messages[0]["content"])

    def test_confirmation_and_cancellation_preserved(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "run_command",
                    "arguments": {"command": "dir"}
                }
            }]
        }

        old_handler = get_confirmation_handler()
        set_confirmation_handler(lambda tool_name, kwargs: False)

        try:
            agent = Agent(memory_manager=self.mem_mgr, context_manager=self.ctx, ai_client=mock_ai)
            resp = agent.process("Выполни команду dir через терминал")
            self.assertEqual(resp["type"], "tool")
            self.assertFalse(resp["result"]["success"])
            self.assertIn("отменил", resp["result"]["error"])
        finally:
            set_confirmation_handler(old_handler)


class TestSkillRegistryConcurrency(unittest.TestCase):
    """7. Потокобезопасность SkillRegistry."""

    def test_skill_registry_thread_safety(self):
        registry = SkillRegistry()
        errors = []

        def worker(idx):
            try:
                skill = BaseSkill(name=f"skill_{idx}", tools=["list_files"])
                registry.register(skill)
                registry.get(f"skill_{idx}")
                registry.disable(f"skill_{idx}")
                registry.enable(f"skill_{idx}")
                registry.find_matching_skill("тест")
                registry.get_all()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(registry.get_all()), 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
