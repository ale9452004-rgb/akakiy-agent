"""
Модуль тестирования специализированного Sub-Agent'а PresentationAgent (Этап 7).

Проверяет:
1. Инициализацию, свойства и метаданные PresentationAgent;
2. Интеллектуальный разбор темы и структуры слайдов (parse_task);
3. Построение валидного Office OpenXML .pptx архива без внешних зависимостей;
4. Полный жизненный цикл run(AgentContext) -> AgentResult с Artifact типа presentation;
5. Обработку ошибок (невалидный контекст, отключенный агент, пустая тема);
6. Регистрацию PresentationAgent в AgentRegistry по умолчанию;
7. Маршрутизацию естественных и явных запросов создания презентации в CommandRouter.
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
    get_agent_registry,
    reset_agent_registry,
)
from tools.agents.presentation import PresentationAgent
from tools.router import CommandRouter, get_router


class TestPresentationAgent(unittest.TestCase):
    """1. Тестирование PresentationAgent и построения OpenXML .pptx."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = PresentationAgent(output_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_capabilities(self):
        """Проверка инициализации и заявленных возможностей."""
        self.assertEqual(self.agent.name, "presentation")
        self.assertTrue(self.agent.enabled)
        self.assertIn("presentation", self.agent.capabilities)
        self.assertIn("pptx", self.agent.capabilities)
        self.assertIn("slides", self.agent.capabilities)
        self.assertEqual(self.agent.output_dir, Path(self.temp_dir.name))

    def test_parse_task_from_simple_prompt(self):
        """Разбор темы из краткой текстовой команды."""
        title, subtitle, slides = self.agent.parse_task("создай презентацию на тему Искусственный Интеллект")
        self.assertEqual(title, "Искусственный Интеллект")
        self.assertIn("Акакий", subtitle)
        self.assertGreaterEqual(len(slides), 3)
        self.assertTrue(all("title" in s and "blocks" in s for s in slides))

    def test_parse_task_from_metadata_slides(self):
        """Использование явно переданных слайдов из метаданных."""
        meta = {
            "title": "Квартальный отчет",
            "subtitle": "Q3 2026",
            "slides": [
                {"title": "Результаты", "blocks": ["Пункт 1", "Пункт 2"]},
                {"title": "Планы", "blocks": ["Задача А", "Задача Б"]},
            ]
        }
        title, subtitle, slides = self.agent.parse_task("сделай отчет", metadata=meta)
        self.assertEqual(title, "Квартальный отчет")
        self.assertEqual(subtitle, "Q3 2026")
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0]["title"], "Результаты")
        self.assertEqual(slides[0]["blocks"], ["Пункт 1", "Пункт 2"])

    def test_parse_task_from_multiline_text(self):
        """Разбор структурированного многострочного текста задачи."""
        multiline_task = """
        Презентация: Архитектура проекта
        Слайд 1: Концепция
        - Микромодульная структура
        - Изоляция зависимостей
        Слайд 2: Безопасность
        - Защита памяти
        - Локальный инференс
        """
        title, subtitle, slides = self.agent.parse_task(multiline_task)
        self.assertIn("Архитектура проекта", title)
        self.assertEqual(len(slides), 2)
        self.assertEqual(slides[0]["title"], "Концепция")
        self.assertEqual(len(slides[0]["blocks"]), 2)
        self.assertEqual(slides[1]["title"], "Безопасность")

    def test_build_presentation_creates_valid_openxml_zip(self):
        """Сгенерированные байты презентации представляют собой валидный OpenXML zip-архив."""
        slides = [
            {
                "title": "Тестовый слайд & <спецсимволы>",
                "blocks": ["Строка 1 с амперсандом &", "Строка 2: 10 > 5"]
            }
        ]
        pptx_bytes = self.agent.build_presentation(
            title="Заголовок & Тест",
            slides=slides,
            subtitle="Подзаголовок 'Акакий'"
        )
        self.assertIsInstance(pptx_bytes, bytes)
        self.assertGreater(len(pptx_bytes), 1000)

        # Проверка целостности zip и синтаксиса всех XML-файлов
        buf = io.BytesIO(pptx_bytes)
        with zipfile.ZipFile(buf, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("[Content_Types].xml", namelist)
            self.assertIn("_rels/.rels", namelist)
            self.assertIn("ppt/presentation.xml", namelist)
            self.assertIn("ppt/slides/slide1.xml", namelist)
            self.assertIn("ppt/slides/slide2.xml", namelist)

            for name in namelist:
                if name.endswith(".xml") or name.endswith(".rels"):
                    content = zf.read(name)
                    # Проверяем, что XML успешно парсится стандартным парсером
                    root = ET.fromstring(content)
                    self.assertIsNotNone(root)

    def test_run_success_creates_file_and_artifact(self):
        """Успешный прогон run() сохраняет файл и возвращает AgentResult с Artifact."""
        ctx = AgentContext(
            task="создай презентацию по архитектуре Акакия",
            metadata={"subtitle": "Инженерный обзор"}
        )
        res = self.agent.run(ctx)

        self.assertIsInstance(res, AgentResult)
        self.assertTrue(res.success)
        self.assertIn("Презентация успешно создана", res.message)
        self.assertEqual(len(res.created_files), 1)

        saved_file = Path(res.created_files[0])
        self.assertTrue(saved_file.exists())
        self.assertTrue(saved_file.name.endswith(".pptx"))

        # Проверка модели Artifact
        self.assertEqual(len(res.artifacts), 1)
        art = res.artifacts[0]
        self.assertIsInstance(art, Artifact)
        self.assertEqual(art.type, ArtifactType.PRESENTATION)
        self.assertTrue(art.is_presentation)
        self.assertTrue(art.is_document)
        self.assertEqual(art.path, str(saved_file))
        self.assertTrue(art.exists())
        self.assertGreater(art.size_bytes, 1000)
        self.assertEqual(len(res.presentations), 1)

        # Проверка данных в data
        self.assertEqual(res.data.get("title"), "архитектуре Акакия")
        self.assertGreaterEqual(res.data.get("slides_count"), 2)

    def test_run_with_invalid_context_returns_fail(self):
        """Невалидный контекст возвращает AgentResult.fail."""
        res = self.agent.run("не AgentContext")
        self.assertFalse(res.success)
        self.assertIn("Некорректный контекст", res.error)

    def test_run_when_disabled_returns_fail(self):
        """Отключенный агент возвращает AgentResult.fail."""
        self.agent.enabled = False
        ctx = AgentContext(task="презентация")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_run_with_empty_task_returns_fail(self):
        """Пустая задача без метаданных возвращает AgentResult.fail."""
        ctx = AgentContext(task="")
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("Не указана тема", res.error)


class TestPresentationRegistryAndRouting(unittest.TestCase):
    """2. Тестирование регистрации и маршрутизации PresentationAgent."""

    def setUp(self):
        reset_agent_registry()
        self.router = CommandRouter()

    def tearDown(self):
        reset_agent_registry()

    def test_registry_contains_presentation_agent(self):
        """PresentationAgent автоматически зарегистрирован в AgentRegistry."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("presentation"))
        agent = reg.get("presentation")
        self.assertIsInstance(agent, PresentationAgent)

    def test_router_match_presentation_patterns(self):
        """Проверка естественных шаблонов распознавания презентации."""
        patterns = [
            ("создай презентацию по архитектуре проекта", "архитектуре проекта"),
            ("сделай презентацию на тему Квантовые компьютеры", "Квантовые компьютеры"),
            ("сгенерируй презентацию про космос", "космос"),
            ("подготовь презентацию о машинном обучении", "машинном обучении"),
            ("презентация: Итоги 2026 года", "Итоги 2026 года"),
            ("создай слайды по машинному зрению", "машинному зрению"),
            ("Акакий, пожалуйста, создай мне презентацию про нейросети", "нейросети"),
        ]
        for user_cmd, expected_topic in patterns:
            res = self.router.match_presentation(user_cmd)
            self.assertIsNotNone(res, f"Команда '{user_cmd}' не распознана match_presentation")
            self.assertEqual(res["action"], "create")
            self.assertEqual(res["prompt"], expected_topic)

    def test_router_route_integration(self):
        """CommandRouter.route() возвращает type: 'presentation'."""
        route = self.router.route("создай презентацию по проекту Акакий")
        self.assertEqual(route.get("type"), "presentation")
        self.assertEqual(route.get("action"), "create")
        self.assertEqual(route.get("prompt"), "проекту Акакий")

    def test_explicit_subagent_route(self):
        """Явный вызов субагента 'субагент presentation: ...' маршрутизируется в presentation."""
        route = self.router.route("субагент presentation: Краткий отчет")
        self.assertEqual(route.get("type"), "presentation")
        self.assertEqual(route.get("prompt"), "Краткий отчет")

    def test_non_image_target_protection(self):
        """Запросы на создание презентации не перехватываются ImageAgent."""
        img_res = self.router.match_image("создай презентацию с красивыми картинками")
        self.assertIsNone(img_res, "Запрос презентации не должен перехватываться match_image")


if __name__ == "__main__":
    unittest.main()
