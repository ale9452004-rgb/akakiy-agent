"""
Сквозной интеграционный тест VRAM Manager и ImageAgent (Task: VRAM Manager v1).

Проверяет реальный жизненный цикл GPU-памяти на RTX 4070:
1. Замер начальной VRAM.
2. Прогрев/загрузка Ollama qwen3:8b через OllamaClient.
3. Вызов ImageAgent с автоматической подготовкой VRAM (выгрузка Ollama).
4. Проверка факта выгрузки Ollama (освобождение VRAM).
5. Реальная генерация изображения через ComfyUI Worker (SDXL-Lightning).
6. Проверка валидности полученного PNG (заголовок, 1024x1024 через struct).
7. Замер VRAM после ComfyUI /free.
8. Повторный обычный запрос к OllamaClient.
9. Проверка автоматической перезагрузки Ollama и получения ответа.

Тест запускается ТОЛЬКО при явном указании переменной окружения:
$env:RUN_IMAGE_VRAM_INTEGRATION='1'
"""

import os
from pathlib import Path
import struct
import unittest

from ollama_client import OllamaClient
from tools.agents import AgentContext, ImageAgent
from tools.vram import VRAMManager


class TestImageVRAMIntegration(unittest.TestCase):
    """Сквозной интеграционный тест VRAM Manager на реальном оборудовании."""

    def setUp(self):
        if os.environ.get("RUN_IMAGE_VRAM_INTEGRATION") != "1":
            self.skipTest(
                "Пропуск интеграционного теста VRAM. "
                "Для запуска установите: $env:RUN_IMAGE_VRAM_INTEGRATION='1'"
            )
        self.vram_mgr = VRAMManager()
        self.ollama = OllamaClient()
        self.agent = ImageAgent(timeout=120)

        # Проверка доступности воркера ComfyUI
        if not self.agent.client.is_available():
            self.skipTest(
                "ComfyUI Worker недоступен на 127.0.0.1:8188. "
                "Запустите воркер перед проведением интеграционного теста."
            )

    def test_e2e_vram_lifecycle(self):
        """Полный сквозной цикл VRAM: Ollama load -> unload -> ComfyUI gen -> /free -> Ollama reload."""
        print("\n" + "=" * 70)
        print(">>> НАЧАЛО ИНТЕГРАЦИОННОГО ТЕСТА VRAM MANAGER V1 <<<")

        # 1. Проверить начальную VRAM
        vram_initial = self.vram_mgr.get_gpu_stats()
        print(f"\n[1] Начальная VRAM:")
        print(f"    Used: {vram_initial.get('used')} MiB, Free: {vram_initial.get('free')} MiB, Total: {vram_initial.get('total')} MiB")

        # 2. Загрузить/обнаружить qwen3:8b через OllamaClient
        print("\n[2] Загрузка модели Ollama qwen3:8b в память...")
        chat_res1 = self.ollama.send_chat([{"role": "user", "content": "Привет, Акакий! Ответь одним словом: Готов."}])
        self.assertTrue(len(chat_res1.get("content", "")) > 0, "Ollama не вернула ответ на начальный запрос.")
        print(f"    Ответ Ollama: '{chat_res1['content'].strip()}'")

        vram_with_ollama = self.vram_mgr.get_gpu_stats()
        ollama_loaded = self.vram_mgr.is_model_loaded("qwen3:8b")
        print(f"    VRAM с загруженной Ollama: Used={vram_with_ollama.get('used')} MiB, Free={vram_with_ollama.get('free')} MiB")
        print(f"    Статус Ollama /api/ps: {'В памяти' if ollama_loaded else 'Не обнаружена'}")
        self.assertTrue(ollama_loaded, "Модель qwen3:8b должна быть загружена в память Ollama.")

        # 3. Вызвать ImageAgent
        print("\n[3] Запуск ImageAgent (автоматическая выгрузка Ollama -> ComfyUI)...")
        prompt = "a photorealistic cute red panda astronaut discovering glowing crystal plants on an alien planet, 8k"
        ctx = AgentContext(
            task=prompt,
            metadata={"width": 1024, "height": 1024, "steps": 4}
        )
        agent_result = self.agent.run(ctx)

        # 4. Убедиться, что генерация успешна и Ollama был выгружен
        self.assertTrue(
            agent_result.success,
            f"ImageAgent завершился с ошибкой: {agent_result.error}"
        )

        vram_prep = agent_result.data.get("vram_prepare", {})
        ollama_unload_info = vram_prep.get("ollama_unload", {})
        self.assertTrue(
            ollama_unload_info.get("success"),
            f"Выгрузка Ollama завершилась с ошибкой: {ollama_unload_info}"
        )
        vram_after_unload = vram_prep.get("gpu_after_unload", {})
        print(f"\n[4] Метрики VRAM после выгрузки Ollama перед запуском ComfyUI:")
        print(f"    Used: {vram_after_unload.get('used')} MiB, Free: {vram_after_unload.get('free')} MiB")
        print(f"    Unload info: {ollama_unload_info.get('message')}")

        # 5. Проверить результат ComfyUI
        self.assertEqual(len(agent_result.created_files), 1, "ImageAgent должен создать 1 файл изображения.")
        saved_file = Path(agent_result.created_files[0])
        self.assertTrue(saved_file.exists(), f"Файл не найден на диске: {saved_file}")
        file_size = saved_file.stat().st_size
        print(f"\n[5] Сгенерированное изображение сохранено:")
        print(f"    Путь: {saved_file}")
        print(f"    Размер: {file_size} байт ({round(file_size / (1024*1024), 2)} MB)")
        print(f"    Время генерации: {agent_result.data.get('generation_time_sec')} сек")

        # 6. Проверить PNG (сигнатура и 1024x1024 без Pillow)
        with open(saved_file, "rb") as f:
            png_header = f.read(24)
        self.assertTrue(png_header.startswith(b"\x89PNG\r\n\x1a\n"), "Файл не является валидным PNG.")
        width, height = struct.unpack(">II", png_header[16:24])
        self.assertEqual((width, height), (1024, 1024), f"Разрешение не соответствует 1024x1024: {width}x{height}")
        print(f"\n[6] Валидация PNG заголовка успешна: {width}x{height} px")

        # 7. Проверить VRAM после /free
        vram_restore = agent_result.data.get("vram_restore", {})
        self.assertTrue(
            vram_restore.get("success"),
            f"ComfyUI /free вернул ошибку: {vram_restore.get('error')}"
        )
        vram_after_free = self.vram_mgr.get_gpu_stats()
        print(f"\n[7] VRAM после ComfyUI /free:")
        print(f"    Used: {vram_after_free.get('used')} MiB, Free: {vram_after_free.get('free')} MiB")

        # 8. Выполнить простой запрос через существующий OllamaClient
        print("\n[8] Повторный запрос к OllamaClient (проверка штатной перезагрузки)...")
        chat_res2 = self.ollama.send_chat([{"role": "user", "content": "Скажи одно слово: Работает!"}])

        # 9. Убедиться, что Ollama снова загрузился и ответил
        ollama_answer = chat_res2.get("content", "").strip()
        print(f"    Ответ Ollama после генерации: '{ollama_answer}'")
        self.assertTrue(len(ollama_answer) > 0, "Ollama не вернула ответ после повторного вызова.")

        vram_reloaded = self.vram_mgr.get_gpu_stats()
        ollama_reloaded = self.vram_mgr.is_model_loaded("qwen3:8b")
        print(f"\n[9] Финальная VRAM (Ollama перезагружена в память):")
        print(f"    Used: {vram_reloaded.get('used')} MiB, Free: {vram_reloaded.get('free')} MiB")
        print(f"    Статус Ollama /api/ps: {'В памяти' if ollama_reloaded else 'Не обнаружена'}")
        self.assertTrue(ollama_reloaded, "Модель qwen3:8b должна снова находиться в памяти Ollama.")

        print("\n>>> ИНТЕГРАЦИОННЫЙ ТЕСТ VRAM MANAGER V1 УСПЕШНО ПРОЙДЕН! <<<")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    unittest.main()
