"""
Тесты оркестрации генерации и редактирования изображений через Native Tool Calling (Step 1).
"""

import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from tools.agent import Agent
from tools.agents.context import AgentContext
from tools.agents.image import ImageAgent
from tools.agents.result import Artifact, ArtifactType
from tools.context import ContextManager
from tools.dispatcher import get_confirmation_handler, set_confirmation_handler
from tools.image_context import ImageContextTracker
from tools.image_tools import (
    edit_image,
    generate_image,
    get_active_image,
    reset_fallback_image_context,
    select_image,
)
from tools.memory import MemoryManager
from tools.permissions import PermissionManager, RiskLevel, SecurityPolicy
from tools.prompt_compiler import PromptCompiler, translate_prompt_to_sdxl_tags
from tools.registry import TOOL_PARAMETERS, TOOLS, get_tools_schema
from ui.artifact_card import FileArtifactCard, ImageArtifactCard, create_artifact_card


def _make_real_png(path: Path, color=(40, 120, 200), size=(64, 64)) -> str:
    img = Image.new("RGB", size, color=color)
    img.save(str(path), format="PNG")
    return str(path)


class TestImageContextPersistenceAndSelection(unittest.TestCase):
    """Проверка персистентности на диск и выбора активного изображения."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.storage_file = self.tmp_path / "image_context.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_persistence_across_restarts_and_select_image(self):
        img1 = _make_real_png(self.tmp_path / "img1.png", color=(10, 20, 30), size=(128, 128))
        img2 = _make_real_png(self.tmp_path / "img2.png", color=(200, 50, 50), size=(128, 128))
        img_ext = _make_real_png(self.tmp_path / "ext.png", color=(50, 200, 50), size=(128, 128))

        tracker1 = ImageContextTracker(storage_path=self.storage_file)
        tracker1.track_generation(file_path=img1, prompt="red fox in forest", width=128, height=128)
        tracker1.track_edit(
            file_path=img2,
            instruction="make fox blue",
            prompt="blue fox in forest",
            source_image_path=img1,
            edit_type="color",
            width=128,
            height=128,
        )
        self.assertTrue(self.storage_file.exists())

        # Перезагружаем новый экземпляр с диска
        tracker2 = ImageContextTracker(storage_path=self.storage_file)
        self.assertEqual(tracker2.get_root_image_path(), img1)
        self.assertEqual(tracker2.get_active_image_path(validate_disk=True), img2)
        self.assertEqual(len(tracker2.history), 2)

        # Выбираем первое изображение назад
        ok, entry, msg = tracker2.select_active_image(img1)
        self.assertTrue(ok, msg)
        self.assertEqual(tracker2.get_active_image_path(validate_disk=True), img1)
        self.assertEqual(entry.prompt, "red fox in forest")

        # Выбираем внешний файл не из истории
        ok_ext, entry_ext, _ = tracker2.select_active_image(img_ext, prompt="external scene")
        self.assertTrue(ok_ext)
        self.assertEqual(tracker2.get_active_image_path(validate_disk=True), img_ext)
        self.assertEqual(entry_ext.prompt, "external scene")

        # Несуществующий файл отклоняется
        ok_bad, _, err_bad = tracker2.select_active_image(str(self.tmp_path / "missing.png"))
        self.assertFalse(ok_bad)
        self.assertIn("не найден", err_bad.lower())

        # Перезагрузка подтверждает сохранение выбора img_ext
        tracker3 = ImageContextTracker(storage_path=self.storage_file)
        self.assertEqual(tracker3.get_active_image_path(validate_disk=True), img_ext)

    def test_sync_from_legacy_dict_preserves_storage_path(self):
        img1 = _make_real_png(self.tmp_path / "legacy.png")
        tracker = ImageContextTracker(storage_path=self.storage_file)
        tracker.sync_from_legacy_dict({"prompt": "starship", "created_files": [img1]}, validate_disk=True)

        self.assertEqual(tracker.storage_path, self.storage_file)
        self.assertEqual(tracker.get_active_image_path(validate_disk=True), img1)
        self.assertTrue(self.storage_file.exists())


class TestPromptCompilerUnmatchedFallback(unittest.TestCase):
    """Проверка fallback при неизвестном субъекте и LLM-переводе тегов."""

    def test_unmatched_subject_keeps_clean_phrase_instead_of_bare_quality(self):
        pos, neg, meta = PromptCompiler.compile("нарисуй трактор Беларусь на поле")
        self.assertTrue(meta.get("unmatched_fallback"))
        self.assertIsNone(meta.get("subject"))
        self.assertIn("трактор беларусь на поле", pos.lower())
        self.assertNotIn("нарисуй", pos.lower())
        self.assertTrue(len(neg) > 10)

    def test_translate_prompt_to_sdxl_tags_validates_english_only(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {"content": "Belarus MTZ-82 tractor in green summer field, sunlit, photorealistic"}
        res = translate_prompt_to_sdxl_tags("трактор Беларусь в поле", mock_ai)
        self.assertIn("Belarus MTZ-82 tractor", res)

        # Ответ с кириллицей (или дефолтный mock "Ответ от LLM") должен отбраковываться
        mock_ai.send_chat.return_value = {"content": "Ответ от LLM"}
        self.assertIsNone(translate_prompt_to_sdxl_tags("трактор Беларусь в поле", mock_ai))


class TestRegistryAndPermissionsForImageTools(unittest.TestCase):
    """Проверка регистрации инструментов, схем и политики разрешений."""

    def test_tools_registered_and_signatures_match_parameters(self):
        image_tool_names = ("generate_image", "edit_image", "get_active_image", "select_image")
        schemas = {s["function"]["name"]: s for s in get_tools_schema()}

        for name in image_tool_names:
            self.assertIn(name, TOOLS)
            self.assertIn(name, TOOL_PARAMETERS)
            self.assertIn(name, schemas)

            fn = TOOLS[name]["function"]
            sig_params = set(inspect.signature(fn).parameters.keys())
            schema_props = set(TOOL_PARAMETERS[name]["properties"].keys())
            self.assertEqual(sig_params, schema_props, f"Parameter mismatch for {name}")

    def test_permissions_levels_for_image_tools(self):
        mgr = PermissionManager()

        # get_active_image всегда SAFE
        self.assertEqual(mgr.assess_tool("get_active_image").risk_level, RiskLevel.SAFE)
        self.assertFalse(mgr.assess_tool("get_active_image").requires_confirmation)

        # Мутации изображений имеют LOW (автоодобрение в NORMAL, запрос в STRICT, запрет в READ_ONLY)
        for t in ("generate_image", "edit_image", "select_image"):
            ass_normal = mgr.assess_tool(t, {"prompt": "test", "instruction": "test", "file_path": "a.png"})
            self.assertEqual(ass_normal.risk_level, RiskLevel.LOW)
            self.assertFalse(ass_normal.requires_confirmation)
            self.assertTrue(ass_normal.allowed)

        mgr.set_policy(SecurityPolicy.STRICT)
        self.assertTrue(mgr.assess_tool("generate_image", {"prompt": "cat"}).requires_confirmation)
        self.assertTrue(mgr.assess_tool("edit_image", {"instruction": "red"}).requires_confirmation)

        mgr.set_policy(SecurityPolicy.READ_ONLY)
        self.assertTrue(mgr.assess_tool("get_active_image").allowed)
        self.assertFalse(mgr.assess_tool("generate_image", {"prompt": "cat"}).allowed)
        self.assertFalse(mgr.assess_tool("edit_image", {"instruction": "red"}).allowed)


class TestAgentNativeImageToolOrchestration(unittest.TestCase):
    """Сквозные тесты Agent.process() с Qwen Native Tool Calling и ImageAgent."""

    def setUp(self):
        reset_fallback_image_context()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.mem = MemoryManager(storage_path=self.tmp_path / "mem.json")
        self.ctx = ContextManager(memory_manager=self.mem)
        self.captured_prompts = []

    def tearDown(self):
        reset_fallback_image_context()
        self.tmp_dir.cleanup()

    def _build_mock_agent(self, ai_side_effect, perm_mgr=None):
        mock_ai = MagicMock()
        mock_ai.send_chat.side_effect = ai_side_effect
        agent = Agent(
            memory_manager=self.mem,
            context_manager=self.ctx,
            ai_client=mock_ai,
            permission_manager=perm_mgr,
            bridge=None,
            image_context_path=self.tmp_path / "img_ctx.json",
        )
        img_agent = ImageAgent(output_dir=str(self.tmp_path / "out"))
        agent.agent_registry.register(img_agent)
        return agent, mock_ai, img_agent

    def test_native_generate_then_context_aware_edit_propagates_artifacts(self):
        out_gen = self.tmp_path / "out" / "gen_1.png"
        out_edit = self.tmp_path / "out" / "edit_1.png"
        out_gen.parent.mkdir(parents=True, exist_ok=True)
        _make_real_png(out_gen, color=(120, 80, 40))
        _make_real_png(out_edit, color=(40, 120, 80))

        # Запрос 1 не перехватывается regex fast-path (косвенная формулировка), идёт в Qwen
        call_seq_1 = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_gen",
                        "function": {
                            "name": "generate_image",
                            "arguments": {
                                "prompt": "vintage white Lada Niva 2121 on rocky stormy sea coast, waves, overcast",
                                "aspect_ratio": "landscape",
                            },
                        },
                    }
                ],
            },
            {
                "content": "Готово, я сгенерировал изображение с белой Нивой 2121 на берегу штормового моря.",
                "tool_calls": [],
            },
        ]

        agent, mock_ai, _ = self._build_mock_agent(call_seq_1)

        with patch.object(agent, "run_subagent") as mock_sub:
            from tools.agents.result import AgentResult
            mock_sub.return_value = AgentResult.ok(
                message="Изображение успешно сгенерировано: gen_1.png",
                created_files=[str(out_gen)],
                data={
                    "positive_prompt": "vintage white Lada Niva 2121 on rocky stormy sea coast, waves, overcast",
                    "negative_prompt": "blurry",
                    "width": 1216,
                    "height": 832,
                },
            )

            resp1 = agent.process("Очень хочется увидеть белую Ниву 2121 у штормового моря")
            self.assertEqual(resp1["type"], "chat")
            self.assertEqual(resp1["created_files"], [str(out_gen)])
            self.assertEqual(len(resp1["artifacts"]), 1)
            self.assertEqual(agent.image_context.get_active_image_path(validate_disk=True), str(out_gen))

            # Проверяем skip_compile=True для английского промпта Qwen и _permission_approved=True
            sub_kwargs = mock_sub.call_args[1]
            self.assertTrue(sub_kwargs.get("skip_compile"))
            self.assertTrue(sub_kwargs.get("_permission_approved"))
            self.assertEqual(sub_kwargs.get("width"), 1216)
            self.assertEqual(sub_kwargs.get("height"), 832)

        # Запрос 2: косвенная правка без regex-триггеров -> Qwen видит контекст активного PNG
        call_seq_2 = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_edit",
                        "function": {
                            "name": "edit_image",
                            "arguments": {
                                "instruction": "добавь яркое закатное освещение",
                                "edit_type": "lighting",
                                "positive_prompt": "vintage white Lada Niva 2121 on stormy sea coast, dramatic golden sunset lighting, clouds",
                                "denoise": 0.52,
                            },
                        },
                    }
                ],
            },
            {
                "content": "Освещение обновлено на закатное.",
                "tool_calls": [],
            },
        ]
        mock_ai.send_chat.side_effect = call_seq_2

        with patch.object(agent, "run_subagent") as mock_sub2:
            from tools.agents.result import AgentResult
            mock_sub2.return_value = AgentResult.ok(
                message="Изображение успешно отредактировано: edit_1.png",
                created_files=[str(out_edit)],
                data={"width": 1216, "height": 832},
            )

            resp2 = agent.process("Можем ли мы придать этому кадру более драматичный золотой закат?")
            self.assertEqual(resp2["type"], "chat")
            self.assertEqual(resp2["created_files"], [str(out_edit)])
            self.assertEqual(len(resp2["artifacts"]), 1)
            self.assertEqual(agent.image_context.get_active_image_path(validate_disk=True), str(out_edit))

            # Проверяем, что системный промпт первого вызова содержал контекст активного изображения
            first_call_msgs = mock_ai.send_chat.call_args_list[-2][0][0]
            self.assertIn("КОНТЕКСТ АКТИВНОГО ИЗОБРАЖЕНИЯ В СЕССИИ", first_call_msgs[0]["content"])
            self.assertIn("gen_1.png", first_call_msgs[0]["content"])
            # Базовый системный промпт ContextManager остался чистым
            self.assertNotIn("КОНТЕКСТ АКТИВНОГО ИЗОБРАЖЕНИЯ", agent.context_manager.get_system_prompt())

            # Проверяем, что source_image_path в ImageAgent был gen_1.png и positive_prompt сохранён
            sub2_kwargs = mock_sub2.call_args[1]
            self.assertEqual(sub2_kwargs.get("action"), "edit")
            self.assertEqual(sub2_kwargs.get("source_image_path"), str(out_gen))
            self.assertIn("golden sunset lighting", mock_sub2.call_args[1].get("task", "") or mock_sub2.call_args[0][0] if mock_sub2.call_args[0] else "")

    def test_no_double_confirmation_in_strict_mode(self):
        perm = PermissionManager(policy=SecurityPolicy.STRICT)
        out_gen = self.tmp_path / "strict_gen.png"
        _make_real_png(out_gen)

        confirm_calls = []
        old_handler = get_confirmation_handler()
        set_confirmation_handler(lambda name, kw: (confirm_calls.append(name), True)[1])

        try:
            agent, _, img_agent = self._build_mock_agent(
                [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {
                                    "name": "generate_image",
                                    "arguments": {"prompt": "red apple on table"},
                                },
                            }
                        ],
                    },
                    {"content": "Готово", "tool_calls": []},
                ],
                perm_mgr=perm,
            )

            with patch.object(img_agent.client, "is_available", return_value=True), \
                 patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
                 patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}), \
                 patch.object(img_agent.client, "queue_prompt", return_value={"prompt_id": "pid_strict"}), \
                 patch.object(img_agent.client, "get_history", return_value={
                     "status": {"completed": True},
                     "outputs": {"7": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}},
                 }), \
                 patch.object(img_agent.client, "view_image", return_value=out_gen.read_bytes()):
                resp = agent.process("Мне нужно изображение красного яблока")
                self.assertEqual(resp["type"], "chat")
                self.assertEqual(len(resp["created_files"]), 1)
                self.assertEqual(confirm_calls, ["generate_image"])
        finally:
            set_confirmation_handler(old_handler)

    def test_fast_path_translates_unmatched_cyrillic_before_vram_unload(self):
        out_gen = self.tmp_path / "fast_tr.png"
        _make_real_png(out_gen)

        agent, mock_ai, img_agent = self._build_mock_agent(
            [{"content": "classic Soviet Niva 2121 offroad SUV driving in forest, muddy road, photorealistic"}]
        )
        captured_wf = []

        with patch.object(img_agent.client, "is_available", return_value=True), \
             patch.object(img_agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}), \
             patch.object(img_agent.vram_manager, "restore_after_image_generation", return_value={"success": True}), \
             patch.object(img_agent.client, "queue_prompt", side_effect=lambda wf: (captured_wf.append(wf), {"prompt_id": "pid_tr"})[1]), \
             patch.object(img_agent.client, "get_history", return_value={
                 "status": {"completed": True},
                 "outputs": {"7": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}},
             }), \
             patch.object(img_agent.client, "view_image", return_value=out_gen.read_bytes()):
            resp = agent.process("нарисуй трактор Беларусь на пашне")
            self.assertEqual(resp["type"], "image")
            self.assertTrue(resp["success"])
            self.assertTrue(mock_ai.send_chat.called)
            self.assertEqual(len(captured_wf), 1)
            self.assertIn("Niva 2121", captured_wf[0]["2"]["inputs"]["text"])


class TestArtifactCardOnEditButton(unittest.TestCase):
    """Проверка кнопки редактирования на ImageArtifactCard и совместимости с FileArtifactCard."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.img_path = _make_real_png(Path(self.tmp_dir.name) / "card_test.png")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        self.tmp_dir.cleanup()

    def test_on_edit_callback_invoked_and_safe_for_file_cards(self):
        picked = []
        art_img = Artifact.from_image(path=self.img_path, prompt="test card")
        card = create_artifact_card(
            self.root,
            art_img,
            compact=False,
            on_edit=lambda path, meta: picked.append((path, meta)),
        )
        self.assertIsInstance(card, ImageArtifactCard)
        card.on_edit_image()
        self.assertEqual(len(picked), 1)
        self.assertEqual(Path(picked[0][0]).resolve(), Path(self.img_path).resolve())
        self.assertEqual(picked[0][1].get("prompt"), "test card")

        # FileArtifactCard не должен падать, если on_edit передан в фабрику create_artifact_card
        art_doc = Artifact(name="doc.pdf", type=ArtifactType.DOCUMENT, path="data/doc.pdf")
        file_card = create_artifact_card(
            self.root,
            art_doc,
            compact=True,
            on_edit=lambda path, meta: picked.append((path, meta)),
        )
        self.assertIsInstance(file_card, FileArtifactCard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
