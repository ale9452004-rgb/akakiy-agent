"""
Тесты маршрутизации и обработки сценариев редактирования ранее сгенерированных изображений:
Scenario A (generate), Scenario B (revise), Scenario C (edit).

Проверяет:
1. Чёткое разделение трёх сценариев в CommandRouter.
2. Распознавание модификаций (поза, фон, цвет, удаление объекта, 'оставь всё как есть').
3. Передачу пути к исходному PNG через Agent._last_image_result.
4. Защиту от ложных срабатываний (команды задач, кода, файлов, заметок).
5. Честное сообщение об отсутствующих моделях ControlNet OpenPose и Inpainting без утверждений 'PNG нельзя редактировать'.
6. Формирование валидного графа img2img и подготовку входного файла в workers/comfyui/input.
"""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.router import CommandRouter
from tools.agent import Agent
from tools.agents.context import AgentContext
from tools.agents.image import ImageAgent
from tools.agents.result import AgentResult


class TestImageEditRouting(unittest.TestCase):
    """Тестирование маршрутизатора для Scenario A, B, C."""

    def setUp(self):
        self.router = CommandRouter()
        self.dummy_last_image = {
            "prompt": "рыжий кот на пляже у моря",
            "created_files": ["C:/Akakiy agent/data/generated/images/img_dummy_cat.png"],
            "width": 1024,
            "height": 1024,
            "aspect_ratio": "1:1",
            "count": 1
        }

    def test_scenario_a_fresh_generation(self):
        """Сценарий A: генерация нового изображения с нуля без привязки к прошлому."""
        queries = [
            "сгенерируй кота на пляже",
            "нарисуй замок в горах",
            "создай изображение футуристического города",
            "изобрази космический корабль",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertIn(route.get("action"), (None, "generate", "create"))
                self.assertFalse(route.get("is_revision", False))

    def test_scenario_b_feedback_revision(self):
        """Сценарий B: ревизия / исправление промпта по замечанию."""
        queries = [
            "Ты сгенерировал двух котов, а я просил одного и рыжего",
            "Тут два кота вместо одного, переделай",
            "Не тот цвет, кот должен быть рыжим",
            "Переделай изображение: только один кот и ярко-рыжий",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "revise")
                self.assertTrue(route.get("is_revision"))

    def test_scenario_c_edit_pose(self):
        """Сценарий C: изменение позы персонажа."""
        queries = [
            "Поменяй позу коту в изображении, чтобы он лежал на спине",
            "Оставь всё как есть, поменяй только позу",
            "Поменяй позу на лежачую в изображении",
            "Измени позу кота на сидячую",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "edit")
                self.assertEqual(route.get("edit_type"), "pose")
                self.assertEqual(route.get("source_image_path"), "C:/Akakiy agent/data/generated/images/img_dummy_cat.png")

    def test_scenario_c_edit_color_and_style(self):
        """Сценарий C: изменение цвета, окраса, стиля."""
        queries = [
            "Сделай кота рыжим",
            "Перекрась кота в белый",
            "Поменяй цвет кота на черный",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "edit")
                self.assertEqual(route.get("edit_type"), "color")
                self.assertEqual(route.get("source_image_path"), "C:/Akakiy agent/data/generated/images/img_dummy_cat.png")

    def test_scenario_c_edit_remove_object(self):
        """Сценарий C: удаление лишнего объекта."""
        queries = [
            "Убери второго кота",
            "Удали лишнего кота на картинке",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "edit")
                self.assertEqual(route.get("edit_type"), "remove")

    def test_scenario_c_edit_background(self):
        """Сценарий C: изменение фона / окружения."""
        queries = [
            "Измени фон на лес",
            "Замени фон на море",
            "Поменяй фон на закат в изображении",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "edit")
                self.assertEqual(route.get("edit_type"), "background")

    def test_scenario_c_explicit_edit_command(self):
        """Сценарий C: явная команда редактирования через глагол."""
        queries = [
            "Отредактируй изображение: сделай собаку белой",
            "Поправь картинку: измени освещение на закатное",
        ]
        for q in queries:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertEqual(route.get("type"), "image")
                self.assertEqual(route.get("action"), "edit")

    def test_edit_without_last_image(self):
        """Если изображение не создавалось, но пользователь явно говорит об изображении."""
        route = self.router.route("Поменяй позу коту в изображении, чтобы он лежал на спине", last_image=None)
        self.assertEqual(route.get("type"), "image")
        self.assertEqual(route.get("action"), "edit")
        self.assertIsNone(route.get("source_image_path"))

    def test_non_image_collisions_avoided(self):
        """Защита от ложного перехвата команд других подсистем."""
        cases = [
            ("удали задачу 1", "tool", "delete_task"),
            ("сделай задачу купить молоко", "tool", "complete_task"),
            ("измени код в файле main.py", "coding", None),
            ("найди файл cat.png", "tool", "find_file"),
            ("покажи файлы проекта", "tool", "list_files"),
            ("создай заметку о встрече", "tool", "create_note"),
        ]
        for q, expected_type, expected_tool in cases:
            with self.subTest(query=q):
                route = self.router.route(q, last_image=self.dummy_last_image)
                self.assertNotEqual(route.get("action"), "edit")
                if expected_type == "tool":
                    self.assertEqual(route.get("type"), "tool")
                    self.assertEqual(route.get("tool"), expected_tool)
                elif expected_type == "coding":
                    self.assertEqual(route.get("type"), "coding")


class TestImageAgentCapabilitiesAndEdit(unittest.TestCase):
    """Тестирование возможностей ImageAgent, img2img и честной обработки отсутствующих моделей."""

    def setUp(self):
        self.agent = ImageAgent()

    def test_controlnet_openpose_detection(self):
        """Проверка детекции ControlNet OpenPose в текущем окружении."""
        # В текущем репозитории ControlNet OpenPose отсутствует
        has_pose = self.agent.has_controlnet_openpose()
        self.assertFalse(has_pose, "ControlNet OpenPose не должен быть обнаружен в пустой папке controlnet")

    def test_inpaint_model_detection(self):
        """Проверка детекции специализированных inpaint-моделей."""
        # В текущем репозитории специализированные inpaint-модели отсутствуют
        has_inpaint = self.agent.has_inpaint_model()
        self.assertFalse(has_inpaint, "Inpaint модель не должна быть обнаружена на базовом SDXL Lightning")

    def test_honest_message_on_missing_pose_model(self):
        """Честное сообщение при запросе изменения позы персонажа без ControlNet."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake_png_data")
            tmp_path = tmp.name

        try:
            ctx = AgentContext(
                task="Поменяй позу коту в изображении, чтобы он лежал на спине",
                metadata={
                    "action": "edit",
                    "edit_type": "pose",
                    "source_image_path": tmp_path
                }
            )
            result = self.agent.run(ctx)
            self.assertTrue(result.success)
            # Сообщение не должно утверждать, что PNG нельзя редактировать
            self.assertNotIn("PNG не подлежат редактированию", result.message)
            self.assertNotIn("нельзя редактировать", result.message.lower())
            # Сообщение должно честно сообщать об отсутствии модели ControlNet OpenPose
            self.assertIn("ControlNet OpenPose", result.message)
            self.assertIn("вариант", result.message.lower())
            self.assertEqual(result.data.get("status"), "missing_model")
            self.assertEqual(result.data.get("edit_type"), "pose")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_honest_message_on_missing_inpaint_model(self):
        """Честное сообщение при запросе удаления объекта без Inpainting."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake_png_data")
            tmp_path = tmp.name

        try:
            ctx = AgentContext(
                task="Убери второго кота",
                metadata={
                    "action": "edit",
                    "edit_type": "remove",
                    "source_image_path": tmp_path
                }
            )
            result = self.agent.run(ctx)
            self.assertTrue(result.success)
            self.assertNotIn("PNG не подлежат редактированию", result.message)
            self.assertIn("Inpainting", result.message)
            self.assertEqual(result.data.get("status"), "missing_model")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_edit_fails_if_source_image_not_found(self):
        """Ошибка, если файл исходного изображения отсутствует на диске."""
        ctx = AgentContext(
            task="Сделай кота рыжим",
            metadata={
                "action": "edit",
                "edit_type": "color",
                "source_image_path": "C:/non_existent_folder_xyz/img_missing.png"
            }
        )
        result = self.agent.run(ctx)
        self.assertFalse(result.success)
        self.assertIn("не найдено на диске", result.error)

    def test_build_img2img_workflow_structure(self):
        """Проверка корректности структуры JSON-графа img2img."""
        workflow = self.agent.build_img2img_workflow(
            input_image_name="test_cat.png",
            prompt="vibrant orange ginger cat",
            negative_prompt="blurry, ugly",
            seed=12345,
            denoise=0.6,
            steps=4
        )
        # Проверяем ключевые узлы ComfyUI img2img
        self.assertIn("4", workflow)
        self.assertEqual(workflow["4"]["class_type"], "LoadImage")
        self.assertEqual(workflow["4"]["inputs"]["image"], "test_cat.png")

        self.assertIn("5", workflow)
        self.assertEqual(workflow["5"]["class_type"], "VAEEncode")
        self.assertEqual(workflow["5"]["inputs"]["pixels"], ["4", 0])

        self.assertIn("6", workflow)
        self.assertEqual(workflow["6"]["class_type"], "KSampler")
        self.assertEqual(workflow["6"]["inputs"]["denoise"], 0.6)
        self.assertEqual(workflow["6"]["inputs"]["latent_image"], ["5", 0])

        self.assertIn("7", workflow)
        self.assertEqual(workflow["7"]["class_type"], "VAEDecode")

        self.assertIn("8", workflow)
        self.assertEqual(workflow["8"]["class_type"], "SaveImage")

    def test_img2img_staging_and_execution_with_mock_comfyui(self):
        """Проверка копирования исходного PNG в workers/comfyui/input и вызова img2img workflow."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake_source_cat_png")
            tmp_path = tmp.name

        try:
            ctx = AgentContext(
                task="Сделай фон лесным",
                metadata={
                    "action": "edit",
                    "edit_type": "background",
                    "source_image_path": tmp_path,
                    "manage_vram": False,
                    "auto_free": False,
                    "skip_compile": True
                }
            )

            # Мокаем client ComfyUI
            with patch.object(self.agent.client, "is_available", return_value=True), \
                 patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "test_prompt_456"}), \
                 patch.object(self.agent.client, "get_history", return_value={
                     "status": {"completed": True, "status_str": "success"},
                     "outputs": {
                         "8": {
                             "images": [{"filename": "out_edit.png", "subfolder": "", "type": "output"}]
                         }
                     }
                 }), \
                 patch.object(self.agent.client, "view_image", return_value=b"mock_edited_png_bytes"):

                result = self.agent.run(ctx)
                self.assertTrue(result.success, f"Expected success, got error: {result.error}")
                self.assertTrue(len(result.created_files) == 1)
                self.assertIn("отредактировано", result.message)

                # Проверяем, что созданный файл существует
                out_path = Path(result.created_files[0])
                self.assertTrue(out_path.exists())
                self.assertEqual(out_path.read_bytes(), b"mock_edited_png_bytes")
                # Убираем созданный файл
                if out_path.exists():
                    out_path.unlink()

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestAgentProcessImageEditIntegration(unittest.TestCase):
    """Интеграционные тесты полного цикла Agent.process() для запросов редактирования."""

    def setUp(self):
        from tools.agents import get_agent_registry
        from tools.agents.image import ImageAgent
        get_agent_registry().register(ImageAgent())

    def test_agent_process_edit_without_prior_image(self):
        """Если изображение еще не создавалось, возвращается понятное предупреждение."""
        agent = Agent()
        agent._last_image_result = None

        resp = agent.process("Поменяй позу коту в изображении, чтобы он лежал на спине")
        self.assertEqual(resp.get("type"), "image")
        self.assertEqual(resp.get("action"), "edit")
        self.assertIn("Нет ранее сгенерированного изображения", resp.get("answer"))
        # Ни в коем случае не должно быть сообщения про неподлежащий редактированию PNG
        self.assertNotIn("PNG не подлежат редактированию", resp.get("answer"))

    def test_agent_process_edit_pose_gives_honest_explanation(self):
        """После генерации запрос на смену позы даёт честное объяснение и варианты."""
        agent = Agent()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake_cat_png")
            tmp_path = tmp.name

        try:
            # Имитируем сохраненный результат предыдущей генерации
            agent._last_image_result = {
                "prompt": "рыжий кот загорает на пляже",
                "created_files": [tmp_path],
                "width": 1024,
                "height": 1024,
                "aspect_ratio": "1:1",
                "count": 1
            }

            resp = agent.process("Поменяй позу коту в изображении, чтобы он лежал на спине")
            self.assertEqual(resp.get("type"), "image")
            self.assertEqual(resp.get("action"), "edit")
            self.assertTrue(resp.get("success"))

            answer = resp.get("answer", "")
            # Проверяем, что нет ошибки "PNG не подлежат редактированию"
            self.assertNotIn("PNG не подлежат редактированию", answer)
            # Проверяем честное информирование об отсутствующей модели
            self.assertIn("ControlNet OpenPose", answer)
            self.assertIn("вариант", answer.lower())

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestImageContextTracker(unittest.TestCase):
    """Тестирование компонента Image Context и цепочек модификаций."""

    def setUp(self):
        from tools.image_context import ImageContextTracker
        self.tracker = ImageContextTracker()

    def test_context_generation_and_history(self):
        """Проверка регистрации начальной генерации и структуры контекста."""
        entry = self.tracker.track_generation(
            file_path="C:/dummy/cat_root.png",
            prompt="рыжий кот на пляже",
            width=1024,
            height=1024
        )
        self.assertEqual(self.tracker.get_root_image_path(), "C:/dummy/cat_root.png")
        self.assertEqual(self.tracker.get_active_image_path(validate_disk=False), "C:/dummy/cat_root.png")
        self.assertEqual(len(self.tracker.history), 1)

    def test_sequential_edits_chain(self):
        """Проверка цепочки правок: root -> edit_1 -> edit_2."""
        # Шаг 1: Исходная генерация (Image A)
        self.tracker.track_generation(
            file_path="C:/dummy/cat_A.png",
            prompt="кот на пляже"
        )
        self.assertEqual(self.tracker.get_root_image_path(), "C:/dummy/cat_A.png")
        self.assertEqual(self.tracker.get_active_image_path(validate_disk=False), "C:/dummy/cat_A.png")

        # Шаг 2: Правка 1 (Image B)
        self.tracker.track_edit(
            file_path="C:/dummy/cat_B.png",
            instruction="сделай кота стройнее",
            prompt="кот на пляже, slender",
            source_image_path="C:/dummy/cat_A.png",
            edit_type="proportions"
        )
        # Корень не изменился, активным стал результат B
        self.assertEqual(self.tracker.get_root_image_path(), "C:/dummy/cat_A.png")
        self.assertEqual(self.tracker.get_active_image_path(validate_disk=False), "C:/dummy/cat_B.png")
        self.assertEqual(len(self.tracker.history), 2)

        # Шаг 3: Правка 2 (Image C)
        self.tracker.track_edit(
            file_path="C:/dummy/cat_C.png",
            instruction="сделай его рыжим",
            prompt="рыжий кот на пляже, slender",
            source_image_path="C:/dummy/cat_B.png",
            edit_type="color"
        )
        # Корень по-прежнему A, активным стал C, в истории 3 шага
        self.assertEqual(self.tracker.get_root_image_path(), "C:/dummy/cat_A.png")
        self.assertEqual(self.tracker.get_active_image_path(validate_disk=False), "C:/dummy/cat_C.png")
        self.assertEqual(len(self.tracker.history), 3)

        # Проверка связей в истории
        history = self.tracker.get_history_summary()
        self.assertEqual(history[0]["file_path"], "C:/dummy/cat_A.png")
        self.assertIsNone(history[0]["source_image_path"])

        self.assertEqual(history[1]["file_path"], "C:/dummy/cat_B.png")
        self.assertEqual(history[1]["source_image_path"], "C:/dummy/cat_A.png")
        self.assertEqual(history[1]["edit_type"], "proportions")

        self.assertEqual(history[2]["file_path"], "C:/dummy/cat_C.png")
        self.assertEqual(history[2]["source_image_path"], "C:/dummy/cat_B.png")
        self.assertEqual(history[2]["edit_type"], "color")


class TestUniversalEditPlanner(unittest.TestCase):
    """Тестирование семантического планировщика EditPlanner на различных видах модификаций."""

    def setUp(self):
        from tools.edit_planner import EditPlanner
        self.planner = EditPlanner()

    def test_plan_shapes_and_proportions(self):
        """Правка формы и пропорций: кот стройнее, покатая крыша."""
        plan1 = self.planner.plan("сделай кота стройнее", base_prompt="рыжий кот")
        self.assertEqual(plan1.action_type, "proportions")
        self.assertEqual(plan1.recommended_mode, "img2img")
        self.assertIn("slender", plan1.positive_prompt_additions)
        self.assertTrue(0.4 <= plan1.denoise <= 0.7)

        plan2 = self.planner.plan("измени форму крыши на покатую", base_prompt="старый дом")
        self.assertEqual(plan2.action_type, "proportions")
        self.assertEqual(plan2.recommended_mode, "img2img")

    def test_plan_lighting_and_atmosphere(self):
        """Правка освещения и атмосферы: туман, закатное освещение."""
        plan1 = self.planner.plan("добавь туман на озеро", base_prompt="озеро в лесу")
        self.assertEqual(plan1.action_type, "lighting")
        self.assertEqual(plan1.recommended_mode, "img2img")
        self.assertIn("misty fog", plan1.positive_prompt_additions)

        plan2 = self.planner.plan("измени освещение на закатное", base_prompt="городская улица")
        self.assertEqual(plan2.action_type, "lighting")
        self.assertIn("sunset lighting", plan2.positive_prompt_additions)

    def test_plan_style_and_genre(self):
        """Правка стиля: готический замок, аниме."""
        plan = self.planner.plan("сделай замок более готическим", base_prompt="замок на холме")
        self.assertEqual(plan.action_type, "style")
        self.assertEqual(plan.recommended_mode, "img2img")
        self.assertIn("gothic architecture style", plan.positive_prompt_additions)

    def test_plan_missing_model_detection(self):
        """Определение потребности в специализированных моделях (OpenPose, Inpaint)."""
        plan_pose = self.planner.plan("поменяй позу кота на сидячую", base_prompt="кот")
        self.assertEqual(plan_pose.action_type, "pose")
        self.assertEqual(plan_pose.recommended_mode, "pose_control")
        self.assertEqual(plan_pose.requires_specialized_model, "openpose")

        plan_remove = self.planner.plan("удали лишнего кота", base_prompt="два кота")
        self.assertEqual(plan_remove.action_type, "remove")
        self.assertEqual(plan_remove.recommended_mode, "inpaint")
        self.assertEqual(plan_remove.requires_specialized_model, "inpaint")


class TestAgentSequentialEditingIntegration(unittest.TestCase):
    """Интеграционные сквозные тесты Agent.process() для цепочки последовательных правок."""

    def setUp(self):
        from tools.agents import get_agent_registry
        from tools.agents.image import ImageAgent
        get_agent_registry().register(ImageAgent())

    def test_sequential_edits_through_agent_process(self):
        """Сценарий многошагового диалога: генерация -> правка 1 -> текст -> правка 2."""
        agent = Agent()

        with tempfile.NamedTemporaryFile(suffix="_A.png", delete=False) as fA, \
             tempfile.NamedTemporaryFile(suffix="_B.png", delete=False) as fB, \
             tempfile.NamedTemporaryFile(suffix="_C.png", delete=False) as fC:
            path_A = fA.name
            path_B = fB.name
            path_C = fC.name

        try:
            # Шаг 1: Симулируем первичную генерацию (Image A)
            mock_res_A = AgentResult.ok(message="Создан кот A", created_files=[path_A])
            with patch.object(agent, "run_subagent", return_value=mock_res_A):
                resp1 = agent.process("сгенерируй кота на пляже")
                self.assertEqual(resp1["type"], "image")
                self.assertEqual(resp1["created_files"], [path_A])
                self.assertEqual(agent.image_context.get_active_image_path(validate_disk=False), path_A)
                self.assertEqual(agent.image_context.get_root_image_path(), path_A)

            # Шаг 2: Правка 1 ("сделай кота стройнее") -> должна взять path_A как вход
            mock_res_B = AgentResult.ok(message="Отредактирован кот B", created_files=[path_B])
            with patch.object(agent, "run_subagent", return_value=mock_res_B) as mock_run_1:
                resp2 = agent.process("сделай кота стройнее")
                self.assertEqual(resp2["type"], "image")
                self.assertEqual(resp2["action"], "edit")
                # Проверяем, что исходником для правки был передан path_A
                call_kwargs_1 = mock_run_1.call_args[1]
                self.assertEqual(call_kwargs_1.get("source_image_path"), path_A)
                self.assertEqual(call_kwargs_1.get("edit_type"), "proportions")
                # Теперь активным стал path_B
                self.assertEqual(agent.image_context.get_active_image_path(validate_disk=False), path_B)
                # А корень остался path_A
                self.assertEqual(agent.image_context.get_root_image_path(), path_A)

            # Шаг 3: Промежуточная текстовая реплика не сбрасывает активное изображение
            with patch.object(agent.ai, "send_chat", return_value={"content": "Всегда пожалуйста!"}):
                resp3 = agent.process("Спасибо, очень красиво!")
                self.assertEqual(agent.image_context.get_active_image_path(validate_disk=False), path_B)

            # Шаг 4: Правка 2 ("сделай его рыжим") -> должна взять path_B как вход, а не path_A!
            mock_res_C = AgentResult.ok(message="Отредактирован кот C", created_files=[path_C])
            with patch.object(agent, "run_subagent", return_value=mock_res_C) as mock_run_2:
                resp4 = agent.process("сделай его рыжим")
                self.assertEqual(resp4["type"], "image")
                self.assertEqual(resp4["action"], "edit")
                # Проверяем, что исходником для второй правки был взят результат первой (path_B)
                call_kwargs_2 = mock_run_2.call_args[1]
                self.assertEqual(call_kwargs_2.get("source_image_path"), path_B)
                self.assertEqual(call_kwargs_2.get("edit_type"), "color")
                # Активным стал результат C
                self.assertEqual(agent.image_context.get_active_image_path(validate_disk=False), path_C)
                # Корень всей цепочки по-прежнему path_A
                self.assertEqual(agent.image_context.get_root_image_path(), path_A)
                self.assertEqual(len(agent.image_context.history), 3)

        finally:
            for p in (path_A, path_B, path_C):
                if os.path.exists(p):
                    os.remove(p)


class TestUniversalImageEditHardening(unittest.TestCase):
    """
    Тесты углублённой устойчивости и семантики универсального редактирования изображений (Stages 1-4).
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_temp_png(self, name: str) -> str:
        fpath = os.path.join(self.tmp_dir, name)
        with open(fpath, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
        return fpath

    def test_stage1_negative_prompt_propagation_to_comfyui_node_3(self):
        """Этап 1: plan.compiled_negative доходит до KSampler / CLIPTextEncode узла 3."""
        img_path = self._create_temp_png("img_room.png")

        agent = Agent(router=CommandRouter())
        agent.image_context.track_generation(
            file_path=img_path,
            prompt="cozy room with a wooden table and window"
        )

        captured_workflows = []

        def mock_queue_prompt(workflow):
            captured_workflows.append(workflow)
            return {"prompt_id": "mock_prompt_123"}

        # Проверяем сквозной вызов ImageAgent через agent.process
        img_agent = agent.agent_registry.get("image")
        with patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.client, "queue_prompt", side_effect=mock_queue_prompt), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True},
                 "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}}
             }), \
             patch.object(img_agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nfake"), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}):
            resp = agent.process("замени деревянный стол на стеклянный")
            self.assertEqual(resp.get("type"), "image")
            self.assertEqual(resp.get("action"), "edit")

            self.assertTrue(len(captured_workflows) > 0, "ComfyUI workflow должен быть сформирован")
            wf = captured_workflows[0]

            # Проверяем узел 3 (CLIPTextEncode для negative prompt)
            self.assertIn("3", wf)
            self.assertEqual(wf["3"]["class_type"], "CLIPTextEncode")
            neg_text = wf["3"]["inputs"]["text"]

            # Проверяем, что исходное удаляемое состояние (wooden) передано в negative prompt
            self.assertIn("wooden", neg_text.lower())

            # Проверяем узел 2 (CLIPTextEncode для positive prompt)
            self.assertIn("2", wf)
            pos_text = wf["2"]["inputs"]["text"]
            self.assertIn("glass material", pos_text.lower())

    def test_stage2_disk_fallback_on_deleted_active_image(self):
        """Этап 2: при удалении активного файла происходит безопасный откат назад по истории."""
        img1 = self._create_temp_png("img_1.png")
        img2 = self._create_temp_png("img_2.png")

        agent = Agent(router=CommandRouter())
        agent.image_context.track_generation(file_path=img1, prompt="original cat")
        agent.image_context.track_edit(file_path=img2, instruction="make cat slim", prompt="slim cat")

        self.assertEqual(agent.image_context.get_active_image_path(validate_disk=True), img2)

        # Удаляем img2 с диска
        os.remove(img2)

        # Теперь get_active_image_path должен безопасно откатиться к img1
        active_after_del = agent.image_context.get_active_image_path(validate_disk=True)
        self.assertEqual(active_after_del, img1)

        # Удаляем и img1
        os.remove(img1)
        self.assertIsNone(agent.image_context.get_active_image_path(validate_disk=True))

        # При попытке редактирования агент корректно и вежливо отказывает без падений
        resp = agent.process("отредактируй картинку: сделай кота рыжим")
        self.assertEqual(resp.get("type"), "image")
        self.assertEqual(resp.get("action"), "edit")
        self.assertFalse(resp.get("success"))
        self.assertIn("Нет ранее сгенерированного изображения", resp.get("answer"))

    def test_stage2_failed_generation_preserves_active_image(self):
        """Этап 2: сбой генерации (таймаут, ошибка ComfyUI) не ломает контекст активного изображения."""
        img1 = self._create_temp_png("img_keep.png")

        agent = Agent(router=CommandRouter())
        agent.image_context.track_generation(file_path=img1, prompt="original scene")

        # Симулируем ошибку сабагента
        mock_fail = AgentResult.fail("ComfyUI connection timeout")
        with patch.object(agent, "run_subagent", return_value=mock_fail):
            resp = agent.process("сделай кота стройнее")
            self.assertFalse(resp.get("success"))
            self.assertIn("Ошибка генерации", resp.get("answer"))

        # Контекст активного изображения остался нетронутым
        self.assertEqual(agent.image_context.get_active_image_path(validate_disk=True), img1)
        self.assertEqual(len(agent.image_context.history), 1)

    def test_stage3_audit_queries_and_false_subjects(self):
        """Этап 3: проверка 4 контрольных запросов аудита и исключение ложных субъектов."""
        from tools.edit_planner import EditPlanner

        planner = EditPlanner()
        base_prompt = "cozy room with a wooden table and window"

        # Запрос 1: "сделай изображение более кинематографичным"
        plan1 = planner.plan("сделай изображение более кинематографичным", base_prompt=base_prompt)
        self.assertEqual(plan1.action_type, "style")
        self.assertNotIn("solo, single cinematic", plan1.compiled_prompt.lower())
        self.assertNotIn("multiple cinematics", plan1.compiled_negative.lower())
        self.assertIn("cinematic shot", plan1.compiled_prompt.lower())

        # Запрос 2: "замени деревянный стол на стеклянный"
        plan2 = planner.plan("замени деревянный стол на стеклянный", base_prompt=base_prompt)
        self.assertEqual(plan2.action_type, "replace")
        self.assertEqual(plan2.target, "стол")
        self.assertIn("wooden", plan2.compiled_negative.lower())
        self.assertIn("glass material", plan2.compiled_prompt.lower())
        self.assertNotIn("solo, single wooden", plan2.compiled_prompt.lower())

        # Запрос 3: "добавь отражение в окне"
        plan3 = planner.plan("добавь отражение в окне", base_prompt=base_prompt)
        self.assertEqual(plan3.action_type, "add")
        self.assertTrue(
            "reflective surface" in plan3.compiled_prompt.lower() or
            "glass reflection" in plan3.compiled_prompt.lower()
        )

        # Запрос 4: "сохрани всё, но сделай освещение вечерним"
        plan4 = planner.plan("сохрани всё, но сделай освещение вечерним", base_prompt=base_prompt)
        self.assertEqual(plan4.action_type, "lighting")
        self.assertTrue(
            "evening lighting" in plan4.compiled_prompt.lower() or
            "dusk atmosphere" in plan4.compiled_prompt.lower()
        )

    def test_stage4_llm_planner_integration_and_safety(self):
        """Этап 4: вызов LLM только при необходимости, ограничение denoise и безопасный fallback."""
        from tools.edit_planner import EditPlanner

        mock_ai = MagicMock()
        planner = EditPlanner(ai_client=mock_ai)

        # 1. Для распознанного детерминированного запроса LLM не вызывается
        planner.plan("сделай кота стройнее", base_prompt="cat")
        mock_ai.send_chat.assert_not_called()
        mock_ai.ask.assert_not_called()

        # 2. Для нестандартного запроса LLM вызывается и валидируется
        mock_ai.send_chat.return_value = {
            "content": '{"target": "замок", "action_type": "style", "what_to_change": "gothic look", "what_to_keep": "structure", "denoise": 0.99, "positive_tags": ["gothic cathedral"], "negative_tags": ["modern architecture"]}'
        }
        plan_custom = planner.plan("преврати это во что-то мистическое и неземное", base_prompt="castle")
        self.assertEqual(plan_custom.action_type, "style")
        # denoise должен быть ограничен безопасным пределом 0.85
        self.assertAlmostEqual(plan_custom.denoise, 0.85)
        self.assertIn("gothic cathedral", plan_custom.compiled_prompt.lower())

        # 3. Безопасный fallback при исключении в LLM
        mock_ai.send_chat.side_effect = TimeoutError("LLM response timeout")
        plan_fallback = planner.plan("непонятная сложная инструкция", base_prompt="scene")
        self.assertIsNotNone(plan_fallback)
        self.assertEqual(plan_fallback.action_type, "general")


if __name__ == "__main__":
    unittest.main()
