"""
Тесты маршрутизации и интеграции сценария генерации изображений:
Agent.process() / router -> ImageAgent.

Проверяет:
1. Распознавание интентов генерации изображений в CommandRouter.
2. Корректное извлечение чистого текстового промпта (prompt) без служебных префиксов.
3. Отсутствие ложных срабатываний (вопросы об изображениях, бытовые команды, планы).
4. Передачу запроса в ImageAgent через Agent.run_subagent.
5. Корректное формирование успешного результата (PNG, created_files, answer).
6. Корректную обработку ошибок (ComfyUI недоступен) без падений и необработанных исключений.
7. Сверхнизкую задержку маршрутизации (< 1 мс).
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.router import CommandRouter
from tools.agent import Agent
from tools.agents.result import AgentResult
from tools.agents.context import AgentContext
from tools.agents.base import SubAgent


class DummyTestImageAgent(SubAgent):
    """Тестовый агент для проверки вызова через run_subagent."""
    name = "image"
    description = "Test image agent"

    def __init__(self, should_succeed=True, fail_error="ComfyUI offline"):
        super().__init__()
        self.should_succeed = should_succeed
        self.fail_error = fail_error
        self.last_context = None

    def run(self, context: AgentContext) -> AgentResult:
        self.last_context = context
        if self.should_succeed:
            return AgentResult.ok(
                message="Изображение успешно сгенерировано: img_test_123.png",
                created_files=["C:/Akakiy agent/data/generated/images/img_test_123.png"],
                data={"prompt": context.task}
            )
        else:
            return AgentResult.fail(
                error=self.fail_error,
                data={"prompt": context.task}
            )


class TestImageRouterPatterns(unittest.TestCase):
    """Проверка шаблонов и извлечения промпта в CommandRouter."""

    def setUp(self):
        self.router = CommandRouter()

    def test_positive_image_patterns(self):
        cases = [
            ("создай изображение кота в космосе", "кота в космосе"),
            ("сгенерируй картинку средневекового замка", "средневекового замка"),
            ("нарисуй лес ночью", "лес ночью"),
            ("сделай изображение робота", "робота"),
            ("нарисуй мне рыжего кота", "рыжего кота"),
            ("сгенерируй фото заката", "заката"),
            ("изобрази футуристический город", "футуристический город"),
            ("Акакий, нарисуй мне замок", "замок"),
            ("создай изображение: кот в очках", "кот в очках"),
            ("сделай картинку заката над океаном", "заката над океаном"),
            ("нарисуй мне, пожалуйста, чашку кофе", "чашку кофе"),
            ("создать изображение красивого сада", "красивого сада"),
            ("нарисовать горы на рассвете", "горы на рассвете"),
        ]

        for query, expected_prompt in cases:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertEqual(route.get("type"), "image", f"Query '{query}' was not routed to 'image'")
                self.assertEqual(route.get("prompt"), expected_prompt)

    def test_negative_patterns_not_triggering_image(self):
        cases = [
            "что такое изображение?",
            "как работает генерация изображений?",
            "почему ты не умеешь рисовать?",
            "создай заметку купить картину",
            "создай задачу нарисовать логотип",
            "создай план: нарисовать пейзаж",
            "найди файл картинка.png",
            "нарисуй",
            "сгенерируй изображение",
            "Привет, как дела?",
        ]

        for query in cases:
            with self.subTest(query=query):
                route = self.router.route(query)
                self.assertNotEqual(
                    route.get("type"),
                    "image",
                    f"Query '{query}' falsely triggered image route!"
                )

    def test_routing_latency(self):
        """Проверка латентности: распознавание запроса к изображению должно занимать < 1 мс."""
        t0 = time.perf_counter()
        route = self.router.route("создай изображение кота в космосе")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertEqual(route.get("type"), "image")
        self.assertLess(elapsed_ms, 1.0, f"Latency {elapsed_ms:.3f} ms exceeds 1.0 ms")


class TestAgentImageProcessIntegration(unittest.TestCase):
    """Проверка вызова ImageAgent из Agent.process()."""

    def setUp(self):
        self.mock_ai = MagicMock()
        self.mock_ai.send_chat.return_value = {"content": "Ответ от LLM"}
        self.agent = Agent(ai_client=self.mock_ai)

    def test_successful_image_generation_flow(self):
        test_agent = DummyTestImageAgent(should_succeed=True)
        self.agent.agent_registry.register(test_agent)

        res = self.agent.process("создай изображение кота в космосе")

        # 1. Проверяем структуру ответа
        self.assertEqual(res.get("type"), "image")
        self.assertTrue(res.get("success"))
        self.assertIn("img_test_123.png", res.get("answer", ""))
        self.assertEqual(len(res.get("created_files", [])), 1)
        self.assertIn("img_test_123.png", res["created_files"][0])

        # 2. Проверяем, что ImageAgent получил чистый prompt
        self.assertIsNotNone(test_agent.last_context)
        self.assertEqual(test_agent.last_context.task, "кота в космосе")

        # 3. LLM не вызывался
        self.assertFalse(self.mock_ai.send_chat.called)

        # 4. Проверяем фиксацию в истории сообщений (ContextManager)
        recent_turns = list(self.agent.context_manager._turns)
        self.assertEqual(len(recent_turns), 1)
        self.assertEqual(recent_turns[0]["user"], "создай изображение кота в космосе")
        self.assertIn("img_test_123.png", recent_turns[0]["assistant"])
        self.assertEqual(recent_turns[0]["tool"], "image")

    def test_failed_image_generation_handles_gracefully(self):
        fail_msg = "Локальный ComfyUI Worker недоступен по адресу http://127.0.0.1:8188."
        test_agent = DummyTestImageAgent(should_succeed=False, fail_error=fail_msg)
        self.agent.agent_registry.register(test_agent)

        res = self.agent.process("нарисуй лес ночью")

        # 1. Проверяем структуру ответа при ошибке
        self.assertEqual(res.get("type"), "image")
        self.assertFalse(res.get("success"))
        self.assertIn("Ошибка генерации изображения", res.get("answer", ""))
        self.assertIn(fail_msg, res.get("answer", ""))
        self.assertEqual(res.get("error"), fail_msg)
        self.assertEqual(res.get("created_files"), [])

        # 2. LLM не вызывался
        self.assertFalse(self.mock_ai.send_chat.called)

    def test_unregistered_image_agent_handles_cleanly(self):
        # Если ImageAgent отключен или разрегистрирован
        self.agent.agent_registry.unregister("image")

        res = self.agent.process("создай изображение кота")
        self.assertEqual(res.get("type"), "image")
        self.assertFalse(res.get("success"))
        self.assertIn("Ошибка генерации изображения", res.get("answer", ""))
        self.assertIn("не найден в реестре", res.get("error", ""))

    def test_prompt_punctuation_and_casing(self):
        cases = [
            ("СОЗДАЙ ИЗОБРАЖЕНИЕ КОТА В КОСМОСЕ", "КОТА В КОСМОСЕ"),
            ("Нарисуй Лес Ночью...", "Лес Ночью"),
            ("сделай картинку: закат на море!?", "закат на море"),
            ("нарисуй рисунок цветущей сакуры.", "цветущей сакуры"),
            ("сгенерируй иллюстрацию космического корабля", "космического корабля"),
            ("сделай арт неоновый самурай", "неоновый самурай"),
        ]
        for query, expected_prompt in cases:
            with self.subTest(query=query):
                route = self.agent.router.route(query)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("prompt"), expected_prompt)


if __name__ == "__main__":
    unittest.main()
