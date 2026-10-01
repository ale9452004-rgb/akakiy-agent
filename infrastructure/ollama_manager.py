"""
Менеджер жизненного цикла локальной LLM-среды Ollama для Акакия.

Обеспечивает:
1. Проверку доступности локального сервера Ollama API (http://localhost:11434).
2. Автоматический запуск процесса 'ollama serve' в фоновом режиме, если сервер не активен.
3. Проверку наличия целевой модели (по умолчанию 'qwen3:8b') без автоскачивания.
4. Отслеживание владельца процесса (started_by_akakiy).
5. Корректное завершение только собственного процесса при выходе из приложения.
"""

import atexit
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TIMEOUT = 15.0
DEFAULT_CHECK_INTERVAL = 0.4


class OllamaManager:
    """
    Управляет запуском, проверкой готовности и корректной остановкой процесса Ollama.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model_name: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        executable: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.check_interval = check_interval
        self.executable = executable

        self.started_by_akakiy: bool = False
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()

    def is_running(self) -> bool:
        """
        Проверяет, отвечает ли Ollama API по HTTP.
        Возвращает True, если сервер возвращает HTTP 200, иначе False.
        """
        url = f"{self.base_url}/api/tags"
        try:
            response = requests.get(url, timeout=1.5)
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _matches_model(name: str, target: str) -> bool:
        """
        Сравнивает имя модели из Ollama API с целевой моделью с учётом тегов и библиотек.
        """
        name_clean = name.strip().lower()
        target_clean = target.strip().lower()

        if name_clean == target_clean:
            return True
        if name_clean == f"{target_clean}:latest":
            return True
        if target_clean == f"{name_clean}:latest":
            return True

        if "/" in name_clean:
            sub_name = name_clean.split("/")[-1]
            if sub_name == target_clean or sub_name == f"{target_clean}:latest":
                return True

        return False

    def check_model_available(self, model: Optional[str] = None) -> Tuple[bool, str]:
        """
        Проверяет наличие модели в локальном хранилище Ollama (/api/tags).
        Не скачивает модель автоматически; при отсутствии возвращает чёткую инструкцию.
        """
        target = (model or self.model_name).strip()
        if not self.is_running():
            return False, f"Сервер Ollama недоступен по адресу {self.base_url}."

        url = f"{self.base_url}/api/tags"
        try:
            response = requests.get(url, timeout=2.5)
            if response.status_code != 200:
                return False, f"Ollama API вернул статус {response.status_code} при запросе списка моделей."

            data = response.json()
            models = data.get("models", [])
            for m in models:
                m_name = m.get("name", "")
                if self._matches_model(m_name, target):
                    return True, f"Модель '{target}' доступна в Ollama."

            return (
                False,
                f"Модель '{target}' не найдена в Ollama. Запустите: ollama run {target}",
            )
        except Exception as e:
            return False, f"Ошибка при проверке модели в Ollama: {e}"

    def is_model_available(self, model: Optional[str] = None) -> bool:
        """
        Упрощённый предикат проверки доступности модели.
        """
        available, _ = self.check_model_available(model)
        return available

    def _resolve_executable(self) -> str:
        """
        Определяет путь к исполняемому файлу ollama.
        """
        if self.executable:
            return self.executable

        found = shutil.which("ollama")
        if found:
            return found

        if sys.platform == "win32":
            candidate = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
            if candidate.is_file():
                return str(candidate)

        return "ollama"

    def start_or_connect(self, require_model: bool = True) -> Tuple[bool, str]:
        """
        Основной метод инициализации окружения LLM:
        1. Если Ollama уже запущен — использует его (started_by_akakiy = False).
        2. Если не запущен — запускает 'ollama serve' (started_by_akakiy = True)
           и ожидает готовности API в течение self.timeout.
        3. Проверяет наличие целевой модели (self.model_name).
        """
        with self._lock:
            # 1. Проверяем, запущен ли уже Ollama
            if self.is_running():
                self.started_by_akakiy = False
                self.process = None
                model_ok, model_msg = self.check_model_available()
                if not model_ok and require_model:
                    return (
                        False,
                        f"Подключено к уже запущенному Ollama, но {model_msg}",
                    )
                return True, f"Подключено к уже запущенному Ollama. {model_msg}"

            # 2. Не запущен — запускаем свой процесс
            exe = self._resolve_executable()
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            try:
                self.process = subprocess.Popen(
                    [exe, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                self.started_by_akakiy = True
            except FileNotFoundError:
                self.started_by_akakiy = False
                self.process = None
                return (
                    False,
                    "Исполняемый файл Ollama не найден. Убедитесь, что Ollama установлен и добавлен в PATH.",
                )
            except Exception as e:
                self.started_by_akakiy = False
                self.process = None
                return False, f"Не удалось запустить процесс Ollama: {e}"

            # 3. Ожидание готовности API
            start_time = time.time()
            connected = False
            while time.time() - start_time < self.timeout:
                if self.process and self.process.poll() is not None:
                    code = self.process.returncode
                    self.cleanup()
                    return (
                        False,
                        f"Процесс Ollama завершился с кодом {code} до инициализации API.",
                    )

                if self.is_running():
                    connected = True
                    break

                time.sleep(self.check_interval)

            if not connected:
                self.cleanup()
                return (
                    False,
                    f"Превышено время ожидания ({self.timeout}с) запуска Ollama API.",
                )

            # 4. Проверка модели
            model_ok, model_msg = self.check_model_available()
            if not model_ok and require_model:
                return (
                    False,
                    f"Ollama успешно запущен Акакием, но {model_msg}",
                )

            return True, f"Ollama успешно запущен Акакием. {model_msg}"

    def ensure_running(self, require_model: bool = True) -> Tuple[bool, str]:
        """
        Синоним start_or_connect для удобства вызывающего кода.
        """
        return self.start_or_connect(require_model=require_model)

    def cleanup(self) -> None:
        """
        Останавливает процесс Ollama, ТОЛЬКО если он был запущен текущим экземпляром Акакия.
        Если Ollama был запущен пользователем/системой до Акакия — не трогает его.
        Ни при каких обстоятельствах не выбрасывает исключений наружу.
        """
        try:
            with self._lock:
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
                    logger.warning(f"Ошибка при завершении процесса Ollama: {e}")
                finally:
                    self.process = None
                    self.started_by_akakiy = False
        except Exception as e:
            logger.warning(f"Непредвиденное исключение в OllamaManager.cleanup: {e}")


# Глобальный синглтон
_instance: Optional[OllamaManager] = None
_instance_lock = threading.Lock()


def get_ollama_manager(
    base_url: str = DEFAULT_OLLAMA_URL,
    model_name: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    executable: Optional[str] = None,
) -> OllamaManager:
    """
    Возвращает синглтон-экземпляр OllamaManager.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = OllamaManager(
                    base_url=base_url,
                    model_name=model_name,
                    timeout=timeout,
                    executable=executable,
                )
    return _instance


def _atexit_cleanup():
    global _instance
    if _instance is not None:
        _instance.cleanup()


atexit.register(_atexit_cleanup)
