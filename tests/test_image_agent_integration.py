r"""
Интеграционный тест для ImageAgent с реальным ComfyUI Worker.

ВНИМАНИЕ:
Данный тест выполняет реальную генерацию изображения через GPU (RTX 4070)
и поэтому изолирован от обычного быстрого запуска unit-тестов.

Для ручного запуска:
PowerShell:
$env:RUN_IMAGE_INTEGRATION="1"; .\.venv\Scripts\python.exe -m unittest tests/test_image_agent_integration.py
"""

import os
from pathlib import Path
import unittest

from tools.agent import Agent
from tools.agents import ImageAgent, AgentContext


class TestImageAgentIntegration(unittest.TestCase):
    """Реальный интеграционный тест с живым ComfyUI сервером на 127.0.0.1:8188."""

    @unittest.skipUnless(
        os.environ.get("RUN_IMAGE_INTEGRATION") == "1",
        "Интеграционный тест с реальным ComfyUI Worker запускается только при RUN_IMAGE_INTEGRATION=1."
    )
    def test_real_comfyui_image_generation(self):
        """Проверка реального сквозного конвейера Agent -> ImageAgent -> ComfyUI -> PNG."""
        image_agent = ImageAgent()
        if not image_agent.client.is_available():
            self.skipTest("ComfyUI Worker не запущен на http://127.0.0.1:8188.")

        main_agent = Agent()
        task_prompt = "A high-tech research drone hovering over neon crystal cave, cinematic lighting, 8k"

        res = main_agent.run_subagent(
            name="image",
            task=task_prompt,
            width=1024,
            height=1024,
            steps=4,
            seed=424242
        )

        self.assertTrue(res.success, f"Генерация завершилась с ошибкой: {res.error}")
        self.assertIn("успешно сгенерировано", res.message)
        self.assertEqual(len(res.created_files), 1)

        file_path = Path(res.created_files[0])
        self.assertTrue(file_path.exists(), f"Файл не найден на диске: {file_path}")
        self.assertGreater(file_path.stat().st_size, 500_000, "Размер файла подозрительно мал (< 500 KB)")

        # Проверяем директорию сохранения
        self.assertIn("data", file_path.parts)
        self.assertIn("generated", file_path.parts)
        self.assertIn("images", file_path.parts)

        # Проверяем валидность графического файла PNG без внешних зависимостей (через struct)
        import struct
        with open(file_path, "rb") as f:
            header = f.read(26)
        # Сигнатура PNG
        self.assertTrue(header.startswith(b"\x89PNG\r\n\x1a\n"), "Файл не является валидным PNG")
        # Чанк IHDR
        self.assertEqual(header[12:16], b"IHDR", "Отсутствует чанк IHDR")
        # Размеры width и height (big-endian 32-bit uint)
        width, height = struct.unpack(">II", header[16:24])
        self.assertEqual((width, height), (1024, 1024))


if __name__ == "__main__":
    unittest.main()
