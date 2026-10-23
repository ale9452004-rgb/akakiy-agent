"""
Тесты компилятора промптов (PromptCompiler), точности формирования positive/negative prompt для SDXL-Lightning
и обработки замечаний пользователя к результатам генерации.
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from tools.agents.context import AgentContext
from tools.agents.result import AgentResult
from tools.prompt_compiler import PromptCompiler, compile_image_prompt
from tools.router import CommandRouter


class TestPromptCompilerAccuracy(unittest.TestCase):
    """Тестирование точности компиляции positive и negative промптов."""

    def test_single_ginger_cat_beach_prompt(self):
        """
        Проверка целевого кейса:
        'Сгенерируй мне рыжего кота загорающего на пляжу у моря'
        - строго один кот (solo, single cat, 1cat);
        - выраженно рыжая шерсть (vibrant ginger fur, orange);
        - лежа/загорает на пляже у моря (sunbathing, sandy beach, sea in background);
        - запрет лишних котов и белой шерсти в negative prompt (multiple cats, two cats, white fur, extra animals).
        """
        query = "Сгенерируй мне рыжего кота загорающего на пляжу у моря"
        pos, neg, meta = compile_image_prompt(query)

        pos_lower = pos.lower()
        neg_lower = neg.lower()

        # 1. Проверка Positive Prompt:
        self.assertTrue(
            "single cat" in pos_lower or "solo" in pos_lower or "1cat" in pos_lower,
            f"Positive prompt must enforce single cat: {pos}"
        )
        self.assertTrue(
            "ginger" in pos_lower or "orange" in pos_lower,
            f"Positive prompt must specify ginger/orange fur: {pos}"
        )
        self.assertTrue(
            "sunbath" in pos_lower or "basking" in pos_lower or "relaxing" in pos_lower,
            f"Positive prompt must include sunbathing/relaxing action: {pos}"
        )
        self.assertTrue(
            "beach" in pos_lower or "sand" in pos_lower,
            f"Positive prompt must include beach/sand: {pos}"
        )
        self.assertTrue(
            "sea" in pos_lower or "ocean" in pos_lower or "water" in pos_lower,
            f"Positive prompt must include sea/ocean: {pos}"
        )

        # 2. Проверка Negative Prompt:
        self.assertIn(
            "multiple cats",
            neg_lower,
            f"Negative prompt must suppress multiple cats: {neg}"
        )
        self.assertIn(
            "two cats",
            neg_lower,
            f"Negative prompt must suppress two cats: {neg}"
        )
        self.assertIn(
            "white fur",
            neg_lower,
            f"Negative prompt must suppress white fur when ginger requested: {neg}"
        )
        self.assertIn(
            "extra animals",
            neg_lower,
            f"Negative prompt must suppress extra animals: {neg}"
        )

        # 3. Метаданные:
        self.assertEqual(meta.get("subject"), "cat")
        self.assertTrue(meta.get("is_singular"))

    def test_generalization_castle_mountains(self):
        """Проверка генерализации: замок в горах на закате (не кот)."""
        query = "нарисуй замок в горах на закате"
        pos, neg, meta = compile_image_prompt(query)

        pos_lower = pos.lower()
        neg_lower = neg.lower()

        self.assertEqual(meta.get("subject"), "castle")
        self.assertTrue("castle" in pos_lower)
        self.assertTrue("mountain" in pos_lower)
        self.assertTrue("sunset" in pos_lower or "golden hour" in pos_lower)

        # Негативный промпт для замка подавляет лишние замки
        self.assertIn("multiple castles", neg_lower)
        self.assertIn("two castles", neg_lower)

        # Не должен содержать кошачьих специфичных тегов
        self.assertNotIn("cats", pos_lower)
        self.assertNotIn("cats", neg_lower)

    def test_generalization_black_dog_snow(self):
        """Проверка генерализации: черная собака бежит по снегу."""
        query = "черная собака бежит по снегу"
        pos, neg, meta = compile_image_prompt(query)

        pos_lower = pos.lower()
        neg_lower = neg.lower()

        self.assertEqual(meta.get("subject"), "dog")
        self.assertTrue("black" in pos_lower)
        self.assertTrue("dog" in pos_lower)
        self.assertTrue("running" in pos_lower or "motion" in pos_lower)
        self.assertTrue("snow" in pos_lower or "winter" in pos_lower)

        # Негативный промпт подавляет лишних собак и белую/рыжую шерсть
        self.assertIn("multiple dogs", neg_lower)
        self.assertIn("white fur", neg_lower)
        self.assertIn("orange fur", neg_lower)

    def test_explicit_user_exclusions(self):
        """Проверка парсинга явных пользовательских исключений 'без белой шерсти, без других животных'."""
        query = "рыжий кот на траве без белой шерсти и без других животных"
        pos, neg, meta = compile_image_prompt(query)

        neg_lower = neg.lower()
        self.assertIn("white fur", neg_lower)
        self.assertIn("extra animals", neg_lower)

    def test_count_enforcement_multi(self):
        """Проверка явного запроса на 2 объекта: не должно подавлять два объекта."""
        query = "нарисуй двух кошек на окне"
        pos, neg, meta = compile_image_prompt(query, count=2)

        self.assertFalse(meta.get("is_singular"))
        neg_lower = neg.lower()
        # При явном запросе двух кошек мы не должны подавлять "two cats"
        self.assertNotIn("two cats", neg_lower)


class TestImageCritiqueRoutingAndHandling(unittest.TestCase):
    """Тестирование маршрутизации замечаний пользователя и отсутствия формальных отписок."""

    def setUp(self):
        self.router = CommandRouter()

    def test_critique_routes_to_revision_with_last_image(self):
        """
        Пользовательское замечание «Ты сгенерировал двух котов, а я просил одного и рыжего»
        должно маршрутизироваться в type: 'image', is_revision: True с объединением ограничений.
        """
        last_image = {
            "prompt": "рыжего кота загорающего на пляжу у моря",
            "created_files": ["data/generated/images/img_test.png"],
            "width": 1024,
            "height": 1024,
            "aspect_ratio": "square"
        }
        critique = "Ты сгенерировал двух котов, а я просил одного и рыжего"

        route = self.router.route(critique, last_image=last_image)

        self.assertEqual(route.get("type"), "image")
        self.assertTrue(route.get("is_revision"))
        self.assertEqual(route.get("count"), 1)

        # Проверяем, что промпт содержит как оригинальный контекст, так и замечание
        merged_prompt = route.get("prompt", "")
        self.assertIn("рыжего кота", merged_prompt)
        self.assertIn("одного", merged_prompt)

    def test_critique_routes_even_without_last_image(self):
        """
        Если в сообщении есть исчерпывающая критика ('двух котов, а я просил одного и рыжего'),
        маршрутизатор распознает запрос на ревизию даже без предыдущего кэша.
        """
        critique = "Ты сгенерировал двух котов, а я просил одного и рыжего"
        route = self.router.route(critique, last_image=None)

        self.assertEqual(route.get("type"), "image")
        self.assertTrue(route.get("is_revision"))
        self.assertEqual(route.get("count"), 1)

    def test_ambiguous_critique_routes_to_clarify(self):
        """
        Абстрактное замечание («Мне не нравится картинка») маршрутизируется в clarification,
        а не в генерацию вслепую.
        """
        last_image = {"prompt": "замок"}
        query = "Мне совсем не нравится эта картинка"
        route = self.router.route(query, last_image=last_image)

        self.assertEqual(route.get("type"), "image_feedback_clarify")
        self.assertFalse(route.get("is_revision"))

    def test_agent_process_critique_never_returns_generic_completion(self):
        """
        Ключевое требование: на замечание «Ты сгенерировал двух котов, а я просил одного и рыжего»
        Акакий НЕ должен отвечать 'Действие успешно завершено' или 'Действие успешно выполнено'.
        """
        from tools.agent import Agent

        # Инициализируем агента с моком ImageAgent
        agent = Agent()
        agent._last_image_result = {
            "prompt": "рыжего кота загорающего на пляжу у моря",
            "created_files": ["data/generated/images/old_cat.png"],
            "width": 1024,
            "height": 1024
        }

        # Мокаем run_subagent для симуляции успешной генерации нового изображения
        mock_subagent_res = AgentResult.ok(
            message="Изображение успешно сгенерировано: img_fixed_single_cat.png",
            created_files=["data/generated/images/img_fixed_single_cat.png"],
            data={"count": 1}
        )

        with patch.object(agent, "run_subagent", return_value=mock_subagent_res) as mock_run:
            critique = "Ты сгенерировал двух котов, а я просил одного и рыжего"
            result = agent.process(critique)

            self.assertEqual(result.get("type"), "image")
            self.assertTrue(result.get("success"))
            self.assertTrue(result.get("is_revision"))

            answer = result.get("answer", "")
            message = result.get("message", "")

            # Ни в answer, ни в message не должно быть абстрактной отписки
            self.assertNotIn("Действие успешно завершено", answer)
            self.assertNotIn("Действие успешно выполнено", answer)
            self.assertNotIn("Действие успешно завершено", message)
            self.assertNotIn("Действие успешно выполнено", message)

            # Ответ должен содержать информацию об исправлении
            self.assertIn("перегенерировал", answer.lower())
            self.assertIn("img_fixed_single_cat.png", answer)

            # Проверяем, что субагент был вызван с флагом is_revision=True
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            self.assertTrue(kwargs.get("is_revision"))

    def test_agent_process_critique_handles_failure_cleanly(self):
        """Если повторная генерация завершилась ошибкой, агент честно сообщает об ошибке."""
        from tools.agent import Agent

        agent = Agent()
        agent._last_image_result = {
            "prompt": "рыжего кота загорающего на пляжу у моря",
            "created_files": ["data/generated/images/old_cat.png"]
        }

        mock_fail_res = AgentResult.fail(
            error="ComfyUI Worker OOM",
            data={}
        )

        with patch.object(agent, "run_subagent", return_value=mock_fail_res):
            critique = "Ты сгенерировал двух котов, а я просил одного и рыжего"
            result = agent.process(critique)

            self.assertEqual(result.get("type"), "image")
            self.assertFalse(result.get("success"))

            answer = result.get("answer", "")
            self.assertIn("Ошибка генерации", answer)
            self.assertNotIn("Действие успешно завершено", answer)
            self.assertNotIn("Действие успешно выполнено", answer)


if __name__ == "__main__":
    unittest.main()
