"""
Модуль тестирования специализированного Sub-Agent'а ResearchAgent (Этап 9).

Проверяет:
1. Инициализацию, свойства и метаданные ResearchAgent;
2. Интеллектуальный разбор темы и исследовательских вопросов (parse_task);
3. Сбор информации по источникам и формирование Markdown отчёта;
4. Полный жизненный цикл run(AgentContext) -> AgentResult с Artifact типа text/document;
5. Обработку ошибок (невалидный контекст, отключенный агент, пустая задача);
6. Регистрацию ResearchAgent в AgentRegistry по умолчанию;
7. Маршрутизацию естественных и явных запросов исследования в CommandRouter;
8. Интеграцию с Agent.process().
"""

import tempfile
import unittest
from pathlib import Path

from tools.agents import (
    AgentContext,
    AgentResult,
    AgentRegistry,
    Artifact,
    ArtifactType,
    ResearchAgent,
    get_agent_registry,
    reset_agent_registry,
)
from tools.router import CommandRouter


class TestResearchAgent(unittest.TestCase):
    """1. Тестирование ResearchAgent, сбора информации и формирования отчёта."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = ResearchAgent(output_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_capabilities(self):
        """Проверка инициализации и заявленных возможностей."""
        self.assertEqual(self.agent.name, "research")
        self.assertTrue(self.agent.enabled)
        self.assertIn("research", self.agent.capabilities)
        self.assertIn("search", self.agent.capabilities)
        self.assertIn("analysis", self.agent.capabilities)
        self.assertEqual(self.agent.output_dir, Path(self.temp_dir.name))

    def test_parse_task_from_simple_prompt(self):
        """Разбор темы из краткой текстовой команды."""
        topic, questions, sources = self.agent.parse_task("исследуй тему: архитектура микросервисов")
        self.assertEqual(topic, "архитектура микросервисов")
        self.assertGreaterEqual(len(questions), 3)
        self.assertTrue(all(isinstance(q, str) and len(q) > 0 for q in questions))

    def test_parse_task_from_metadata_questions(self):
        """Использование явно переданных вопросов из метаданных."""
        meta = {
            "topic": "Подсистема памяти",
            "questions": [
                "Как устроен MemoryManager?",
                "Как сохраняются факты?"
            ],
            "sources": ["data/memory.json"]
        }
        topic, questions, sources = self.agent.parse_task("проведи исследование", metadata=meta)
        self.assertEqual(topic, "Подсистема памяти")
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0], "Как устроен MemoryManager?")
        self.assertEqual(sources, ["data/memory.json"])

    def test_parse_task_from_multiline_text(self):
        """Разбор структурированного многострочного текста задачи с вопросами."""
        multiline_task = """
        Исследование: Безопасность выполнения кода
        Вопрос 1: Какие ограничения накладываются на терминальные команды?
        Вопрос 2: Как устроен AST-анализ файлов?
        - Проверяется ли синтаксис py_compile?
        """
        topic, questions, sources = self.agent.parse_task(multiline_task)
        self.assertIn("Безопасность выполнения кода", topic)
        self.assertGreaterEqual(len(questions), 3)
        self.assertIn("Какие ограничения накладываются на терминальные команды?", questions[0])

    def test_gather_information_and_generate_report(self):
        """Сбор информации по локальным файлам и генерация Markdown отчёта."""
        # Создаем тестовый файл в temp_dir для анализа
        test_file = Path(self.temp_dir.name) / "test_doc.md"
        test_file.write_text("Архитектура системы построена на базе микромодулей и субагентов.", encoding="utf-8")

        topic = "Модульность архитектуры"
        questions = ["Каковы принципы модульности?"]
        findings, sources, summary = self.agent.gather_information(
            topic=topic,
            questions=questions,
            sources_hint=[str(test_file)]
        )

        self.assertGreaterEqual(len(sources), 1)
        self.assertEqual(len(findings), 1)
        self.assertIn("успешно выполнено", summary)

        report_md = self.agent.generate_report_markdown(
            topic=topic,
            questions=questions,
            findings=findings,
            sources=sources,
            summary=summary
        )
        self.assertIn(f"# Исследовательский отчёт: {topic}", report_md)
        self.assertIn("## 1. Краткий итог (Executive Summary)", report_md)
        self.assertIn("## 2. Результаты исследования по вопросам", report_md)
        self.assertIn("## 3. Использованные источники и материалы", report_md)

    def test_run_success_creates_file_and_artifact(self):
        """Успешный запуск run() сохраняет отчёт и возвращает AgentResult с Artifact."""
        ctx = AgentContext(
            task="исследуй подсистему субагентов",
            metadata={"questions": ["Как работает AgentContext?", "Как устроен AgentResult?"]}
        )
        res = self.agent.run(ctx)

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("успешно выполнено", res.message)
        self.assertEqual(len(res.created_files), 1)

        saved_file = Path(res.created_files[0])
        self.assertTrue(saved_file.exists())
        self.assertTrue(saved_file.name.endswith(".md"))

        # Проверка модели Artifact
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertIsInstance(art, Artifact)
        self.assertEqual(art.type, ArtifactType.TEXT)
        self.assertTrue(art.is_research)
        self.assertEqual(art.path, str(saved_file))
        self.assertTrue(art.exists())
        self.assertGreater(art.size_bytes, 100)
        self.assertEqual(len(res.research_reports), 1)

        # Проверка данных в data
        self.assertEqual(res.data.get("topic"), "подсистему субагентов")
        self.assertEqual(len(res.data.get("questions")), 2)
        self.assertIn("report_content", res.data)

    def test_run_with_invalid_context_returns_fail(self):
        """Невалидный контекст возвращает AgentResult.fail."""
        res = self.agent.run("не AgentContext")
        self.assertFalse(res.success)
        self.assertIn("Некорректный контекст", res.error)

    def test_run_when_disabled_returns_fail(self):
        """Отключенный агент возвращает AgentResult.fail."""
        self.agent.enabled = False
        ctx = AgentContext(task="исследование")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_run_with_empty_task_returns_fail(self):
        """Пустая задача без метаданных возвращает AgentResult.fail."""
        ctx = AgentContext(task="")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("Не указана тема", res.error)


class TestResearchRegistryAndRouting(unittest.TestCase):
    """2. Тестирование регистрации и маршрутизации ResearchAgent."""

    def setUp(self):
        reset_agent_registry()
        self.router = CommandRouter()

    def tearDown(self):
        reset_agent_registry()

    def test_registry_contains_research_agent(self):
        """ResearchAgent автоматически зарегистрирован в AgentRegistry."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("research"))
        agent = reg.get("research")
        self.assertIsInstance(agent, ResearchAgent)

    def test_router_match_research_patterns(self):
        """Проверка естественных шаблонов распознавания команд исследования."""
        patterns = [
            ("исследуй архитектуру проекта", "архитектуру проекта"),
            ("проведи исследование на тему Квантовые вычисления", "Квантовые вычисления"),
            ("сделай исследование по производительности", "производительности"),
            ("исследование: Асинхронные очереди", "Асинхронные очереди"),
            ("исследование на тему Базы данных", "Базы данных"),
            ("найди информацию по машинному зрению", "машинному зрению"),
            ("Акакий, пожалуйста, проведи мне исследование про нейросети", "нейросети"),
        ]
        for user_cmd, expected_topic in patterns:
            res = self.router.match_research(user_cmd)
            self.assertIsNotNone(res, f"Команда '{user_cmd}' не распознана match_research")
            self.assertEqual(res["action"], "research")
            self.assertEqual(res["prompt"], expected_topic)

    def test_router_route_integration(self):
        """CommandRouter.route() возвращает type: 'research'."""
        route = self.router.route("исследуй архитектуру проекта Акакий")
        self.assertEqual(route.get("type"), "research")
        self.assertEqual(route.get("action"), "research")
        self.assertEqual(route.get("prompt"), "архитектуру проекта Акакий")

    def test_explicit_subagent_route(self):
        """Явный вызов субагента 'субагент research: ...' маршрутизируется в research."""
        route = self.router.route("субагент research: Анализ памяти")
        self.assertEqual(route.get("type"), "research")
        self.assertEqual(route.get("prompt"), "Анализ памяти")

    def test_non_image_target_protection(self):
        """Запросы на исследование не перехватываются ImageAgent."""
        img_res = self.router.match_image("сделай исследование с красивыми картинками")
        self.assertIsNone(img_res, "Запрос исследования не должен перехватываться match_image")

    def test_agent_process_research_routing(self):
        """Интеграционная проверка вызова ResearchAgent через Agent.process()."""
        from unittest.mock import MagicMock
        from tools.agent import Agent

        mock_ai = MagicMock()
        mock_mem = MagicMock()
        main_agent = Agent(ai_client=mock_ai, memory_manager=mock_mem)

        with tempfile.TemporaryDirectory() as tmp_out:
            res_agent = ResearchAgent(output_dir=tmp_out)
            main_agent.agent_registry.register(res_agent)

            result = main_agent.process("исследуй архитектуру проекта")
            self.assertEqual(result["type"], "research")
            self.assertTrue(result["success"])
            self.assertIn("успешно выполнено", result["answer"])
            self.assertEqual(len(result["created_files"]), 1)
            self.assertTrue(result["created_files"][0].endswith(".md"))
            self.assertTrue(Path(result["created_files"][0]).exists())
            self.assertEqual(len(result["artifacts"]), 1)
            self.assertEqual(result["artifacts"][0]["type"], "text")
            self.assertTrue(result["result"].artifacts[0].is_research)


if __name__ == "__main__":
    unittest.main()
