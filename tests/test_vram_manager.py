"""
Unit-тесты для VRAMManager и его интеграции с ImageAgent.

Все сетевые вызовы и системные команды мокируются.
Тесты изолированы от наличия GPU, Ollama и ComfyUI.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.agents.context import AgentContext
from tools.agents.image import ImageAgent
from tools.vram import VRAMManager, reset_vram_manager


class TestVRAMManager(unittest.TestCase):
    """Модульные тесты функциональности VRAMManager."""

    def setUp(self):
        reset_vram_manager()
        self.vram = VRAMManager(
            ollama_url="http://localhost:11434",
            comfyui_url="http://127.0.0.1:8188",
            default_model="qwen3:8b",
            timeout=5
        )

    def tearDown(self):
        reset_vram_manager()

    # 1. Успешная выгрузка Ollama
    @patch("requests.post")
    @patch("requests.get")
    def test_unload_ollama_success(self, mock_get, mock_post):
        """Успешная выгрузка Ollama возвращает success=True, unloaded=True."""
        # Модели загружены в /api/ps
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen3:8b", "model": "qwen3:8b"}]}
        )
        # Выгрузка через /api/generate
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"model": "qwen3:8b", "done": True, "done_reason": "unload"}
        )

        res = self.vram.unload_ollama("qwen3:8b")
        self.assertTrue(res["success"])
        self.assertTrue(res["unloaded"])
        self.assertFalse(res.get("already_unloaded", False))
        self.assertEqual(res.get("done_reason"), "unload")
        mock_post.assert_called_once_with(
            "http://localhost:11434/api/generate",
            json={"model": "qwen3:8b", "keep_alive": 0},
            timeout=5
        )

    # 2. Ollama уже выгружен
    @patch("requests.post")
    @patch("requests.get")
    def test_unload_ollama_already_unloaded(self, mock_get, mock_post):
        """Если модель уже отсутствует в /api/ps, возвращается success=True, already_unloaded=True."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": []}
        )

        res = self.vram.unload_ollama("qwen3:8b")
        self.assertTrue(res["success"])
        self.assertFalse(res["unloaded"])
        self.assertTrue(res["already_unloaded"])
        # /api/generate не должен вызываться, если уже выгружено
        mock_post.assert_not_called()

    # 3. Ошибка Ollama
    @patch("requests.post")
    @patch("requests.get")
    def test_unload_ollama_error(self, mock_get, mock_post):
        """Ошибка HTTP или соединение с Ollama возвращает success=False."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen3:8b"}]}
        )
        mock_post.return_value = MagicMock(
            status_code=500,
            text="Internal Server Error"
        )

        res = self.vram.unload_ollama("qwen3:8b")
        self.assertFalse(res["success"])
        self.assertIn("500", res["error"])

    # 4. Успешный /free ComfyUI
    @patch("requests.post")
    def test_free_comfyui_success(self, mock_post):
        """Успешный вызов POST /free возвращает success=True."""
        mock_post.return_value = MagicMock(status_code=200)

        res = self.vram.free_comfyui()
        self.assertTrue(res["success"])
        mock_post.assert_called_once_with(
            "http://127.0.0.1:8188/free",
            json={"unload_models": True, "free_memory": True},
            timeout=5
        )

    # 5. Ошибка /free
    @patch("requests.post")
    def test_free_comfyui_error(self, mock_post):
        """Сбой или сетевая ошибка POST /free возвращает success=False."""
        mock_post.return_value = MagicMock(
            status_code=502,
            text="Bad Gateway"
        )

        res = self.vram.free_comfyui()
        self.assertFalse(res["success"])
        self.assertIn("502", res["error"])

    # 6. GPU stats
    @patch("subprocess.check_output")
    def test_gpu_stats_success_and_fallback(self, mock_subp):
        """Парсинг вывода nvidia-smi и безопасная деградация при ошибке."""
        # 6a. Успешный парсинг
        mock_subp.return_value = " 2500, 5688, 8188 \n"
        stats = self.vram.get_gpu_stats()
        self.assertTrue(stats["available"])
        self.assertEqual(stats["used"], 2500)
        self.assertEqual(stats["free"], 5688)
        self.assertEqual(stats["total"], 8188)

        # 6b. Ошибка вызова (например, нет GPU или nvidia-smi)
        mock_subp.side_effect = FileNotFoundError("nvidia-smi not found")
        stats_err = self.vram.get_gpu_stats()
        self.assertFalse(stats_err["available"])
        self.assertEqual(stats_err["used"], 0)
        self.assertEqual(stats_err["free"], 0)
        self.assertEqual(stats_err["total"], 0)
        self.assertIn("error", stats_err)

    # 7. Prepare flow
    @patch.object(VRAMManager, "get_gpu_stats")
    @patch.object(VRAMManager, "unload_ollama")
    def test_prepare_flow(self, mock_unload, mock_stats):
        """prepare_for_image_generation собирает метрики и выгружает Ollama."""
        mock_stats.side_effect = [
            {"available": True, "used": 4500, "free": 3688, "total": 8188},  # initial
            {"available": True, "used": 1500, "free": 6688, "total": 8188},  # after unload
            {"available": True, "used": 4500, "free": 3688, "total": 8188},  # second initial (fail case)
        ]
        mock_unload.return_value = {"success": True, "unloaded": True}

        res = self.vram.prepare_for_image_generation()
        self.assertTrue(res["success"])
        self.assertEqual(res["gpu_initial"]["used"], 4500)
        self.assertEqual(res["gpu_after_unload"]["used"], 1500)
        mock_unload.assert_called_once()

        # Если выгрузка не удалась, prepare возвращает success=False
        mock_unload.return_value = {"success": False, "error": "Connection refused"}
        res_fail = self.vram.prepare_for_image_generation()
        self.assertFalse(res_fail["success"])
        self.assertIn("Connection refused", res_fail["error"])

    # 8. Restore flow
    @patch.object(VRAMManager, "get_gpu_stats")
    @patch.object(VRAMManager, "free_comfyui")
    def test_restore_flow(self, mock_free, mock_stats):
        """restore_after_image_generation вызывает /free и не загружает Ollama принудительно."""
        mock_stats.return_value = {"available": True, "used": 1200, "free": 6988, "total": 8188}
        mock_free.return_value = {"success": True, "message": "OK"}

        res = self.vram.restore_after_image_generation()
        self.assertTrue(res["success"])
        self.assertEqual(res["gpu_after_restore"]["used"], 1200)
        mock_free.assert_called_once()


class TestImageAgentVRAMIntegration(unittest.TestCase):
    """Тесты интеграции ImageAgent с VRAMManager."""

    def setUp(self):
        reset_vram_manager()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.mock_vram = MagicMock(spec=VRAMManager)
        self.agent = ImageAgent(
            output_dir=str(self.output_dir),
            timeout=5,
            vram_manager=self.mock_vram
        )

    def tearDown(self):
        reset_vram_manager()
        self.temp_dir.cleanup()

    # 9. ImageAgent вызывает prepare перед генерацией
    def test_image_agent_calls_prepare_before_generation(self):
        """ImageAgent вызывает prepare_for_image_generation перед отправкой задачи."""
        self.mock_vram.prepare_for_image_generation.return_value = {
            "success": False,
            "error": "Ollama VRAM unlock failure"
        }

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt") as mock_queue:

            ctx = AgentContext(task="Киберкот")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("Ошибка подготовки VRAM", res.error)
            self.assertIn("Ollama VRAM unlock failure", res.error)
            # Генерация не должна начинаться вслепую
            mock_queue.assert_not_called()
            self.mock_vram.prepare_for_image_generation.assert_called_once()

    # 10. ImageAgent вызывает /free через finally при успешной генерации
    def test_image_agent_calls_free_in_finally_on_success(self):
        """При успешной генерации restore_after_image_generation вызывается в finally."""
        self.mock_vram.prepare_for_image_generation.return_value = {"success": True}
        self.mock_vram.restore_after_image_generation.return_value = {"success": True}

        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdata"
        hist_ok = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"7": {"images": [{"filename": "cat.png", "subfolder": "", "type": "output"}]}}
        }

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "p-1"}), \
             patch.object(self.agent.client, "get_history", return_value=hist_ok), \
             patch.object(self.agent.client, "view_image", return_value=fake_png):

            ctx = AgentContext(task="Кот на крыше")
            res = self.agent.run(ctx)

            self.assertTrue(res.success)
            self.mock_vram.prepare_for_image_generation.assert_called_once()
            self.mock_vram.restore_after_image_generation.assert_called_once()

    # 11. ImageAgent вызывает /free при ошибке генерации
    def test_image_agent_calls_free_on_generation_error(self):
        """При исключении или ошибке воркера restore_after_image_generation все равно вызывается."""
        self.mock_vram.prepare_for_image_generation.return_value = {"success": True}
        self.mock_vram.restore_after_image_generation.return_value = {"success": True}

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", side_effect=RuntimeError("ComfyUI crashed")):

            ctx = AgentContext(task="Кот на крыше")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("ComfyUI crashed", res.error)
            # Гарантированный вызов очистки в finally
            self.mock_vram.restore_after_image_generation.assert_called_once()

    # 12. Созданный PNG сохраняется даже если cleanup завершился ошибкой
    def test_saved_png_preserved_even_if_cleanup_fails(self):
        """Если /free вернул ошибку, созданный PNG сохраняется и возвращается с предупреждением."""
        self.mock_vram.prepare_for_image_generation.return_value = {"success": True}
        self.mock_vram.restore_after_image_generation.return_value = {
            "success": False,
            "error": "VRAM free request timed out"
        }

        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRsaved_data"
        hist_ok = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"7": {"images": [{"filename": "cat_clean_fail.png", "subfolder": "", "type": "output"}]}}
        }

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "p-2"}), \
             patch.object(self.agent.client, "get_history", return_value=hist_ok), \
             patch.object(self.agent.client, "view_image", return_value=fake_png):

            ctx = AgentContext(task="Белый тигр")
            res = self.agent.run(ctx)

            # Результат успешный, файл не потерян!
            self.assertTrue(res.success)
            self.assertEqual(len(res.created_files), 1)
            saved_path = Path(res.created_files[0])
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), fake_png)
            # В данных зафиксирована ошибка cleanup
            self.assertEqual(res.data.get("vram_cleanup_error"), "VRAM free request timed out")
            self.assertIn("Предупреждение", res.message)


if __name__ == "__main__":
    unittest.main()
