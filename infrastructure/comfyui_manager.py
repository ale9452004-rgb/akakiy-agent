"""
Менеджер жизненного цикла локального ComfyUI Worker для Акакия.

Обеспечивает:
1. Автоматический запуск изолированного процесса ComfyUI с параметрами --listen 127.0.0.1 --port 8188.
2. Проверку доступности и валидности ComfyUI API (http://127.0.0.1:8188/system_stats).
3. Подключение к уже запущенному экземпляру ComfyUI без повторного старта.
4. Отслеживание владельца процесса (started_by_akakiy).
5. Корректное завершение только собственного процесса при выходе из приложения.
6. Неблокирующий асинхронный запуск (start_async) для GUI Tkinter.
7. Предотвращение гонок при ранних запросах на генерацию (is_starting / wait_until_ready).
8. Защиту от посторонних процессов на порту 8188 без попыток их принудительного завершения.
"""

import atexit
import logging
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Tuple

import requests

from config import PROJECT_PATH

logger = logging.getLogger(__name__)

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
DEFAULT_TIMEOUT = 30.0
DEFAULT_CHECK_INTERVAL = 0.5


class ComfyUIManager:
    """
    Управляет запуском, проверкой готовности и безопасной остановкой процесса ComfyUI Worker.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_COMFYUI_URL,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        python_executable: Optional[Path] = None,
        main_script: Optional[Path] = None,
        working_dir: Optional[Path] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.check_interval = check_interval

        self._custom_python_executable = python_executable
        self._custom_main_script = main_script
        self._custom_working_dir = working_dir

        self.started_by_akakiy: bool = False
        self.process: Optional[subprocess.Popen] = None
        self._starting: bool = False
        self._ready_event = threading.Event()
        self._lock = threading.RLock()
        self._last_status: Tuple[bool, str] = (False, "ComfyUI Worker не инициализирован.")

    def _resolve_python_executable(self) -> Path:
        """Определяет абсолютный путь к python.exe внутри workers/comfyui/.venv."""
        if self._custom_python_executable:
            return Path(self._custom_python_executable).resolve()

        if sys.platform == "win32":
            candidate = PROJECT_PATH / "workers" / "comfyui" / ".venv" / "Scripts" / "python.exe"
        else:
            candidate = PROJECT_PATH / "workers" / "comfyui" / ".venv" / "bin" / "python"

        return candidate.resolve()

    def _resolve_main_script(self) -> Path:
        """Определяет абсолютный путь к workers/comfyui/main.py."""
        if self._custom_main_script:
            return Path(self._custom_main_script).resolve()
        return (PROJECT_PATH / "workers" / "comfyui" / "main.py").resolve()

    def _resolve_working_dir(self) -> Path:
        """Определяет абсолютный путь к рабочей директории workers/comfyui."""
        if self._custom_working_dir:
            return Path(self._custom_working_dir).resolve()
        return (PROJECT_PATH / "workers" / "comfyui").resolve()

    def is_port_in_use(self) -> bool:
        """Проверяет, открыт ли сокет на целевом хосте и порту."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.6)
                return s.connect_ex((self.host, self.port)) == 0
        except Exception:
            return False

    def is_running(self) -> bool:
        """
        Проверяет, отвечает ли ComfyUI API по HTTP и возвращает ли корректные system_stats.
        Возвращает True, только если сервер возвращает HTTP 200 с валидным JSON ComfyUI.
        """
        url = f"{self.base_url}/system_stats"
        try:
            response = requests.get(url, timeout=1.5)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and ("system" in data or "devices" in data):
                    return True
            return False
        except Exception:
            return False

    def is_starting(self) -> bool:
        """Возвращает True, если ComfyUI сейчас находится в процессе запуска."""
        with self._lock:
            return self._starting

    def is_ready(self) -> bool:
        """Возвращает True, если ComfyUI активен и готов принимать запросы."""
        return self.is_running()

    @property
    def last_status(self) -> Tuple[bool, str]:
        """Возвращает последний зафиксированный статус запуска (success, message)."""
        with self._lock:
            return self._last_status

    def wait_until_ready(self, timeout: float = 15.0) -> bool:
        """
        Ожидает готовности worker в течение timeout секунд.
        Полезно для предотвращения гонок при ранних запросах генерации.
        """
        if self.is_running():
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ready_event.wait(timeout=min(0.5, max(0.05, deadline - time.time()))):
                if self.is_running():
                    return True
            if self.is_running():
                return True
            with self._lock:
                if not self._starting:
                    # Процесс завершился ошибкой или не запускается
                    break
            time.sleep(0.2)

        return self.is_running()

    def start_or_connect(self) -> Tuple[bool, str]:
        """
        Основной метод запуска и подключения к ComfyUI Worker:
        1. Если ComfyUI уже запущен и API отвечает — использует его (started_by_akakiy = False).
        2. Если порт занят посторонним процессом (API не ComfyUI) — сообщает об ошибке без его завершения.
        3. Если не запущен — проверяет наличие python.exe и main.py.
        4. Запускает изолированный процесс 'python.exe main.py --listen host --port port'.
        5. Ожидает готовности API (/system_stats) в пределах timeout.
        6. Возвращает (success, status_message).
        """
        with self._lock:
            # 1. Проверяем, запущен ли уже полноценный ComfyUI
            if self.is_running():
                self.started_by_akakiy = False
                self.process = None
                self._starting = False
                self._ready_event.set()
                msg = f"Подключено к уже работающему ComfyUI Worker ({self.base_url})."
                self._last_status = (True, msg)
                return True, msg

            # 2. Проверяем, не занят ли порт посторонним приложением
            if self.is_port_in_use():
                msg = (
                    f"Порт {self.port} уже занят сторонним процессом, не являющимся активным ComfyUI API. "
                    "ComfyUI Worker не может быть запущен на этом порту."
                )
                logger.warning(msg)
                self._starting = False
                self._last_status = (False, msg)
                return False, msg

            # 3. Разрешаем пути
            python_exe = self._resolve_python_executable()
            if not python_exe.is_file():
                msg = (
                    f"Изолированное окружение Python для ComfyUI не найдено по пути: {python_exe}. "
                    "Убедитесь, что workers/comfyui/.venv настроен корректно."
                )
                logger.error(msg)
                self._starting = False
                self._last_status = (False, msg)
                return False, msg

            main_script = self._resolve_main_script()
            if not main_script.is_file():
                msg = (
                    f"Точка входа ComfyUI main.py не найдена по пути: {main_script}. "
                    "Убедитесь, что репозиторий ComfyUI распакован в workers/comfyui/."
                )
                logger.error(msg)
                self._starting = False
                self._last_status = (False, msg)
                return False, msg

            working_dir = self._resolve_working_dir()
            if not working_dir.is_dir():
                msg = f"Рабочий каталог ComfyUI не найден: {working_dir}."
                logger.error(msg)
                self._starting = False
                self._last_status = (False, msg)
                return False, msg

            # 4. Запускаем дочерний процесс
            self._starting = True
            self._ready_event.clear()

            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            cmd = [
                str(python_exe),
                str(main_script),
                "--listen",
                self.host,
                "--port",
                str(self.port),
            ]

            try:
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(working_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                self.started_by_akakiy = True
            except Exception as e:
                self.started_by_akakiy = False
                self.process = None
                self._starting = False
                msg = f"Не удалось запустить процесс ComfyUI Worker: {e}"
                logger.exception(msg)
                self._last_status = (False, msg)
                return False, msg

        # 5. Ожидание готовности API (вне lock для возможности параллельных проверок)
        start_time = time.time()
        connected = False

        while time.time() - start_time < self.timeout:
            with self._lock:
                proc = self.process
                if proc is not None and proc.poll() is not None:
                    code = proc.returncode
                    self.cleanup()
                    msg = f"Процесс ComfyUI Worker аварийно завершился с кодом {code} до готовности API."
                    logger.error(msg)
                    self._last_status = (False, msg)
                    return False, msg

            if self.is_running():
                connected = True
                break

            time.sleep(self.check_interval)

        with self._lock:
            self._starting = False
            if not connected:
                self.cleanup()
                msg = f"Превышено время ожидания ({self.timeout}с) запуска ComfyUI API по адресу {self.base_url}."
                logger.error(msg)
                self._last_status = (False, msg)
                return False, msg

            self._ready_event.set()
            msg = f"ComfyUI Worker успешно запущен Акакием на {self.base_url}."
            logger.info(msg)
            self._last_status = (True, msg)
            return True, msg

    def ensure_running(self) -> Tuple[bool, str]:
        """Синоним start_or_connect для единообразия с OllamaManager."""
        return self.start_or_connect()

    def start_async(
        self,
        callback: Optional[Callable[[bool, str], None]] = None
    ) -> threading.Thread:
        """
        Запускает ComfyUI Worker в фоновом потоке, не блокируя UI Tkinter.
        По завершении инициализации вызывает callback(success, message), если передан.
        """
        def _target():
            success, msg = self.start_or_connect()
            if callback:
                try:
                    callback(success, msg)
                except Exception as e:
                    logger.warning(f"Ошибка в callback после старта ComfyUI: {e}")

        thread = threading.Thread(target=_target, name="ComfyUI-Startup-Thread", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        """Синоним cleanup для удобства."""
        self.cleanup()

    def cleanup(self) -> None:
        """
        Безопасно останавливает ComfyUI Worker, ТОЛЬКО если он был запущен текущим экземпляром Акакия.
        Если ComfyUI был запущен пользователем/системой отдельно — не трогает его.
        Ни при каких обстоятельствах не выбрасывает исключений наружу.
        """
        try:
            with self._lock:
                self._starting = False
                self._ready_event.clear()

                if not self.started_by_akakiy:
                    return

                proc = self.process
                if proc is None:
                    self.started_by_akakiy = False
                    return

                try:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3.0)
                        except (subprocess.TimeoutExpired, Exception):
                            try:
                                proc.kill()
                                proc.wait(timeout=1.0)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"Ошибка при завершении процесса ComfyUI Worker: {e}")
                finally:
                    self.process = None
                    self.started_by_akakiy = False
        except Exception as e:
            logger.warning(f"Непредвиденное исключение в ComfyUIManager.cleanup: {e}")


# Глобальный синглтон
_instance: Optional[ComfyUIManager] = None
_instance_lock = threading.Lock()


def get_comfyui_manager(
    base_url: str = DEFAULT_COMFYUI_URL,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    python_executable: Optional[Path] = None,
    main_script: Optional[Path] = None,
    working_dir: Optional[Path] = None,
) -> ComfyUIManager:
    """
    Возвращает синглтон-экземпляр ComfyUIManager.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ComfyUIManager(
                    base_url=base_url,
                    host=host,
                    port=port,
                    timeout=timeout,
                    python_executable=python_executable,
                    main_script=main_script,
                    working_dir=working_dir,
                )
    return _instance


def _atexit_cleanup():
    global _instance
    if _instance is not None:
        _instance.cleanup()


atexit.register(_atexit_cleanup)
