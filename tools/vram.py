"""
Модуль управления видеопамятью (VRAM Manager) для Акакия.

Обеспечивает координацию GPU VRAM между Ollama (LLM) и ComfyUI (Image Worker):
- мониторинг потребления VRAM через nvidia-smi;
- выгрузку модели Ollama (qwen3:8b) по запросу через API с keep_alive: 0;
- освобождение памяти ComfyUI Worker через POST /free;
- подготовку VRAM перед генерацией изображений;
- восстановление состояния после генерации без принудительной холостой загрузки Ollama;
- контекстный менеджер image_generation_session.
"""

from contextlib import contextmanager
import subprocess
from typing import Any, Dict, Optional
import requests

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_MODEL = "qwen3:8b"


class VRAMManager:
    """
    Инфраструктурный менеджер управления GPU-памятью.
    """

    def __init__(
        self,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        comfyui_url: str = DEFAULT_COMFYUI_URL,
        default_model: str = DEFAULT_MODEL,
        timeout: int = 10
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.comfyui_url = comfyui_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout

    def get_gpu_stats(self) -> Dict[str, Any]:
        """
        Возвращает текущую статистику VRAM GPU через nvidia-smi (в MiB).
        Ключи: total, used, free, available, used_mib, free_mib, total_mib.
        При ошибке или отсутствии GPU возвращает fallback со значениями 0.
        """
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.free,memory.total",
                    "--format=csv,noheader,nounits"
                ],
                text=True,
                timeout=5
            )
            parts = [int(p.strip()) for p in out.strip().split(",")]
            return {
                "available": True,
                "used": parts[0],
                "free": parts[1],
                "total": parts[2],
                "used_mib": parts[0],
                "free_mib": parts[1],
                "total_mib": parts[2]
            }
        except Exception as e:
            return {
                "available": False,
                "used": 0,
                "free": 0,
                "total": 0,
                "used_mib": 0,
                "free_mib": 0,
                "total_mib": 0,
                "error": str(e)
            }

    def is_model_loaded(self, model: Optional[str] = None) -> bool:
        """
        Проверяет через Ollama /api/ps, загружена ли модель в данный момент в VRAM/RAM.
        """
        target = model or self.default_model
        try:
            resp = requests.get(f"{self.ollama_url}/api/ps", timeout=self.timeout)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return any(
                    target == m.get("name", "") or target == m.get("model", "") or target in m.get("name", "")
                    for m in models
                )
        except Exception:
            pass
        return False

    def unload_ollama(self, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Выгружает модель Ollama из памяти с keep_alive: 0.
        Не считает ошибкой, если модель уже выгружена.
        """
        target = model or self.default_model

        # 1. Проверяем /api/ps - если модель не загружена, фиксируем факт
        already_unloaded = False
        try:
            ps_resp = requests.get(f"{self.ollama_url}/api/ps", timeout=self.timeout)
            if ps_resp.status_code == 200:
                models = ps_resp.json().get("models", [])
                is_loaded = any(
                    target == m.get("name", "") or target == m.get("model", "") or target in m.get("name", "")
                    for m in models
                )
                if not is_loaded:
                    already_unloaded = True
        except Exception:
            # Если /api/ps недоступен, продолжаем попытку через /api/generate
            pass

        if already_unloaded:
            return {
                "success": True,
                "model": target,
                "unloaded": False,
                "already_unloaded": True,
                "message": f"Модель '{target}' уже выгружена из памяти Ollama."
            }

        # 2. Вызываем /api/generate с keep_alive: 0
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={"model": target, "keep_alive": 0},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "model": target,
                    "unloaded": True,
                    "already_unloaded": False,
                    "done_reason": data.get("done_reason", "unload"),
                    "message": f"Модель '{target}' успешно выгружена из памяти Ollama."
                }
            else:
                return {
                    "success": False,
                    "model": target,
                    "unloaded": False,
                    "already_unloaded": False,
                    "error": f"Ollama вернула HTTP {resp.status_code}: {resp.text}"
                }
        except Exception as e:
            return {
                "success": False,
                "model": target,
                "unloaded": False,
                "already_unloaded": False,
                "error": f"Ошибка соединения с Ollama: {e}"
            }

    def free_comfyui(self) -> Dict[str, Any]:
        """
        Освобождает видеопамять ComfyUI Worker через POST /free.
        """
        try:
            resp = requests.post(
                f"{self.comfyui_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": "ComfyUI память успешно освобождена."
                }
            else:
                return {
                    "success": False,
                    "error": f"ComfyUI /free вернул HTTP {resp.status_code}: {resp.text}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка соединения с ComfyUI /free: {e}"
            }

    def prepare_for_image_generation(self, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Подготавливает VRAM к генерации изображений:
        1. Снимает начальную статистику GPU.
        2. Выгружает модель Ollama.
        3. Снимает статистику GPU после выгрузки.
        Возвращает структурированный словарь.
        """
        gpu_initial = self.get_gpu_stats()
        unload_res = self.unload_ollama(model=model)

        if not unload_res.get("success"):
            return {
                "success": False,
                "gpu_initial": gpu_initial,
                "ollama_unload": unload_res,
                "error": f"Не удалось подготовить VRAM: {unload_res.get('error')}"
            }

        gpu_after_unload = self.get_gpu_stats()
        return {
            "success": True,
            "gpu_initial": gpu_initial,
            "gpu_after_unload": gpu_after_unload,
            "ollama_unload": unload_res
        }

    def restore_after_image_generation(self) -> Dict[str, Any]:
        """
        Восстанавливает состояние VRAM после генерации изображений:
        1. Освобождает память ComfyUI (/free).
        2. Снимает финальную статистику GPU.
        НЕ загружает принудительно Ollama (Ollama загрузится штатно при следующем запросе).
        """
        free_res = self.free_comfyui()
        gpu_after = self.get_gpu_stats()

        return {
            "success": free_res.get("success", False),
            "comfyui_free": free_res,
            "gpu_after_restore": gpu_after,
            "error": free_res.get("error") if not free_res.get("success") else None
        }

    @contextmanager
    def image_generation_session(self, model: Optional[str] = None):
        """
        Контекстный менеджер для безопасной сессии генерации изображений.
        Гарантирует вызов restore_after_image_generation() в блоке finally.
        """
        prep_res = self.prepare_for_image_generation(model=model)
        session_data = {
            "prepare": prep_res,
            "restore": None
        }
        try:
            yield session_data
        finally:
            restore_res = self.restore_after_image_generation()
            session_data["restore"] = restore_res


_default_vram_manager: Optional[VRAMManager] = None


def get_vram_manager() -> VRAMManager:
    """Возвращает синглтон VRAMManager."""
    global _default_vram_manager
    if _default_vram_manager is None:
        _default_vram_manager = VRAMManager()
    return _default_vram_manager


def reset_vram_manager() -> None:
    """Сбрасывает синглтон VRAMManager (для изоляции тестов)."""
    global _default_vram_manager
    _default_vram_manager = None
