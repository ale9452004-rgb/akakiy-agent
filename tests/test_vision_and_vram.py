"""
Тесты Vision-контура (qwen3-vl:4b), настроек Vision-модели,
мультимодельной выгрузки VRAMManager и инструмента inspect_image (Step 2).
"""

import base64
import inspect
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from infrastructure.ollama_manager import (
    DEFAULT_MODEL,
    DEFAULT_VISION_MODEL,
    OllamaManager,
)
from ollama_client import MODEL as CLIENT_DEFAULT_MODEL, OllamaClient, encode_images_base64
from tools.agent import Agent
from tools.image_tools import (
    _normalize_bbox,
    inspect_image,
    reset_fallback_image_context,
)
from tools.memory import MemoryManager
from tools.context import ContextManager
from tools.permissions import PermissionManager, RiskLevel, SecurityPolicy
from tools.registry import TOOL_PARAMETERS, TOOLS
from tools.settings import AppSettings, reset_app_settings
from tools.vram import VRAMManager, reset_vram_manager
from ui.views import SettingsView


def _make_png(path: Path, color=(30, 140, 220), size=(200, 100)) -> str:
    img = Image.new("RGB", size, color=color)
    img.save(str(path), format="PNG")
    return str(path)


class TestAppSettingsAndOllamaVisionSupport(unittest.TestCase):
    """Настройки vision_model, базовая кодировка изображений и мультимодель OllamaManager."""

    def setUp(self):
        reset_app_settings()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.img_path = Path(_make_png(self.tmp_path / "sample.png", size=(200, 100)))

    def tearDown(self):
        reset_app_settings()
        self.tmp_dir.cleanup()

    def test_app_settings_vision_model_persistence(self):
        cfg_file = self.tmp_path / "settings.json"
        s1 = AppSettings(storage_path=cfg_file)
        self.assertEqual(s1.vision_model, DEFAULT_VISION_MODEL)

        s1.set("vision_model", "qwen3-vl:8b")
        s2 = AppSettings(storage_path=cfg_file)
        self.assertEqual(s2.vision_model, "qwen3-vl:8b")
        self.assertEqual(s2.get("vision_model"), "qwen3-vl:8b")

        # Пустое значение безопасно откатывается к DEFAULT_VISION_MODEL
        s2.from_dict({"vision_model": "   "})
        self.assertEqual(s2.vision_model, DEFAULT_VISION_MODEL)

    @patch("ollama_client.requests.post")
    def test_ollama_client_send_vision_query_and_ask_with_images(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {"content": '{"answer": "Один рыжий кот", "mask_bbox": [0.1, 0.2, 0.7, 0.9]}'}
            },
        )
        client = OllamaClient()
        self.assertEqual(CLIENT_DEFAULT_MODEL, "qwen3:8b")

        res = client.send_vision_query(
            prompt="Сколько котов?",
            images=self.img_path,
            model="qwen3-vl:4b",
            response_format="json",
        )
        self.assertIn("Один рыжий кот", res["content"])

        called_payload = mock_post.call_args[1]["json"]
        self.assertEqual(called_payload["model"], "qwen3-vl:4b")
        self.assertEqual(called_payload["format"], "json")
        self.assertEqual(len(called_payload["messages"]), 1)
        sent_b64 = called_payload["messages"][0]["images"][0]
        self.assertEqual(base64.b64decode(sent_b64), self.img_path.read_bytes())

        # Проверка ask с images: история не засоряется base64
        mock_post.reset_mock()
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "Вижу синий прямоугольник."}},
        )
        ans = client.ask("Что на картинке?", images=self.img_path, model="qwen3-vl:4b")
        self.assertIn("прямоугольник", ans)
        ask_payload = mock_post.call_args[1]["json"]
        self.assertEqual(ask_payload["model"], "qwen3-vl:4b")
        self.assertIn("images", ask_payload["messages"][-1])
        self.assertNotIn("images", client.messages[-2])  # user msg в истории чистый

        with self.assertRaises(FileNotFoundError):
            encode_images_base64(self.tmp_path / "missing.png")

    @patch("ollama_client.requests.post")
    def test_ollama_client_thinking_fallback_and_think_false(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {
                    "content": "",
                    "thinking": '{"answer": "Белая кружка на столе", "mask_bbox": [395, 300, 608, 582]}',
                }
            },
        )
        client = OllamaClient()
        res = client.send_vision_query(
            prompt="Где кружка?",
            images=self.img_path,
            response_format={"type": "object"},
            options={"num_predict": 512, "temperature": 0.1},
        )
        self.assertIn("Белая кружка", res["content"])
        called_payload = mock_post.call_args[1]["json"]
        self.assertIs(called_payload["think"], False)
        self.assertEqual(called_payload["options"]["num_predict"], 512)

    @patch("infrastructure.ollama_manager.requests.get")
    def test_ollama_manager_vision_model_check(self, mock_get):
        mgr = OllamaManager()
        self.assertEqual(DEFAULT_MODEL, "qwen3:8b")
        self.assertEqual(DEFAULT_VISION_MODEL, "qwen3-vl:4b")

        # Сервер доступен, но qwen3-vl:4b ещё не скачана
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen3:8b"}]},
        )
        ok, msg = mgr.check_vision_model_available()
        self.assertFalse(ok)
        self.assertIn("ollama pull qwen3-vl:4b", msg)

        # После загрузки модели
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen3:8b"}, {"name": "qwen3-vl:4b:latest"}]},
        )
        ok2, _ = mgr.check_vision_model_available()
        self.assertTrue(ok2)


