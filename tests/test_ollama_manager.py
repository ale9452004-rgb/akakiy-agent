"""
Тесты жизненного цикла локальной среды Ollama (OllamaManager).

Покрывают 8 обязательных сценариев:
1. Ollama уже запущен (started_by_akakiy == False, Popen не вызывается).
2. Ollama запущен Акакием (started_by_akakiy == True, процесс отслеживается).
3. Ошибка запуска (FileNotFoundError при отсутствии ollama в PATH).
4. Превышение таймаута ожидания готовности API.
5. cleanup() НЕ завершает чужой процесс (started_by_akakiy == False).
6. cleanup() завершает только собственный процесс (started_by_akakiy == True).
7. Отсутствие модели qwen3:8b корректно выявляется и возвращает инструкцию.
8. Ошибки внутри cleanup() не приводят к падению приложения.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from infrastructure.ollama_manager import (
    OllamaManager,
    get_ollama_manager,
    DEFAULT_OLLAMA_URL,
    DEFAULT_MODEL,
)


class TestOllamaManager(unittest.TestCase):
    """Набор тестов для OllamaManager."""

    def setUp(self):
        self.mgr = OllamaManager(
            base_url="http://localhost:11434",
            model_name="qwen3:8b",
            timeout=1.0,
            check_interval=0.05,
        )

    # =========================================================================
    # Сценарий 1: Ollama уже запущен
    # =========================================================================
    @patch("infrastructure.ollama_manager.requests.get")
    @patch("infrastructure.ollama_manager.subprocess.Popen")
    def test_scenario_1_already_running(self, mock_popen, mock_get):
        """Если Ollama уже запущен — используем его, started_by_akakiy = False."""
        # Мокируем ответ /api/tags: 200 OK со списком моделей, включающим qwen3:8b
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "qwen3:8b:latest"}]
        }
        mock_get.return_value = mock_response

        success, message = self.mgr.start_or_connect()

        self.assertTrue(success)
        self.assertFalse(self.mgr.started_by_akakiy)
        self.assertIsNone(self.mgr.process)
        mock_popen.assert_not_called()
        self.assertIn("уже запущенному Ollama", message)

    # =========================================================================
    # Сценарий 2: Ollama запущен Акакием
    # =========================================================================
    @patch("infrastructure.ollama_manager.requests.get")
    @patch("infrastructure.ollama_manager.subprocess.Popen")
    def test_scenario_2_started_by_akakiy(self, mock_popen, mock_get):
        """Если Ollama не запущен — поднимаем процесс и отслеживаем владение."""
        # 1-й вызов: сервер недоступен (ConnectionError)
        # 2-й и 3-й вызовы: сервер поднялся и возвращает модель
        fail_response = MagicMock()
        fail_response.status_code = 500

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "models": [{"name": "qwen3:8b"}]
        }

        mock_get.side_effect = [
            Exception("Connection refused"),  # первый is_running()
            ok_response,                      # polling is_running()
            ok_response,                      # check_model_available()
            ok_response,
        ]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        success, message = self.mgr.start_or_connect()

        self.assertTrue(success)
        self.assertTrue(self.mgr.started_by_akakiy)
        self.assertIs(self.mgr.process, mock_proc)
        mock_popen.assert_called_once()
        self.assertIn("успешно запущен Акакием", message)

    # =========================================================================
    # Сценарий 3: Ошибка запуска (FileNotFoundError)
    # =========================================================================
    @patch("infrastructure.ollama_manager.requests.get")
    @patch("infrastructure.ollama_manager.subprocess.Popen")
    def test_scenario_3_failed_to_launch_file_not_found(self, mock_popen, mock_get):
        """Если ollama отсутствует в системе — возвращается понятная ошибка без падения."""
        mock_get.side_effect = Exception("Connection refused")
        mock_popen.side_effect = FileNotFoundError("Executable not found")

        success, message = self.mgr.start_or_connect()

        self.assertFalse(success)
        self.assertFalse(self.mgr.started_by_akakiy)
        self.assertIsNone(self.mgr.process)
        self.assertIn("не найден", message)

    # =========================================================================
    # Сценарий 4: Превышение таймаута ожидания API
    # =========================================================================
    @patch("infrastructure.ollama_manager.requests.get")
    @patch("infrastructure.ollama_manager.subprocess.Popen")
    def test_scenario_4_api_timeout_exceeded(self, mock_popen, mock_get):
        """Если сервер запущен, но API не отвечает в течение таймаута — очистка и возврат ошибки."""
        mock_get.side_effect = Exception("Connection refused")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        # Таймаут делаем минимальным для быстрого теста
        self.mgr.timeout = 0.08
        self.mgr.check_interval = 0.02

        success, message = self.mgr.start_or_connect()

        self.assertFalse(success)
        self.assertIn("Превышено время ожидания", message)
        # Проверяем, что процесс был завершён через cleanup()
        mock_proc.terminate.assert_called_once()
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Сценарий 5: cleanup() НЕ завершает чужой процесс
    # =========================================================================
    def test_scenario_5_cleanup_does_not_terminate_foreign_ollama(self):
        """cleanup() ничего не делает, если started_by_akakiy == False."""
        self.mgr.started_by_akakiy = False
        mock_proc = MagicMock()
        self.mgr.process = mock_proc

        self.mgr.cleanup()

        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()
        # Внешний процесс не тронут

    # =========================================================================
    # Сценарий 6: cleanup() завершает только собственный процесс
    # =========================================================================
    def test_scenario_6_cleanup_terminates_own_process(self):
        """cleanup() завершает процесс, если started_by_akakiy == True."""
        self.mgr.started_by_akakiy = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.mgr.process = mock_proc

        self.mgr.cleanup()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=3.0)
        self.assertIsNone(self.mgr.process)
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Сценарий 7: Отсутствие целевой модели qwen3:8b
    # =========================================================================
    @patch("infrastructure.ollama_manager.requests.get")
    def test_scenario_7_missing_model_detected(self, mock_get):
        """Отсутствие целевой модели возвращает чёткую инструкцию пользователю."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3:8b"}, {"name": "mistral:7b"}]
        }
        mock_get.return_value = mock_response

        # 1. Прямая проверка модели
        available, msg = self.mgr.check_model_available("qwen3:8b")
        self.assertFalse(available)
        self.assertIn("qwen3:8b", msg)
        self.assertIn("ollama run qwen3:8b", msg)

        # 2. Предикат
        self.assertFalse(self.mgr.is_model_available("qwen3:8b"))

        # 3. При вызове start_or_connect(require_model=True)
        success, connect_msg = self.mgr.start_or_connect(require_model=True)
        self.assertFalse(success)
        self.assertIn("qwen3:8b", connect_msg)

    # =========================================================================
    # Сценарий 8: Ошибки внутри cleanup() не роняют приложение
    # =========================================================================
    def test_scenario_8_cleanup_errors_do_not_crash(self):
        """Ошибки или исключения в процессе завершения безопасно перехватываются."""
        self.mgr.started_by_akakiy = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate.side_effect = PermissionError("Access denied")
        self.mgr.process = mock_proc

        # Не должно выбрасывать исключений
        try:
            self.mgr.cleanup()
        except Exception as e:
            self.fail(f"cleanup() выбросил исключение: {e}")

        self.assertIsNone(self.mgr.process)
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Дополнительные проверки и краевые случаи
    # =========================================================================
    def test_cleanup_hanging_process_calls_kill(self):
        """Если процесс завис при terminate(), вызывается kill()."""
        self.mgr.started_by_akakiy = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="ollama", timeout=3.0)
        self.mgr.process = mock_proc

        self.mgr.cleanup()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        self.assertIsNone(self.mgr.process)

    def test_repeated_cleanup_is_safe_and_idempotent(self):
        """Повторный вызов cleanup() безопасен и не вызывает повторную остановку процесса."""
        self.mgr.started_by_akakiy = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.mgr.process = mock_proc

        # Первый вызов cleanup()
        self.mgr.cleanup()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(self.mgr.process)
        self.assertFalse(self.mgr.started_by_akakiy)

        # Второй вызов cleanup() - не должен ничего делать или вызывать terminate повторно
        self.mgr.cleanup()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(self.mgr.process)
        self.assertFalse(self.mgr.started_by_akakiy)

        # Третий вызов cleanup()
        self.mgr.cleanup()
        mock_proc.terminate.assert_called_once()

    def test_matches_model_variants(self):
        """Проверка сопоставления различных форматов тегов моделей."""
        self.assertTrue(OllamaManager._matches_model("qwen3:8b", "qwen3:8b"))
        self.assertTrue(OllamaManager._matches_model("qwen3:8b:latest", "qwen3:8b"))
        self.assertTrue(OllamaManager._matches_model("library/qwen3:8b", "qwen3:8b"))
        self.assertFalse(OllamaManager._matches_model("llama3:8b", "qwen3:8b"))

    @patch("infrastructure.ollama_manager.requests.get")
    @patch("infrastructure.ollama_manager.subprocess.Popen")
    def test_process_dies_prematurely(self, mock_popen, mock_get):
        """Если запущенный процесс упал до готовности API — возвращается код ошибки."""
        mock_get.side_effect = Exception("Connection refused")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        self.mgr.timeout = 0.5
        self.mgr.check_interval = 0.02

        success, message = self.mgr.start_or_connect()
        self.assertFalse(success)
        self.assertIn("завершился с кодом 1", message)

    def test_singleton_get_ollama_manager(self):
        """Синглтон get_ollama_manager возвращает стабильный экземпляр."""
        inst1 = get_ollama_manager()
        inst2 = get_ollama_manager()
        self.assertIs(inst1, inst2)

    def test_gui_window_close_calls_ollama_cleanup(self):
        """Проверка, что закрытие GUI вызывает cleanup() у переданного ollama_mgr."""
        import tkinter as tk
        from gui import AkakiyGUI
        root = tk.Tk()
        root.withdraw()
        mock_ollama_mgr = MagicMock()

        try:
            with patch("gui.VoiceService"), \
                 patch("gui.GlobalHotKeyManager"):
                app = AkakiyGUI(root, ollama_mgr=mock_ollama_mgr)
                app._on_window_close()
            mock_ollama_mgr.cleanup.assert_called_once()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_gui_destroy_calls_ollama_cleanup(self):
        """Проверка, что app.destroy() вызывает cleanup() у переданного ollama_mgr."""
        import tkinter as tk
        from gui import AkakiyGUI
        root = tk.Tk()
        root.withdraw()
        mock_ollama_mgr = MagicMock()

        try:
            with patch("gui.VoiceService"), \
                 patch("gui.GlobalHotKeyManager"):
                app = AkakiyGUI(root, ollama_mgr=mock_ollama_mgr)
                app.destroy()
            mock_ollama_mgr.cleanup.assert_called_once()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    @patch("main.Agent")
    @patch("main.get_ollama_manager")
    def test_cli_lifecycle_starts_and_cleans_up(self, mock_get_mgr, mock_agent):
        """Проверка, что запуск CLI в main.py вызывает start_or_connect и cleanup."""
        import sys
        import main as main_module

        mock_mgr = MagicMock()
        mock_mgr.start_or_connect.return_value = (True, "OK")
        mock_get_mgr.return_value = mock_mgr

        with patch.object(sys, "argv", ["main.py"]), \
             patch("builtins.input", side_effect=["выход"]), \
             patch("builtins.print"):
            main_module.main()

        mock_mgr.start_or_connect.assert_called_once()
        mock_mgr.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
