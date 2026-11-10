"""
Тесты Step 3: локальный Masked Inpainting (PIL-маски с feather + SetLatentNoiseMask /
InpaintModelConditioning), ControlNet (Canny / OpenPose discovery & graph)
и сквозная связка inspect_image(mask_bbox) -> edit_image(mask_bbox) через Native Tool Calling.
"""

import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from config import PROJECT_PATH
from tools.agent import Agent
from tools.agents.context import AgentContext
from tools.agents.image import ImageAgent, generate_feathered_mask_png
from tools.context import ContextManager
from tools.edit_planner import EditPlanner
from tools.image_tools import edit_image, reset_fallback_image_context
from tools.memory import MemoryManager
from tools.registry import TOOL_PARAMETERS, TOOLS


def _make_png(path: Path, color=(40, 120, 200), size=(200, 100)) -> str:
    img = Image.new("RGB", size, color=color)
    img.save(str(path), format="PNG")
    return str(path)


class TestFeatheredMaskAndWorkflowBuilders(unittest.TestCase):
    """Проверка генерации feathered-масок и структуры графов Inpaint / ControlNet."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.agent = ImageAgent(output_dir=str(self.tmp_path / "out"))
        self.src_img = Path(_make_png(self.tmp_path / "source.png", size=(200, 100)))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_generate_feathered_mask_png_dimensions_and_blur(self):
        mask_out = self.tmp_path / "mask.png"
        w, h = generate_feathered_mask_png(
            source_image_path=str(self.src_img),
            mask_bbox=[0.25, 0.25, 0.75, 0.75],
            output_path=mask_out,
            feather=12,
        )
        self.assertEqual((w, h), (200, 100))
        self.assertTrue(mask_out.exists())

        with Image.open(mask_out) as im:
            self.assertEqual(im.size, (200, 100))
            center_r = im.getpixel((100, 50))[0]
            corner_r = im.getpixel((2, 2))[0]
            edge_r = im.getpixel((50, 50))[0]

            self.assertGreaterEqual(center_r, 245)
            self.assertLessEqual(corner_r, 5)
            self.assertGreater(edge_r, 10)
            self.assertLess(edge_r, 245)

    def test_build_inpaint_workflow_standard_and_dedicated(self):
        wf_std = self.agent.build_inpaint_workflow(
            input_image_name="in.png",
            mask_image_name="mask.png",
            prompt="beach sand only",
            negative_prompt="second cat, duplicate",
            seed=42,
            denoise=0.8,
            use_inpaint_conditioning=False,
        )
        self.assertEqual(wf_std["4"]["class_type"], "LoadImage")
        self.assertEqual(wf_std["9"]["class_type"], "LoadImageMask")
        self.assertEqual(wf_std["9"]["inputs"]["image"], "mask.png")
        self.assertEqual(wf_std["9"]["inputs"]["channel"], "red")
        self.assertEqual(wf_std["5"]["class_type"], "VAEEncode")
        self.assertEqual(wf_std["10"]["class_type"], "SetLatentNoiseMask")
        self.assertEqual(wf_std["10"]["inputs"]["samples"], ["5", 0])
        self.assertEqual(wf_std["10"]["inputs"]["mask"], ["9", 0])
        self.assertEqual(wf_std["6"]["class_type"], "KSampler")
        self.assertEqual(wf_std["6"]["inputs"]["latent_image"], ["10", 0])
        self.assertIn("second cat", wf_std["3"]["inputs"]["text"])

        wf_ded = self.agent.build_inpaint_workflow(
            input_image_name="in.png",
            mask_image_name="mask.png",
            prompt="beach sand only",
            seed=42,
            use_inpaint_conditioning=True,
        )
        self.assertNotIn("5", wf_ded)
        self.assertEqual(wf_ded["10"]["class_type"], "InpaintModelConditioning")
        self.assertTrue(wf_ded["10"]["inputs"]["noise_mask"])
        self.assertEqual(wf_ded["6"]["inputs"]["positive"], ["10", 0])
        self.assertEqual(wf_ded["6"]["inputs"]["negative"], ["10", 1])
        self.assertEqual(wf_ded["6"]["inputs"]["latent_image"], ["10", 2])

    def test_build_controlnet_workflow_canny_structure(self):
        wf = self.agent.build_controlnet_workflow(
            input_image_name="in.png",
            controlnet_name="controlnet-canny-sdxl.safetensors",
            prompt="sunset castle",
            negative_prompt="blurry",
            seed=7,
            denoise=0.72,
            control_type="canny",
            control_strength=0.85,
        )
        self.assertEqual(wf["9"]["class_type"], "ControlNetLoader")
        self.assertEqual(wf["9"]["inputs"]["control_net_name"], "controlnet-canny-sdxl.safetensors")
        self.assertEqual(wf["10"]["class_type"], "Canny")
        self.assertEqual(wf["10"]["inputs"]["image"], ["4", 0])
        self.assertEqual(wf["11"]["class_type"], "ControlNetApplyAdvanced")
        self.assertEqual(wf["11"]["inputs"]["control_net"], ["9", 0])
        self.assertEqual(wf["11"]["inputs"]["image"], ["10", 0])
        self.assertEqual(wf["11"]["inputs"]["strength"], 0.85)
        self.assertEqual(wf["6"]["inputs"]["positive"], ["11", 0])
        self.assertEqual(wf["6"]["inputs"]["negative"], ["11", 1])


class TestImageAgentInpaintAndControlNetExecution(unittest.TestCase):
    """Тестирование выполнения Inpaint и ControlNet в ImageAgent и очистки staging-файлов."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.agent = ImageAgent(output_dir=str(self.tmp_path / "out"))
        self.src_img = Path(_make_png(self.tmp_path / "cat_src.png", size=(128, 128)))
        self.input_dir = PROJECT_PATH / "workers" / "comfyui" / "input"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _snapshot_input_dir(self):
        if not self.input_dir.exists():
            return set()
        return {p.name for p in self.input_dir.iterdir()}

    def test_inpaint_with_mask_bbox_runs_and_cleans_up(self):
        before_files = self._snapshot_input_dir()
        captured = []
        observed_mask_exists_during_queue = []

        def mock_queue(wf):
            captured.append(wf)
            mask_fname = wf["9"]["inputs"]["image"]
            observed_mask_exists_during_queue.append((self.input_dir / mask_fname).is_file())
            return {"prompt_id": "inpaint_job_1"}

        ctx = AgentContext(
            task="empty sand beach",
            metadata={
                "action": "edit",
                "edit_type": "remove",
                "source_image_path": str(self.src_img),
                "mask_bbox": [0.5, 0.2, 0.9, 0.9],
                "feather": 8,
                "denoise": 0.82,
                "manage_vram": False,
                "auto_free": False,
                "skip_compile": True,
            },
        )

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", side_effect=mock_queue), \
             patch.object(self.agent.client, "get_history", return_value={
                 "status": {"completed": True, "status_str": "success"},
                 "outputs": {"8": {"images": [{"filename": "out_inp.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(self.agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_out"):
            res = self.agent.run(ctx)

        self.assertTrue(res.success, res.error)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["10"]["class_type"], "SetLatentNoiseMask")
        self.assertEqual(observed_mask_exists_during_queue, [True])
        self.assertEqual(res.data.get("edit_mode"), "inpaint")
        self.assertTrue(res.data.get("mask_used"))
        # Входные и масочные временные файлы должны быть удалены из workers/comfyui/input
        self.assertEqual(self._snapshot_input_dir(), before_files)

    def test_inpaint_cleanup_even_on_comfyui_error(self):
        before_files = self._snapshot_input_dir()
        mask_file = Path(_make_png(self.tmp_path / "custom_mask.png", color=(255, 255, 255), size=(128, 128)))

        ctx = AgentContext(
            task="paint red ball",
            metadata={
                "action": "edit",
                "edit_type": "add",
                "source_image_path": str(self.src_img),
                "mask_path": str(mask_file),
                "manage_vram": False,
                "auto_free": False,
                "skip_compile": True,
            },
        )

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", side_effect=RuntimeError("Queue failed")):
            res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertEqual(self._snapshot_input_dir(), before_files)

    def test_dedicated_inpaint_checkpoint_selected_automatically_when_present(self):
        captured = []

        def mock_queue(wf):
            captured.append(wf)
            return {"prompt_id": "inpaint_job_ded"}

        ctx = AgentContext(
            task="grass field",
            metadata={
                "action": "edit",
                "edit_type": "remove",
                "source_image_path": str(self.src_img),
                "mask_bbox": [0.1, 0.1, 0.5, 0.5],
                "manage_vram": False,
                "auto_free": False,
                "skip_compile": True,
            },
        )

        with patch.object(self.agent, "get_available_models", return_value={
            "checkpoints": ["sdxl_lightning_4step.safetensors", "sd_xl_base_1.0_inpainting_0.1.safetensors"],
            "controlnet": [],
            "inpaint": [],
            "loras": [],
        }), \
             patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", side_effect=mock_queue), \
             patch.object(self.agent.client, "get_history", return_value={
                 "status": {"completed": True, "status_str": "success"},
                 "outputs": {"8": {"images": [{"filename": "out_ded.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(self.agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_ded"):
            res = self.agent.run(ctx)

        self.assertTrue(res.success, res.error)
        self.assertEqual(captured[0]["1"]["inputs"]["ckpt_name"], "sd_xl_base_1.0_inpainting_0.1.safetensors")
        self.assertEqual(captured[0]["10"]["class_type"], "InpaintModelConditioning")

    def test_controlnet_canny_missing_vs_installed(self):
        ctx_missing = AgentContext(
            task="cyberpunk neon city",
            metadata={
                "action": "edit",
                "edit_type": "style",
                "source_image_path": str(self.src_img),
                "control_type": "canny",
                "manage_vram": False,
                "auto_free": False,
                "skip_compile": True,
            },
        )
        res_missing = self.agent.run(ctx_missing)
        self.assertTrue(res_missing.success)
        self.assertEqual(res_missing.data.get("status"), "missing_model")
        self.assertIn("ControlNet CANNY", res_missing.data.get("missing_component", ""))

        captured = []
        with patch.object(self.agent, "get_available_models", return_value={
            "checkpoints": ["sdxl_lightning_4step.safetensors"],
            "controlnet": ["diffusers_xl_canny_full.safetensors"],
            "inpaint": [],
            "loras": [],
        }), \
             patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", side_effect=lambda wf: captured.append(wf) or {"prompt_id": "cn_1"}), \
             patch.object(self.agent.client, "get_history", return_value={
                 "status": {"completed": True, "status_str": "success"},
                 "outputs": {"8": {"images": [{"filename": "out_cn.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(self.agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_cn"):
            res_ok = self.agent.run(ctx_missing)

        self.assertTrue(res_ok.success, res_ok.error)
        self.assertEqual(res_ok.data.get("edit_mode"), "controlnet")
        self.assertEqual(captured[0]["9"]["class_type"], "ControlNetLoader")
        self.assertEqual(captured[0]["10"]["class_type"], "Canny")
        self.assertEqual(captured[0]["11"]["class_type"], "ControlNetApplyAdvanced")

    def test_invalid_mask_path_fails_cleanly(self):
        ctx = AgentContext(
            task="remove object",
            metadata={
                "action": "edit",
                "edit_type": "remove",
                "source_image_path": str(self.src_img),
                "mask_path": str(self.tmp_path / "missing_mask.png"),
            },
        )
        res = self.agent.run(ctx)
        self.assertFalse(res.success)
        self.assertIn("не найден", res.error.lower())


class TestEndToEndVisionInspectToInpaintToolCalling(unittest.TestCase):
    """Сквозной тест Step 1 + Step 2 + Step 3 через Native Tool Calling (inspect_image -> edit_image)."""

    def setUp(self):
        reset_fallback_image_context()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.src_img = Path(_make_png(self.tmp_path / "two_cats.png", size=(256, 256)))

    def tearDown(self):
        reset_fallback_image_context()
        self.tmp_dir.cleanup()

    def test_edit_image_registry_matches_signature(self):
        self.assertIn("edit_image", TOOLS)
        self.assertIn("edit_image", TOOL_PARAMETERS)
        sig_params = set(inspect.signature(edit_image).parameters.keys())
        schema_props = set(TOOL_PARAMETERS["edit_image"]["properties"].keys())
        self.assertEqual(sig_params, schema_props)

    @patch("infrastructure.ollama_manager.get_ollama_manager")
    @patch("ollama_client.requests.post")
    def test_e2e_inspect_bbox_then_edit_inpaint(self, mock_post, mock_get_mgr):
        mock_mgr = MagicMock()
        mock_mgr.check_vision_model_available.return_value = (True, "OK")
        mock_get_mgr.return_value = mock_mgr

        # Ответ Vision-модели qwen3-vl:4b на inspect_image(return_bbox=True)
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": "Справа виден второй серый кот.",
                            "objects": [{"label": "second gray cat", "bbox": [0.55, 0.2, 0.95, 0.9]}],
                            "mask_bbox": [0.55, 0.2, 0.95, 0.9],
                        },
                        ensure_ascii=False,
                    )
                }
            },
        )

        # 3 шага Qwen: 1) inspect_image -> 2) edit_image(mask_bbox=...) -> 3) финальный ответ
        mock_ai = MagicMock()
        mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "inspect_image",
                            "arguments": {"question": "Где находится второй кот?", "return_bbox": True},
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_2",
                        "function": {
                            "name": "edit_image",
                            "arguments": {
                                "instruction": "убери второго кота справа",
                                "edit_type": "remove",
                                "positive_prompt": "clean sandy beach, ocean waves, untouched background",
                                "negative_prompt": "second cat, two cats",
                                "mask_bbox": [0.55, 0.2, 0.95, 0.9],
                            },
                        },
                    }
                ],
            },
            {
                "content": "Я удалил второго кота справа с помощью точечного inpainting по координатам [0.55, 0.2, 0.95, 0.9].",
                "tool_calls": [],
            },
        ]

        mem = MemoryManager(storage_path=self.tmp_path / "mem.json")
        ctx = ContextManager(memory_manager=mem)
        agent = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=mock_ai,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx.json",
        )
        img_agent = ImageAgent(output_dir=str(self.tmp_path / "out"))
        agent.agent_registry.register(img_agent)
        agent.image_context.track_generation(file_path=str(self.src_img), prompt="two cats on beach")

        out_png_bytes = b"\x89PNG\r\n\x1a\ninpainted_result_png"
        captured_workflows = []

        with patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.client, "queue_prompt", side_effect=lambda wf: captured_workflows.append(wf) or {"prompt_id": "e2e_1"}), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True, "status_str": "success"},
                 "outputs": {"8": {"images": [{"filename": "e2e_out.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(img_agent.client, "view_image", return_value=out_png_bytes), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}):
            resp = agent.process(
                "Проверь глазами через зрение, кто там справа, и оставь в той области только чистый песок"
            )

        self.assertEqual(resp["type"], "chat")
        self.assertEqual(len(resp["created_files"]), 1)
        self.assertEqual(len(resp["artifacts"]), 1)
        self.assertTrue(Path(resp["created_files"][0]).is_file())
        self.assertEqual(agent.image_context.get_active_image_path(validate_disk=True), resp["created_files"][0])

        # Проверяем, что Qwen получил ответ inspect_image с mask_bbox перед вызовом edit_image
        second_msgs = mock_ai.send_chat.call_args_list[1][0][0]
        inspect_payload = json.loads(second_msgs[-1]["content"])
        self.assertEqual(inspect_payload["mask_bbox"], [0.55, 0.2, 0.95, 0.9])

        self.assertEqual(len(captured_workflows), 1)
        wf = captured_workflows[0]
        self.assertEqual(wf["9"]["class_type"], "LoadImageMask")
        self.assertEqual(wf["10"]["class_type"], "SetLatentNoiseMask")
        self.assertIn("second cat", wf["3"]["inputs"]["text"].lower())


class TestImageOrchestrationScopingAndPlanner(unittest.TestCase):
    """Регрессионные тесты scoping'а 5 image-инструментов, алиасов/retry и EditPlanner 'преврати ... в ...'."""

    def setUp(self):
        reset_fallback_image_context()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.src_img = Path(_make_png(self.tmp_path / "mug_scene.png", size=(256, 256)))

    def tearDown(self):
        reset_fallback_image_context()
        self.tmp_dir.cleanup()

    def test_image_query_scopes_tools_without_affecting_system_queries(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.side_effect = [
            {"content": "Ок", "tool_calls": []},
            {"content": "Ок", "tool_calls": []},
        ]
        mem = MemoryManager(storage_path=self.tmp_path / "mem.json")
        ctx = ContextManager(memory_manager=mem)
        agent = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=mock_ai,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx.json",
        )

        agent.process("Хочется увидеть солнечный летний кадр: зелёная лужайка и стол")
        img_call_kwargs = mock_ai.send_chat.call_args_list[0][1]
        img_msgs = mock_ai.send_chat.call_args_list[0][0][0]
        img_tool_names = {t["function"]["name"] for t in img_call_kwargs["tools"]}
        self.assertEqual(
            img_tool_names,
            {"generate_image", "edit_image", "inspect_image", "get_active_image", "select_image"},
        )
        self.assertIn("ПРАВИЛА РАБОТЫ С ИЗОБРАЖЕНИЯМИ", img_msgs[0]["content"])

        agent.process("Сделай что-нибудь полезное для системы")
        sys_call_kwargs = mock_ai.send_chat.call_args_list[1][1]
        sys_tool_names = {t["function"]["name"] for t in sys_call_kwargs["tools"]}
        self.assertEqual(len(sys_tool_names), len(TOOLS))

    def test_generate_image_synonym_alias_and_single_schema_retry(self):
        mock_ai = MagicMock()
        # Попытка 1: ошибочный лишний параметр background_color + алиас scene_description
        # Попытка 2: модель исправляется и передаёт корректный prompt
        # Попытка 3: финальный ответ
        mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c_bad",
                        "function": {
                            "name": "generate_image",
                            "arguments": {"scene_description": "sunny green meadow", "background_color": "#7CFC00"},
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c_good",
                        "function": {
                            "name": "generate_image",
                            "arguments": {"scene_description": "sunny green meadow", "aspect_ratio": "landscape"},
                        },
                    }
                ],
            },
            {"content": "Изображение сгенерировано.", "tool_calls": []},
        ]
        mem = MemoryManager(storage_path=self.tmp_path / "mem2.json")
        ctx = ContextManager(memory_manager=mem)
        agent = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=mock_ai,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx2.json",
        )
        img_agent = ImageAgent(output_dir=str(self.tmp_path / "out2"))
        agent.agent_registry.register(img_agent)

        with patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.client, "queue_prompt", return_value={"prompt_id": "alias_1"}), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True},
                 "outputs": {"7": {"images": [{"filename": "g.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(img_agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_g"), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}):
            resp = agent.process("Хочется увидеть солнечный летний кадр на лужайке")

        self.assertEqual(resp["type"], "chat")
        self.assertEqual(len(resp.get("created_files", [])), 1)
        # Первый раунд вернул в модель role: tool с подсказкой допустимых аргументов
        second_msgs = mock_ai.send_chat.call_args_list[1][0][0]
        self.assertEqual(second_msgs[-1]["role"], "tool")
        self.assertIn("Допустимые аргументы", second_msgs[-1]["content"])

        # Проверка жёсткого лимита MAX_SCHEMA_RETRIES = 1 при повторной ошибке схемы
        mock_ai_fail = MagicMock()
        mock_ai_fail.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [{"id": "b1", "function": {"name": "generate_image", "arguments": {"bad1": 1}}}],
            },
            {
                "content": "",
                "tool_calls": [{"id": "b2", "function": {"name": "generate_image", "arguments": {"bad2": 2}}}],
            },
        ]
        agent_fail = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=mock_ai_fail,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx3.json",
        )
        fail_resp = agent_fail.process("Хочется увидеть кадр летней лужайки")
        self.assertEqual(fail_resp["type"], "tool")
        self.assertFalse(fail_resp["success"])
        self.assertTrue(bool(fail_resp.get("answer")))
        self.assertTrue(bool(fail_resp.get("error")))

    def test_edit_planner_prevratit_replace_and_no_color_leak_under_mask(self):
        planner = EditPlanner(ai_client=None)
        plan = planner.plan(
            "преврати белую кружку в синюю стеклянную бутылку, сохранив стол и лужайку",
            base_prompt="white porcelain mug on wooden table, green lawn",
            use_llm=False,
        )
        self.assertEqual(plan.action_type, "replace")
        self.assertGreaterEqual(plan.denoise, 0.55)
        neg_text = " ".join(plan.negative_prompt_additions).lower()
        self.assertTrue("mug" in neg_text or "cup" in neg_text)
        self.assertIn("white", neg_text)

        mock_ai = MagicMock()
        mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "ed_1",
                        "function": {
                            "name": "edit_image",
                            "arguments": {
                                "instruction": "преврати кружку в синюю стеклянную бутылку",
                                "edit_type": "replace",
                                "positive_prompt": "translucent blue glass bottle on wooden table",
                                "negative_prompt": "white porcelain mug, ceramic cup",
                                "mask_bbox": [0.3, 0.3, 0.55, 0.65],
                            },
                        },
                    }
                ],
            },
            {"content": "Кружка заменена на бутылку.", "tool_calls": []},
        ]
        mem = MemoryManager(storage_path=self.tmp_path / "mem3.json")
        ctx = ContextManager(memory_manager=mem)
        agent = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=mock_ai,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx4.json",
        )
        img_agent = ImageAgent(output_dir=str(self.tmp_path / "out4"))
        agent.agent_registry.register(img_agent)
        agent.image_context.track_generation(
            file_path=str(self.src_img),
            prompt="white porcelain mug on wooden table, green lawn",
        )

        captured = []
        with patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.client, "queue_prompt", side_effect=lambda wf: captured.append(wf) or {"prompt_id": "m1"}), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True},
                 "outputs": {"8": {"images": [{"filename": "e.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(img_agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_bottle"), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}):
            resp = agent.process("Определи с помощью зрения координаты кружки и преврати её в синюю стеклянную бутылку")

        self.assertEqual(resp["type"], "chat")
        self.assertEqual(len(captured), 1)
        wf = captured[0]
        wf_neg = wf["3"]["inputs"]["text"].lower()
        self.assertNotIn("black fur", wf_neg)
        self.assertNotIn("orange fur", wf_neg)
        self.assertIn("mug", wf_neg)
        self.assertIn("blue glass bottle", wf["2"]["inputs"]["text"].lower())
        self.assertGreaterEqual(wf["6"]["inputs"]["denoise"], 0.78)

    def test_english_replace_planner_and_general_edit_type_masked_defaults(self):
        planner = EditPlanner(ai_client=None)
        plan = planner.plan(
            "replace the white porcelain cup with a translucent blue glass bottle",
            base_prompt="white porcelain cup on wooden table, green lawn",
            use_llm=False,
        )
        self.assertEqual(plan.action_type, "replace")
        neg_text = " ".join(plan.negative_prompt_additions).lower()
        pos_text = " ".join(plan.positive_prompt_additions).lower()
        self.assertIn("white", neg_text)
        self.assertTrue("mug" in neg_text or "cup" in neg_text)
        self.assertIn("deep blue", pos_text)
        self.assertIn("glass bottle", pos_text)

        from tools.image_tools import bind_active_image_agent

        mem = MemoryManager(storage_path=self.tmp_path / "mem4.json")
        ctx = ContextManager(memory_manager=mem)
        agent = Agent(
            memory_manager=mem,
            context_manager=ctx,
            ai_client=MagicMock(),
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx5.json",
        )
        img_agent = ImageAgent(output_dir=str(self.tmp_path / "out5"))
        agent.agent_registry.register(img_agent)
        agent.image_context.track_generation(
            file_path=str(self.src_img),
            prompt="white porcelain cup on wooden table, green lawn",
        )

        captured = []
        with bind_active_image_agent(agent), \
             patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.client, "queue_prompt", side_effect=lambda wf: captured.append(wf) or {"prompt_id": "m2"}), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True},
                 "outputs": {"8": {"images": [{"filename": "e2.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(img_agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\nmock_bottle2"), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}):
            res = edit_image(
                instruction="replace white porcelain cup with blue glass bottle",
                edit_type="general",
                positive_prompt="translucent cobalt blue glass bottle resting on wooden saucer",
                mask_bbox=[0.27, 0.35, 0.45, 0.72],
            )

        self.assertTrue(res["success"], res.get("error"))
        self.assertEqual(res["edit_type"], "replace")
        self.assertGreaterEqual(res["denoise"], 0.94)
        self.assertEqual(len(captured), 1)
        wf = captured[0]
        self.assertEqual(wf["6"]["inputs"]["steps"], 6)
        self.assertAlmostEqual(wf["6"]["inputs"]["cfg"], 2.4)
        self.assertGreaterEqual(wf["6"]["inputs"]["denoise"], 0.94)
        wf_neg = wf["3"]["inputs"]["text"].lower()
        self.assertIn("mug", wf_neg)
        self.assertNotIn("black fur", wf_neg)
        self.assertNotIn("orange fur", wf_neg)


if __name__ == "__main__":
    unittest.main()