class TestVRAMMultiModelUnload(unittest.TestCase):
    """Выгрузка всех загруженных моделей Ollama (qwen3:8b + qwen3-vl:4b) при model=None."""

    def setUp(self):
        reset_vram_manager()
        self.vram = VRAMManager(timeout=5)

    def tearDown(self):
        reset_vram_manager()

    @patch("requests.post")
    @patch("requests.get")
    def test_unload_all_loaded_models_when_model_is_none(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "models": [
                    {"name": "qwen3:8b", "model": "qwen3:8b"},
                    {"name": "qwen3-vl:4b", "model": "qwen3-vl:4b"},
                ]
            },
        )
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"done": True, "done_reason": "unload"},
        )

        res = self.vram.unload_ollama(model=None)
        self.assertTrue(res["success"])
        self.assertTrue(res["unloaded"])
        self.assertEqual(res["unloaded_models"], ["qwen3:8b", "qwen3-vl:4b"])
        self.assertEqual(mock_post.call_count, 2)
        unloaded_sent = [call[1]["json"]["model"] for call in mock_post.call_args_list]
        self.assertEqual(unloaded_sent, ["qwen3:8b", "qwen3-vl:4b"])

    @patch("requests.post")
    @patch("requests.get")
    def test_unload_none_when_ps_empty_does_not_post(self, mock_get, mock_post):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": []},
        )
        res = self.vram.unload_ollama(model=None)
        self.assertTrue(res["success"])
        self.assertFalse(res["unloaded"])
        self.assertTrue(res["already_unloaded"])
        mock_post.assert_not_called()


