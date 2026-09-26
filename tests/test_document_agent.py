"""
Модуль тестирования специализированного Sub-Agent'а DocumentAgent (Этап 8).

Проверяет:
1. Инициализацию, свойства и метаданные DocumentAgent;
2. Интеллектуальный разбор темы и структуры документа (parse_task);
3. Построение валидного Office OpenXML .docx архива без внешних зависимостей;
4. Полный жизненный цикл run(AgentContext) -> AgentResult с Artifact типа document;
5. Обработку ошибок (невалидный контекст, отключенный агент, пустая тема);
6. Регистрацию DocumentAgent в AgentRegistry по умолчанию;
7. Маршрутизацию естественных и явных запросов создания документа в CommandRouter.
"""

import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tools.agents import (
    AgentContext,
    AgentResult,
    AgentRegistry,
    Artifact,
    ArtifactType,
    DocumentAgent,
    get_agent_registry,
    reset_agent_registry,
)
from tools.router import CommandRouter, get_router


class TestDocumentAgent(unittest.TestCase):
    """1. Тестирование DocumentAgent и построения OpenXML .docx."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = DocumentAgent(output_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_capabilities(self):
        """Проверка инициализации и заявленных возможностей."""
        self.assertEqual(self.agent.name, "document")
        self.assertTrue(self.agent.enabled)
        self.assertIn("document", self.agent.capabilities)
        self.assertIn("docx", self.agent.capabilities)
        self.assertIn("word", self.agent.capabilities)
        self.assertIn("text", self.agent.capabilities)
        self.assertIn("report", self.agent.capabilities)
        self.assertEqual(self.agent.output_dir, Path(self.temp_dir.name))

    def test_parse_task_from_simple_prompt(self):
        """Разбор темы из краткой текстовой команды."""
        title, subtitle, sections = self.agent.parse_task("создай документ на тему Архитектура микросервисов")
        self.assertEqual(title, "Архитектура микросервисов")
        self.assertIn("Акакий", subtitle)
        self.assertGreaterEqual(len(sections), 3)
        self.assertTrue(all("heading" in s and "paragraphs" in s and "bullets" in s for s in sections))

    def test_parse_task_from_metadata_sections(self):
        """Использование явно переданных разделов из метаданных."""
        meta = {
            "title": "Техническое задание",
            "subtitle": "Редакция 1.0",
            "sections": [
                {
                    "heading": "1. Цели проекта",
                    "paragraphs": ["Цель проекта - создание отказоустойчивой системы."],
                    "bullets": ["Снижение задержек", "Повышение доступности"]
                },
                {
                    "heading": "2. Стек технологий",
                    "paragraphs": ["В проекте используется Python 3.13."],
                    "bullets": ["Без сторонних библиотек для генерации docx"]
                },
            ]
        }
        title, subtitle, sections = self.agent.parse_task("сделай тз", metadata=meta)
        self.assertEqual(title, "Техническое задание")
        self.assertEqual(subtitle, "Редакция 1.0")
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["heading"], "1. Цели проекта")
        self.assertEqual(len(sections[0]["paragraphs"]), 1)
        self.assertEqual(len(sections[0]["bullets"]), 2)
        self.assertEqual(sections[1]["heading"], "2. Стек технологий")

    def test_parse_task_from_multiline_text(self):
        """Разбор структурированного многострочного текста задачи."""
        multiline_task = """
        Документ: Архитектура проекта
        Раздел 1: Концепция
        В данном разделе описывается базовая концепция.
        - Микромодульная структура
        - Изоляция зависимостей
        Раздел 2: Безопасность
        Применяются современные стандарты безопасности.
        - Защита памяти
        - Локальный инференс
        """
        title, subtitle, sections = self.agent.parse_task(multiline_task)
        self.assertIn("Архитектура проекта", title)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["heading"], "Концепция")
        self.assertEqual(len(sections[0]["paragraphs"]), 1)
        self.assertEqual(len(sections[0]["bullets"]), 2)
        self.assertEqual(sections[1]["heading"], "Безопасность")
        self.assertEqual(len(sections[1]["bullets"]), 2)

    def test_build_document_creates_valid_openxml_zip(self):
        """Сгенерированные байты документа представляют собой валидный OpenXML zip-архив."""
        sections = [
            {
                "heading": "Тестовый раздел & <спецсимволы>",
                "paragraphs": ["Абзац 1 с амперсандом &", "Абзац 2: 10 > 5 и a < b"],
                "bullets": ["Пункт 1: кавычки \"тест\"", "Пункт 2: апостроф 'значение'"]
            }
        ]
        docx_bytes = self.agent.build_document(
            title="Заголовок & Тест документа",
            sections=sections,
            subtitle="Подзаголовок 'Акакий'"
        )
        self.assertIsInstance(docx_bytes, bytes)
        self.assertGreater(len(docx_bytes), 1000)

        # Проверка целостности zip и синтаксиса всех XML-файлов
        buf = io.BytesIO(docx_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("[Content_Types].xml", namelist)
            self.assertIn("_rels/.rels", namelist)
            self.assertIn("word/_rels/document.xml.rels", namelist)
            self.assertIn("word/settings.xml", namelist)
            self.assertIn("word/styles.xml", namelist)
            self.assertIn("word/document.xml", namelist)

            for name in namelist:
                if name.endswith(".xml") or name.endswith(".rels"):
                    content = zf.read(name)
                    # Проверяем, что XML успешно парсится стандартным XML-парсером
                    root = ET.fromstring(content)
                    self.assertIsNotNone(root)

    def test_run_success_creates_file_and_artifact(self):
        """Успешный прогон run() сохраняет файл и возвращает AgentResult с Artifact."""
        ctx = AgentContext(
            task="создай документ по архитектуре Акакия",
            metadata={"subtitle": "Инженерный обзор"}
        )
        res = self.agent.run(ctx)

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("Документ успешно создан", res.message)
        self.assertEqual(len(res.created_files), 1)

        saved_file = Path(res.created_files[0])
        self.assertTrue(saved_file.exists())
        self.assertTrue(saved_file.name.endswith(".docx"))

        # Проверка модели Artifact
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertIsInstance(art, Artifact)
        self.assertEqual(art.type, ArtifactType.DOCUMENT)
        self.assertTrue(art.is_document)
        self.assertFalse(art.is_presentation)
        self.assertEqual(art.path, str(saved_file))
        self.assertTrue(art.exists())
        self.assertGreater(art.size_bytes, 1000)
        self.assertEqual(len(res.documents), 1)

        # Проверка данных в data
        self.assertEqual(res.data.get("title"), "архитектуре Акакия")
        self.assertGreaterEqual(res.data.get("sections_count"), 2)

    def test_run_with_invalid_context_returns_fail(self):
        """Невалидный контекст возвращает AgentResult.fail."""
        res = self.agent.run("не AgentContext")
        self.assertFalse(res.success)
        self.assertIn("Некорректный контекст", res.error)

    def test_run_when_disabled_returns_fail(self):
        """Отключенный агент возвращает AgentResult.fail."""
        self.agent.enabled = False
        ctx = AgentContext(task="документ")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_run_with_empty_task_returns_fail(self):
        """Пустая задача без метаданных возвращает AgentResult.fail."""
        ctx = AgentContext(task="")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("Не указана тема", res.error)


class TestDocumentRegistryAndRouting(unittest.TestCase):
    """2. Тестирование регистрации и маршрутизации DocumentAgent."""

    def setUp(self):
        reset_agent_registry()
        self.router = CommandRouter()

    def tearDown(self):
        reset_agent_registry()

    def test_registry_contains_document_agent(self):
        """DocumentAgent автоматически зарегистрирован в AgentRegistry."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("document"))
        agent = reg.get("document")
        self.assertIsInstance(agent, DocumentAgent)

    def test_router_match_document_patterns(self):
        """Проверка естественных шаблонов распознавания создания документа."""
        patterns = [
            ("создай документ по архитектуре проекта", "архитектуре проекта"),
            ("сделай документ на тему Квантовые вычисления", "Квантовые вычисления"),
            ("сгенерируй документ про космос", "космос"),
            ("подготовь документ о машинном обучении", "машинном обучении"),
            ("напиши документ по финансовому анализу", "финансовому анализу"),
            ("документ: Итоги 2026 года", "Итоги 2026 года"),
            ("документ на тему Отчет за квартал", "Отчет за квартал"),
            ("отчет: Годовые результаты", "Годовые результаты"),
            ("Акакий, пожалуйста, создай мне документ про нейросети", "нейросети"),
        ]
        for user_cmd, expected_topic in patterns:
            res = self.router.match_document(user_cmd)
            self.assertIsNotNone(res, f"Команда '{user_cmd}' не распознана match_document")
            self.assertEqual(res["action"], "create")
            self.assertEqual(res["prompt"], expected_topic)

    def test_router_route_integration(self):
        """CommandRouter.route() возвращает type: 'document'."""
        route = self.router.route("создай документ по проекту Акакий")
        self.assertEqual(route.get("type"), "document")
        self.assertEqual(route.get("action"), "create")
        self.assertEqual(route.get("prompt"), "проекту Акакий")

    def test_explicit_subagent_route(self):
        """Явный вызов субагента 'субагент document: ...' маршрутизируется в document."""
        route = self.router.route("субагент document: Краткий отчет")
        self.assertEqual(route.get("type"), "document")
        self.assertEqual(route.get("prompt"), "Краткий отчет")

    def test_non_image_target_protection(self):
        """Запросы на создание документа не перехватываются ImageAgent."""
        img_res = self.router.match_image("создай документ с красивыми картинками")
        self.assertIsNone(img_res, "Запрос документа не должен перехватываться match_image")

    def test_agent_process_document_routing(self):
        """Интеграционная проверка вызова DocumentAgent через Agent.process()."""
        from unittest.mock import MagicMock
        from tools.agent import Agent

        mock_ai = MagicMock()
        mock_mem = MagicMock()
        main_agent = Agent(ai_client=mock_ai, memory_manager=mock_mem)

        with tempfile.TemporaryDirectory() as tmp_out:
            doc_agent = DocumentAgent(output_dir=tmp_out)
            main_agent.agent_registry.register(doc_agent)

            result = main_agent.process("создай документ на тему Архитектура проекта")
            self.assertEqual(result["type"], "document")
            self.assertTrue(result["success"])
            self.assertIn("Документ успешно создан", result["answer"])
            self.assertEqual(len(result["created_files"]), 1)
            self.assertTrue(result["created_files"][0].endswith(".docx"))
            self.assertTrue(Path(result["created_files"][0]).exists())
            self.assertEqual(len(result["artifacts"]), 1)
            self.assertEqual(result["artifacts"][0]["type"], "document")


if __name__ == "__main__":
    unittest.main()
