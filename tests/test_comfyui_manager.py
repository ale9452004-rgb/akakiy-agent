"""
Тесты жизненного цикла локальной среды ComfyUI Worker (ComfyUIManager).

Покрывают 12 обязательных сценариев:
1. Запуск worker, когда он не запущен.
2. Подключение к уже работающему ComfyUI без создания второго процесса.
3. Повторный start() без создания второго процесса.
4. Ожидание готовности API.
5. Тайм-аут и неуспешный запуск.
6. Отсутствие исполняемого файла или main.py.
7. Занятый порт и недоступный API (чужой процесс не завершается).
8. Остановка собственного процесса.
9. Сохранение чужого процесса при stop()/cleanup().
10. Повторный stop()/cleanup() без ошибки.
11. Неблокирующий запуск из GUI (start_async с callback).
12. Корректная обработка запроса генерации во время запуска worker (гонка / wait_until_ready).
"""

from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from infrastructure.comfyui_manager import (
    ComfyUIManager,
    get_comfyui_manager,
    DEFAULT_COMFYUI_URL,
    DEFAULT_PORT,
)
from tools.agents.context import AgentContext
from tools.agents.image import ImageAgent


class TestComfyUIManager(unittest.TestCase):
    """Набор модульных тестов для ComfyUIManager."""

    def setUp(self):
        # Используем тестовый порт и короткие таймауты для быстрой и изолированной работы
        self.test_dir = Path("workers/comfyui").resolve()
        self.mgr = ComfyUIManager(
            base_url="http://127.0.0.1:9188",
            host="127.0.0.1",
            port=9188,
            timeout=0.1,
            check_interval=0.02,
            python_executable=self.test_dir / ".venv" / "Scripts" / "python.exe",
            main_script=self.test_dir / "main.py",
            working_dir=self.test_dir,
        )

    # =========================================================================
    # Сценарий 1: Запуск worker, когда он не запущен
    # =========================================================================
    @patch.object(ComfyUIManager, "_resolve_working_dir")
    @patch.object(ComfyUIManager, "_resolve_main_script")
    @patch.object(ComfyUIManager, "_resolve_python_executable")
    @patch.object(ComfyUIManager, "is_port_in_use", return_value=False)
    @patch.object(ComfyUIManager, "is_running")
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_1_start_when_not_running(
        self, mock_popen, mock_is_running, mock_port, mock_py, mock_main, mock_dir
    ):
        """Если ComfyUI не запущен — поднимаем процесс, started_by_akakiy = True."""
        mock_py.return_value = MagicMock(is_file=lambda: True)
        mock_main.return_value = MagicMock(is_file=lambda: True)
        mock_dir.return_value = MagicMock(is_dir=lambda: True)

        # 1-й вызов: сервер ещё не запущен, 2-й: сервер запустился
        mock_is_running.side_effect = [False, True]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        success, msg = self.mgr.start_or_connect()

        self.assertTrue(success)
        self.assertTrue(self.mgr.started_by_akakiy)
        self.assertIs(self.mgr.process, mock_proc)
        mock_popen.assert_called_once()
        self.assertIn("успешно запущен Акакием", msg)

    # =========================================================================
    # Сценарий 2: Подключение к уже работающему ComfyUI
    # =========================================================================
    @patch.object(ComfyUIManager, "is_running", return_value=True)
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_2_connect_to_already_running(self, mock_popen, mock_is_running):
        """Если ComfyUI уже запущен — подключаемся без создания процесса, started_by_akakiy = False."""
        success, msg = self.mgr.start_or_connect()

        self.assertTrue(success)
        self.assertFalse(self.mgr.started_by_akakiy)
        self.assertIsNone(self.mgr.process)
        mock_popen.assert_not_called()
        self.assertIn("уже работающему ComfyUI", msg)

    # =========================================================================
    # Сценарий 3: Повторный start() без создания второго процесса
    # =========================================================================
    @patch.object(ComfyUIManager, "is_running", return_value=True)
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_3_idempotent_start(self, mock_popen, mock_is_running):
        """Повторный запуск при уже активном воркере не создаёт второй процесс."""
        success1, msg1 = self.mgr.start_or_connect()
        success2, msg2 = self.mgr.start_or_connect()

        self.assertTrue(success1)
        self.assertTrue(success2)
        mock_popen.assert_not_called()
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Сценарий 4: Ожидание готовности API
    # =========================================================================
    @patch.object(ComfyUIManager, "_resolve_working_dir")
    @patch.object(ComfyUIManager, "_resolve_main_script")
    @patch.object(ComfyUIManager, "_resolve_python_executable")
    @patch.object(ComfyUIManager, "is_port_in_use", return_value=False)
    @patch.object(ComfyUIManager, "is_running")
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_4_wait_for_api_readiness(
        self, mock_popen, mock_is_running, mock_port, mock_py, mock_main, mock_dir
    ):
        """Менеджер циклично опрашивает API до получения готовности."""
        mock_py.return_value = MagicMock(is_file=lambda: True)
        mock_main.return_value = MagicMock(is_file=lambda: True)
        mock_dir.return_value = MagicMock(is_dir=lambda: True)

        # Несколько ответов False во время инициализации, затем True
        mock_is_running.side_effect = [False, False, False, True, True, True]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        self.mgr.timeout = 1.0
        self.mgr.check_interval = 0.02
        success, msg = self.mgr.start_or_connect()

        self.assertTrue(success)
        self.assertTrue(self.mgr.is_ready())
        self.assertIn("успешно запущен Акакием", msg)

    # =========================================================================
    # Сценарий 5: Тайм-аут и неуспешный запуск
    # =========================================================================
    @patch.object(ComfyUIManager, "_resolve_working_dir")
    @patch.object(ComfyUIManager, "_resolve_main_script")
    @patch.object(ComfyUIManager, "_resolve_python_executable")
    @patch.object(ComfyUIManager, "is_port_in_use", return_value=False)
    @patch.object(ComfyUIManager, "is_running", return_value=False)
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_5_timeout_exceeded(
        self, mock_popen, mock_is_running, mock_port, mock_py, mock_main, mock_dir
    ):
        """Если сервер запущен, но API не отвечает в течение таймаута — cleanup() и ошибка."""
        mock_py.return_value = MagicMock(is_file=lambda: True)
        mock_main.return_value = MagicMock(is_file=lambda: True)
        mock_dir.return_value = MagicMock(is_dir=lambda: True)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        self.mgr.timeout = 0.05
        self.mgr.check_interval = 0.01

        success, msg = self.mgr.start_or_connect()

        self.assertFalse(success)
        self.assertIn("Превышено время ожидания", msg)
        mock_proc.terminate.assert_called_once()
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Сценарий 6: Отсутствие исполняемого файла или main.py
    # =========================================================================
    @patch.object(ComfyUIManager, "is_running", return_value=False)
    @patch.object(ComfyUIManager, "is_port_in_use", return_value=False)
    def test_scenario_6_missing_executable_or_script(self, mock_port, mock_running):
        """При отсутствии python.exe или main.py возвращается понятная ошибка без сбоя."""
        # 1. Отсутствует python.exe
        self.mgr._custom_python_executable = Path("non_existent/python.exe")
        success, msg = self.mgr.start_or_connect()
        self.assertFalse(success)
        self.assertIn("окружение Python для ComfyUI не найдено", msg)

        # 2. python.exe есть, но main.py отсутствует
        mock_fake_py = MagicMock()
        mock_fake_py.is_file.return_value = True
        self.mgr._resolve_python_executable = MagicMock(return_value=mock_fake_py)
        self.mgr._custom_main_script = Path("non_existent/main.py")

        success, msg = self.mgr.start_or_connect()
        self.assertFalse(success)
        self.assertIn("main.py не найдена", msg)

    # =========================================================================
    # Сценарий 7: Занятый порт и недоступный API
    # =========================================================================
    @patch.object(ComfyUIManager, "is_running", return_value=False)
    @patch.object(ComfyUIManager, "is_port_in_use", return_value=True)
    @patch("infrastructure.comfyui_manager.subprocess.Popen")
    def test_scenario_7_port_occupied_foreign_service(self, mock_popen, mock_port, mock_running):
        """Если порт открыт, но API не отвечает — это чужой процесс. Не запускать и не убивать его."""
        success, msg = self.mgr.start_or_connect()

        self.assertFalse(success)
        self.assertIn("занят сторонним процессом", msg)
        mock_popen.assert_not_called()
        self.assertFalse(self.mgr.started_by_akakiy)

    # =========================================================================
    # Сценарий 8: Остановка собственного процесса
    # =========================================================================
    def test_scenario_8_stop_own_process(self):
        """Остановка процесса, если started_by_akakiy == True."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        self.mgr.process = mock_proc
        self.mgr.started_by_akakiy = True

        self.mgr.cleanup()

        mock_proc.terminate.assert_called_once()
        self.assertFalse(self.mgr.started_by_akakiy)
        self.assertIsNone(self.mgr.process)

    # =========================================================================
    # Сценарий 9: Сохранение чужого процесса при stop()
    # =========================================================================
    def test_scenario_9_preserve_foreign_process_on_stop(self):
        """cleanup() не трогает чужой процесс (started_by_akakiy == False)."""
        mock_proc = MagicMock()
        self.mgr.process = mock_proc
        self.mgr.started_by_akakiy = False

        self.mgr.cleanup()

        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()

    # =========================================================================
    # Сценарий 10: Повторный stop() без ошибки
    # =========================================================================
    def test_scenario_10_repeated_stop_safe(self):
        """Повторные вызовы cleanup() и stop() идемпотентны и не выбрасывают исключений."""
        self.mgr.started_by_akakiy = False
        self.mgr.process = None

        # Вызываем несколько раз подряд
        self.mgr.cleanup()
        self.mgr.stop()
        self.mgr.cleanup()

        self.assertFalse(self.mgr.started_by_akakiy)
        self.assertIsNone(self.mgr.process)

    # =========================================================================
    # Сценарий 11: Неблокирующий запуск из GUI (start_async)
    # =========================================================================
    @patch.object(ComfyUIManager, "is_running", return_value=True)
    def test_scenario_11_start_async_non_blocking(self, mock_running):
        """start_async выполняется в фоновом потоке и вызывает callback."""
        callback_called = threading.Event()
        callback_args = []

        def cb(success, msg):
            callback_args.append((success, msg))
            callback_called.set()

        thread = self.mgr.start_async(callback=cb)
        self.assertIsInstance(thread, threading.Thread)
        self.assertTrue(thread.is_alive() or callback_called.is_set())

        # Ждём завершения потока
        finished = callback_called.wait(timeout=2.0)
        self.assertTrue(finished, "Callback start_async не был вызван вовремя.")
        self.assertEqual(len(callback_args), 1)
        self.assertTrue(callback_args[0][0])
        self.assertIn("уже работающему ComfyUI", callback_args[0][1])

    # =========================================================================
    # Сценарий 12: Обработка запроса генерации во время запуска (гонка)
    # =========================================================================
    @patch("tools.agents.image.ComfyUIClient.is_available")
    def test_scenario_12_race_condition_wait_until_ready(self, mock_available):
        """Если запрос на генерацию пришёл, когда воркер запускается — агент ждёт готовности."""
        # 1-я проверка: воркер ещё не готов
        # 2-я проверка (после ожидания): воркер стал готов
        mock_available.side_effect = [False, True, True]

        agent = ImageAgent(base_url="http://127.0.0.1:9188")

        with patch("infrastructure.comfyui_manager.get_comfyui_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.is_starting.return_value = True
            mock_mgr.wait_until_ready.return_value = True
            mock_get_mgr.return_value = mock_mgr

            # Мокируем queue_prompt и get_history для быстрого теста валидации гонки
            with patch.object(agent.client, "queue_prompt", return_value={"prompt_id": "p1"}), \
                 patch.object(agent.client, "get_history", return_value={"status": {"completed": True}, "outputs": {"7": {"images": [{"filename": "out.png"}]}}}), \
                 patch.object(agent.client, "view_image", return_value=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x04\x00\x00\x00\x04\x00\x08\x06\x00\x00\x00"), \
                 patch.object(agent.client, "free_memory", return_value=True), \
                 patch.object(agent.vram_manager, "prepare_for_image_generation", return_value={"success": True}):

                res = agent.run(AgentContext(task="кот"))
                self.assertTrue(res.success, f"Ожидался успех после ожидания, получено: {res.error}")
                mock_mgr.wait_until_ready.assert_called_once()
                # Проверяем, что таймаут ожидания берется из менеджера (30с по умолчанию)
                args, kwargs = mock_mgr.wait_until_ready.call_args
                passed_timeout = kwargs.get("timeout") if "timeout" in kwargs else (args[0] if args else None)
                self.assertEqual(passed_timeout, mock_mgr.timeout)

    # =========================================================================
    # Сценарий 13: Таймаут гонки возвращает понятное сообщение
    # =========================================================================
    @patch("tools.agents.image.ComfyUIClient.is_available", return_value=False)
    def test_scenario_13_race_condition_timeout_message(self, mock_available):
        """Если воркер так и не успел запуститься в пределах таймаута — возвращается внятное сообщение."""
        agent = ImageAgent(base_url="http://127.0.0.1:9188")
        with patch("infrastructure.comfyui_manager.get_comfyui_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.is_starting.return_value = True
            mock_mgr.wait_until_ready.return_value = False
            mock_mgr.timeout = 20.0
            mock_get_mgr.return_value = mock_mgr

            res = agent.run(AgentContext(task="кот"))
            self.assertFalse(res.success)
            self.assertIn("ещё запускается", res.error)
            mock_mgr.wait_until_ready.assert_called_once_with(timeout=20.0)

    # =========================================================================
    # Сценарий 14: Callback запуска и обновления статуса потокобезопасен
    # =========================================================================
    def test_scenario_14_gui_callback_thread_safety(self):
        """Callback _on_comfyui_status в AkakiyGUI кладёт событие в queue.Queue без вызова методов Tkinter."""
        import queue
        from gui import AkakiyGUI

        mock_gui = MagicMock(spec=AkakiyGUI)
        mock_gui.queue = queue.Queue()

        # Вызываем реальную функцию привязки
        AkakiyGUI._on_comfyui_status(mock_gui, True, "Готов")

        self.assertFalse(mock_gui.queue.empty())
        item = mock_gui.queue.get_nowait()
        self.assertEqual(item[0], "comfyui_status")
        self.assertEqual(item[1], (True, "Готов"))


if __name__ == "__main__":
    unittest.main()