class TestInspectImageToolAndSettingsView(unittest.TestCase):
    """Регистрация, безопасность, нормализация bbox и оркестрация inspect_image."""

    def setUp(self):
        reset_app_settings()
        reset_fallback_image_context()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.img_path = _make_png(self.tmp_path / "scene.png", size=(1000, 500))

    def tearDown(self):
        reset_fallback_image_context()
        reset_app_settings()
        self.tmp_dir.cleanup()

    def test_inspect_image_registry_and_permissions(self):
        self.assertIn("inspect_image", TOOLS)
        self.assertIn("inspect_image", TOOL_PARAMETERS)
        sig_params = set(inspect.signature(inspect_image).parameters.keys())
        schema_props = set(TOOL_PARAMETERS["inspect_image"]["properties"].keys())
        self.assertEqual(sig_params, schema_props)

        mgr = PermissionManager(policy=SecurityPolicy.READ_ONLY)
        ass = mgr.assess_tool("inspect_image", {"question": "Что на картинке?"})
        self.assertEqual(ass.risk_level, RiskLevel.SAFE)
        self.assertFalse(ass.requires_confirmation)
        self.assertTrue(ass.allowed)

    def test_bbox_normalization(self):
        self.assertEqual(_normalize_bbox([0.1, 0.2, 0.8, 0.9]), [0.1, 0.2, 0.8, 0.9])
        # Обратные координаты и выход за границы зажимаются корректно
        self.assertEqual(_normalize_bbox([0.9, 1.2, -0.1, 0.3]), [0.0, 0.3, 0.9, 1.0])
        # Пиксельные координаты приводятся к 0..1 по размеру картинки
        self.assertEqual(
            _normalize_bbox([100, 50, 500, 250], img_width=1000, img_height=500),
            [0.1, 0.1, 0.5, 0.5],
        )
        # Вырожденная коробка отбрасывается
        self.assertIsNone(_normalize_bbox([0.5, 0.5, 0.501, 0.9]))
        # Смешанная (0..1 + 0..1000) и полная 0..1000 сетка Qwen3-VL
        self.assertEqual(
            _normalize_bbox([0.397, 300, 606, 578], img_width=1216, img_height=832, prefer_scale_1000=True),
            [0.397, 0.3, 0.606, 0.578],
        )
        self.assertEqual(
            _normalize_bbox([395, 300, 608, 582], img_width=1216, img_height=832, prefer_scale_1000=True),
            [0.395, 0.3, 0.608, 0.582],
        )

    @patch("infrastructure.ollama_manager.get_ollama_manager")
    @patch("ollama_client.requests.post")
    def test_agent_native_calling_inspect_image_with_bbox(self, mock_post, mock_get_mgr):
        mock_mgr = MagicMock()
        mock_mgr.check_vision_model_available.return_value = (True, "OK")
        mock_get_mgr.return_value = mock_mgr

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "message": {
                    "content": json.dumps(
                        {
                            "answer": "На изображении видно двух котов; второй сидит справа.",
                            "objects": [{"label": "second cat", "bbox": [0.55, 0.25, 0.92, 0.88]}],
                            "mask_bbox": [0.55, 0.25, 0.92, 0.88],
                        },
                        ensure_ascii=False,
                    )
                }
            },
        )

        mock_ai = MagicMock()
        mock_ai.send_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_inspect",
                        "function": {
                            "name": "inspect_image",
                            "arguments": {
                                "question": "Где находится второй кот?",
                                "return_bbox": True,
                            },
                        },
                    }
                ],
            },
            {
                "content": "Я проверил картинку: второй кот находится в правой части [0.55, 0.25, 0.92, 0.88].",
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
        agent.image_context.track_generation(file_path=self.img_path, prompt="two cats")

        resp = agent.process("Проверь картинку: сколько там объектов и где второй?")
        self.assertEqual(resp["type"], "chat")
        self.assertIn("0.55", resp["answer"])

        # Проверяем, что Qwen получил системную подсказку с упоминанием inspect_image
        sys_msg = mock_ai.send_chat.call_args_list[0][0][0][0]["content"]
        self.assertIn("inspect_image", sys_msg)

        # Проверяем, что в turn tool message ушёл нормализованный mask_bbox
        second_call_msgs = mock_ai.send_chat.call_args_list[1][0][0]
        tool_payload = json.loads(second_call_msgs[-1]["content"])
        self.assertEqual(tool_payload["mask_bbox"], [0.55, 0.25, 0.92, 0.88])
        self.assertEqual(tool_payload["vision_model"], DEFAULT_VISION_MODEL)

    @patch("infrastructure.ollama_manager.get_ollama_manager")
    def test_inspect_image_missing_vision_model_returns_pull_hint(self, mock_get_mgr):
        mock_mgr = MagicMock()
        mock_mgr.check_vision_model_available.return_value = (
            False,
            "Vision-модель 'qwen3-vl:4b' не найдена в Ollama. Загрузите её командой: ollama pull qwen3-vl:4b",
        )
        mock_get_mgr.return_value = mock_mgr

        res = inspect_image("Что на картинке?", image_path=self.img_path)
        self.assertFalse(res["success"])
        self.assertEqual(res.get("missing_vision_model"), "qwen3-vl:4b")
        self.assertIn("ollama pull qwen3-vl:4b", res["error"])

    def test_inspect_image_missing_file_fails_cleanly(self):
        res = inspect_image("Что тут?", image_path=str(self.tmp_path / "absent.png"))
        self.assertFalse(res["success"])
        self.assertIn("не найден", res["error"].lower())

    def test_settings_view_renders_vision_model_safely(self):
        root = tk.Tk()
        root.withdraw()
        try:
            mock_shell = MagicMock()
            view_mock = SettingsView(root, shell=mock_shell)
            labels_text = "\n".join(
                w.cget("text")
                for w in view_mock.winfo_children()[1].winfo_children()
                if isinstance(w, tk.Label)
            )
            self.assertIn("qwen3-vl:4b", labels_text)
            self.assertNotIn("MagicMock", labels_text)

            real_shell = MagicMock()
            real_shell.settings = AppSettings(storage_path=self.tmp_path / "s_ui.json")
            real_shell.settings.set("vision_model", "qwen3-vl:4b-instruct")
            view_real = SettingsView(root, shell=real_shell)
            labels_text_real = "\n".join(
                w.cget("text")
                for w in view_real.winfo_children()[1].winfo_children()
                if isinstance(w, tk.Label)
            )
            self.assertIn("qwen3-vl:4b-instruct", labels_text_real)
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
