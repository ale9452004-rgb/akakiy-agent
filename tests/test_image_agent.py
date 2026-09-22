"""
Unit-тесты для ImageAgent и ComfyUIClient (Task: ImageAgent v1).

Не требуют наличия реального GPU или запущенного ComfyUI воркера.
Все сетевые вызовы мокируются через unittest.mock.
"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.agents import (
    AgentContext,
    AgentResult,
    ImageAgent,
    ComfyUIClient,
    get_agent_registry,
    reset_agent_registry
)


class TestImageAgentUnit(unittest.TestCase):
    """Модульные тесты ImageAgent с изоляцией от GPU и внешних сервисов."""

    def setUp(self):
        reset_agent_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.agent = ImageAgent(
            output_dir=str(self.output_dir),
            timeout=5
        )

    def tearDown(self):
        reset_agent_registry()
        self.temp_dir.cleanup()

    def test_workflow_structure(self):
        """Проверка структуры генерируемого графа ComfyUI для SDXL-Lightning."""
        wf = self.agent.build_workflow(
            prompt="Космический кот",
            negative_prompt="мутный, дефекты",
            seed=42,
            width=1024,
            height=1024,
            steps=4,
            cfg=1.5,
            sampler="euler",
            scheduler="sgm_uniform",
            checkpoint="sdxl_lightning_4step.safetensors"
        )
        self.assertIn("1", wf)
        self.assertIn("2", wf)
        self.assertIn("3", wf)
        self.assertIn("4", wf)
        self.assertIn("5", wf)
        self.assertIn("6", wf)
        self.assertIn("7", wf)

        self.assertEqual(wf["1"]["inputs"]["ckpt_name"], "sdxl_lightning_4step.safetensors")
        self.assertEqual(wf["2"]["inputs"]["text"], "Космический кот")
        self.assertEqual(wf["3"]["inputs"]["text"], "мутный, дефекты")
        self.assertEqual(wf["4"]["inputs"]["width"], 1024)
        self.assertEqual(wf["5"]["inputs"]["steps"], 4)
        self.assertEqual(wf["5"]["inputs"]["cfg"], 1.5)
        self.assertEqual(wf["5"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(wf["5"]["inputs"]["scheduler"], "sgm_uniform")

    def test_empty_prompt_fails(self):
        """ImageAgent отклоняет задачу с пустым prompt."""
        ctx = AgentContext(task="   ")
        res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertIn("Не указан текст запроса", res.error)

    def test_disabled_agent_fails(self):
        """Отключенный ImageAgent не запускает генерацию."""
        self.agent.enabled = False
        ctx = AgentContext(task="Котик")
        res = self.agent.run(ctx)

        self.assertFalse(res.success)
        self.assertIn("отключен", res.error)

    def test_server_unavailable_fails_gracefully(self):
        """При недоступности сервера возвращается понятный fail без падения."""
        with patch.object(self.agent.client, "is_available", return_value=False):
            ctx = AgentContext(task="Котик на Марсе")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("недоступен", res.error)

    def test_queue_prompt_http_error(self):
        """Ошибка HTTP при отправке задачи в ComfyUI возвращает AgentResult.fail."""
        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")

            ctx = AgentContext(task="Котик")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("Ошибка при отправке задачи", res.error)

    def test_history_timeout_fails(self):
        """Таймаут ожидания генерации возвращает AgentResult.fail."""
        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "test-uuid"}), \
             patch.object(self.agent.client, "get_history", return_value=None):

            self.agent.timeout = 1
            ctx = AgentContext(task="Котик", metadata={"timeout": 1})
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("Превышено время ожидания", res.error)

    def test_history_worker_error_fails(self):
        """Ошибка внутри ComfyUI графа корректно перехватывается."""
        error_hist = {
            "status": {
                "status_str": "error",
                "completed": False,
                "messages": ["OutOfMemoryError: CUDA out of memory"]
            }
        }
        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "test-uuid"}), \
             patch.object(self.agent.client, "get_history", return_value=error_hist):

            ctx = AgentContext(task="Котик")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("Ошибка выполнения графа", res.error)
            self.assertIn("CUDA out of memory", res.error)

    def test_missing_output_images_fails(self):
        """Завершенная задача без изображений в outputs возвращает ошибку."""
        hist_empty = {
            "status": {
                "status_str": "success",
                "completed": True
            },
            "outputs": {
                "7": {}  # Нет ключа images
            }
        }
        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "test-uuid"}), \
             patch.object(self.agent.client, "get_history", return_value=hist_empty):

            ctx = AgentContext(task="Котик", metadata={"timeout": 2})
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("не вернул выходное изображение", res.error)

    def test_view_image_empty_bytes_fails(self):
        """Получение пустого файла через /view возвращает fail."""
        hist_ok = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "7": {
                    "images": [{"filename": "out.png", "subfolder": "", "type": "output"}]
                }
            }
        }
        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "test-uuid"}), \
             patch.object(self.agent.client, "get_history", return_value=hist_ok), \
             patch.object(self.agent.client, "view_image", return_value=b""):

            ctx = AgentContext(task="Котик")
            res = self.agent.run(ctx)

            self.assertFalse(res.success)
            self.assertIn("пустое изображение", res.error)

    def test_successful_mocked_generation_flow(self):
        """Полный успешный мок-флоу: постановка задачи, ожидание, скачивание /view, сохранение."""
        fake_png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRmock_data"
        hist_ok = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "7": {
                    "images": [{"filename": "ComfyUI_0001.png", "subfolder": "", "type": "output"}]
                }
            }
        }

        with patch.object(self.agent.client, "is_available", return_value=True), \
             patch.object(self.agent.client, "queue_prompt", return_value={"prompt_id": "uuid-123"}), \
             patch.object(self.agent.client, "get_history", return_value=hist_ok), \
             patch.object(self.agent.client, "view_image", return_value=fake_png_data), \
             patch.object(self.agent.client, "free_memory", return_value=True) as mock_free:

            ctx = AgentContext(
                task="Золотой лев на скале",
                metadata={"width": 1024, "height": 1024, "seed": 777}
            )
            res = self.agent.run(ctx)

            self.assertTrue(res.success)
            self.assertIn("успешно сгенерировано", res.message)
            self.assertEqual(len(res.created_files), 1)

            saved_file = Path(res.created_files[0])
            self.assertTrue(saved_file.exists())
            self.assertEqual(saved_file.read_bytes(), fake_png_data)
            self.assertEqual(res.data["prompt"], "Золотой лев на скале")
            self.assertEqual(res.data["seed"], 777)
            self.assertEqual(res.data["file_size_bytes"], len(fake_png_data))
            mock_free.assert_called_once()

    def test_safe_unique_filename_format(self):
        """Проверка безопасного формата генерируемого имени файла."""
        name1 = self.agent._generate_safe_filename()
        name2 = self.agent._generate_safe_filename()

        self.assertTrue(name1.startswith("img_"))
        self.assertTrue(name1.endswith(".png"))
        self.assertNotEqual(name1, name2)

    def test_image_agent_in_default_registry(self):
        """ImageAgent автоматически регистрируется в глобальном реестре под именем 'image'."""
        reg = get_agent_registry()
        self.assertTrue(reg.has("image"))
        agent = reg.get("image")
        self.assertIsInstance(agent, ImageAgent)
        self.assertEqual(agent.name, "image")


if __name__ == "__main__":
    unittest.main()
