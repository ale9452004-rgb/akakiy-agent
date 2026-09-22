"""
Модуль специализированного Sub-Agent'а генерации изображений (ImageAgent).

Обеспечивает:
- подключение к локальному изолированному ComfyUI Worker по HTTP API;
- формирование валидного графа workflow для модели SDXL-Lightning 4-step;
- передачу задачи из AgentContext (prompt, negative_prompt, seed, steps, resolution);
- надёжное получение результата через ComfyUI API /view;
- сохранение готовых файлов в директорию data/generated/images/ с безопасными уникальными именами;
- возврат стандартизированного AgentResult с created_files;
- надёжную обработку ошибок (недоступность сервера, таймауты, сбои воркера) без исключений наружу.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import random
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import requests

from config import PROJECT_PATH
from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult
from tools.vram import VRAMManager, get_vram_manager


class ComfyUIClient:
    """
    Легковесный HTTP-клиент для взаимодействия с локальным ComfyUI Worker.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        """Проверяет доступность ComfyUI сервера."""
        try:
            resp = requests.get(f"{self.base_url}/system_stats", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def queue_prompt(self, workflow: Dict[str, Any], client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Отправляет JSON workflow в очередь генерации ComfyUI (/prompt).
        Возвращает ответ сервера с prompt_id.
        """
        payload: Dict[str, Any] = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id

        resp = requests.post(
            f"{self.base_url}/prompt",
            json=payload,
            timeout=10
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"ComfyUI вернул ошибку при постановке задачи: HTTP {resp.status_code} - {resp.text}"
            )
        return resp.json()

    def get_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает статус и результаты выполнения задачи (/history/{prompt_id}).
        """
        resp = requests.get(
            f"{self.base_url}/history/{prompt_id}",
            timeout=5
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get(prompt_id)

    def view_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """
        Скачивает сгенерированное изображение через эндпоинт /view.
        """
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type
        }
        resp = requests.get(
            f"{self.base_url}/view",
            params=params,
            timeout=15
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Не удалось загрузить изображение через /view: HTTP {resp.status_code}"
            )
        return resp.content

    def free_memory(self) -> bool:
        """
        Запрашивает освобождение VRAM в ComfyUI (/free).
        """
        try:
            resp = requests.post(
                f"{self.base_url}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False


RESOLUTION_PRESETS: Dict[str, Tuple[int, int]] = {
    "square": (1024, 1024),
    "квадрат": (1024, 1024),
    "квадратное": (1024, 1024),
    "квадратный": (1024, 1024),
    "1:1": (1024, 1024),
    "landscape": (1216, 832),
    "широкое": (1216, 832),
    "широкий": (1216, 832),
    "горизонтальное": (1216, 832),
    "горизонтальный": (1216, 832),
    "альбомное": (1216, 832),
    "пейзажное": (1216, 832),
    "16:9": (1344, 768),
    "portrait": (832, 1216),
    "вертикальное": (832, 1216),
    "вертикальный": (832, 1216),
    "портретное": (832, 1216),
    "портретный": (832, 1216),
    "9:16": (768, 1344),
}


def safe_validate_resolution(width: Any, height: Any) -> Tuple[int, int]:
    """
    Безопасно валидирует и нормализует разрешение для SDXL на 8 GB VRAM:
    - минимальный размер стороны: 512 px
    - максимальный размер стороны: 1536 px
    - масштабирует при превышении ~1.35 MP с сохранением соотношения сторон
    - округляет до ближайшего кратного 64 (требование VAE SDXL)
    """
    try:
        w = int(width)
        h = int(height)
    except (ValueError, TypeError):
        return 1024, 1024

    if w <= 0:
        w = 1024
    if h <= 0:
        h = 1024

    MAX_PIXELS = 1344 * 768  # ~1.03 MP
    total = w * h
    if total > 1_350_000:
        scale = (MAX_PIXELS / total) ** 0.5
        w = int(w * scale)
        h = int(h * scale)

    w = max(512, min(1536, round(w / 64) * 64))
    h = max(512, min(1536, round(h / 64) * 64))

    return w, h


def safe_validate_count(count: Any) -> int:
    """Безопасно валидирует количество изображений (1..4) для защиты от OOM и таймаутов."""
    try:
        c = int(count)
    except (ValueError, TypeError):
        c = 1
    return max(1, min(4, c))


class ImageAgent(SubAgent):
    """
    Специализированный SubAgent генерации изображений через локальный ComfyUI Worker.
    """

    name: str = "image"
    description: str = "Специализированный sub-agent для генерации изображений через локальный ComfyUI Worker."
    capabilities: List[str] = ["image_generation", "sdxl_lightning", "text_to_image"]

    DEFAULT_CHECKPOINT = "sdxl_lightning_4step.safetensors"
    DEFAULT_NEGATIVE_PROMPT = "blurry, low quality, distorted, bad anatomy, ugly, watermark, signature"
    DEFAULT_WIDTH = 1024
    DEFAULT_HEIGHT = 1024
    DEFAULT_STEPS = 4
    DEFAULT_CFG = 1.5
    DEFAULT_SAMPLER = "euler"
    DEFAULT_SCHEDULER = "sgm_uniform"
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        base_url: str = "http://127.0.0.1:8188",
        output_dir: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        enabled: bool = True,
        vram_manager: Optional[VRAMManager] = None
    ):
        super().__init__(
            name=name or self.name,
            description=description or self.description,
            capabilities=capabilities or self.capabilities,
            enabled=enabled
        )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.output_dir = Path(output_dir) if output_dir else (PROJECT_PATH / "data" / "generated" / "images")
        self.client = ComfyUIClient(base_url=self.base_url, timeout=self.timeout)
        self.vram_manager = vram_manager or get_vram_manager()

    def build_workflow(
        self,
        prompt: str,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        seed: Optional[int] = None,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        steps: int = DEFAULT_STEPS,
        cfg: float = DEFAULT_CFG,
        sampler: str = DEFAULT_SAMPLER,
        scheduler: str = DEFAULT_SCHEDULER,
        checkpoint: str = DEFAULT_CHECKPOINT
    ) -> Dict[str, Any]:
        """
        Формирует минимальный стандартный JSON-граф для SDXL-Lightning 4-step.
        """
        if seed is None:
            seed = random.randint(1, 2**32 - 1)

        return {
            "1": {
                "inputs": {
                    "ckpt_name": checkpoint
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "2": {
                "inputs": {
                    "text": prompt,
                    "clip": ["1", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "3": {
                "inputs": {
                    "text": negative_prompt,
                    "clip": ["1", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "4": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "5": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0]
                },
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEDecode"
            },
            "7": {
                "inputs": {
                    "filename_prefix": "Akakiy_ImageAgent",
                    "images": ["6", 0]
                },
                "class_type": "SaveImage"
            }
        }

    def _generate_safe_filename(self) -> str:
        """Генерирует безопасное уникальное имя для сохраняемого файла изображения."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_suffix = uuid.uuid4().hex[:6]
        return f"img_{timestamp}_{unique_suffix}.png"

    def run(self, context: AgentContext) -> AgentResult:
        """
        Выполняет генерацию изображения по переданному контексту.
        """
        if not self.validate_context(context):
            return AgentResult.fail(
                error="Некорректный контекст: ожидается экземпляр AgentContext."
            )

        if not self.enabled:
            return AgentResult.fail(
                error=f"Sub-agent '{self.name}' отключен."
            )

        # 1. Извлечение и валидация текстового запроса (prompt)
        prompt = context.task.strip()
        if not prompt:
            prompt = str(context.get("prompt", "")).strip()

        if not prompt:
            return AgentResult.fail(
                error="Не указан текст запроса (prompt) для генерации изображения."
            )

        # 1.1. Извлечение и безопасная нормализация разрешения и количества
        aspect_ratio = str(context.get("aspect_ratio", "")).strip().lower()
        raw_width = context.get("width")
        raw_height = context.get("height")

        if aspect_ratio in RESOLUTION_PRESETS and (raw_width is None or raw_height is None):
            width, height = RESOLUTION_PRESETS[aspect_ratio]
        else:
            w_val = raw_width if raw_width is not None else self.DEFAULT_WIDTH
            h_val = raw_height if raw_height is not None else self.DEFAULT_HEIGHT
            width, height = safe_validate_resolution(w_val, h_val)

        count = safe_validate_count(context.get("count", 1))

        # 2. Проверка доступности ComfyUI Worker
        if not self.client.is_available():
            return AgentResult.fail(
                error=f"Локальный ComfyUI Worker недоступен по адресу {self.base_url}. Убедитесь, что воркер запущен."
            )

        # 3. Подготовка VRAM (выгрузка Ollama) через VRAMManager
        manage_vram = context.get("manage_vram", True)
        vram_prepare_info = None
        if manage_vram and self.vram_manager:
            vram_prepare_info = self.vram_manager.prepare_for_image_generation(
                model=context.get("ollama_model")
            )
            if not vram_prepare_info.get("success"):
                return AgentResult.fail(
                    error=f"Ошибка подготовки VRAM: {vram_prepare_info.get('error')}",
                    data={"vram_prepare": vram_prepare_info}
                )

        # 4. Выполнение генерации в защищенном блоке try...finally
        saved_target_paths = []
        total_file_size = 0
        generation_time = 0.0
        generation_error = None
        last_prompt_id = None
        workflow_data = None
        vram_restore_info = None
        cleanup_error = None
        used_seeds = []

        t_overall_start = time.time()
        try:
            negative_prompt = str(context.get("negative_prompt", self.DEFAULT_NEGATIVE_PROMPT))
            steps = int(context.get("steps", self.DEFAULT_STEPS))
            cfg = float(context.get("cfg", self.DEFAULT_CFG))
            sampler = str(context.get("sampler", self.DEFAULT_SAMPLER))
            scheduler = str(context.get("scheduler", self.DEFAULT_SCHEDULER))
            base_seed = context.get("seed")
            checkpoint = str(context.get("checkpoint", self.DEFAULT_CHECKPOINT))
            timeout = int(context.get("timeout", self.timeout))

            self.output_dir.mkdir(parents=True, exist_ok=True)

            for i in range(count):
                if base_seed is not None:
                    curr_seed = int(base_seed) + i
                else:
                    curr_seed = random.randint(1, 2**32 - 1)
                used_seeds.append(curr_seed)

                workflow = self.build_workflow(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    seed=curr_seed,
                    width=width,
                    height=height,
                    steps=steps,
                    cfg=cfg,
                    sampler=sampler,
                    scheduler=scheduler,
                    checkpoint=checkpoint
                )

                # Отправка задачи в ComfyUI
                try:
                    prompt_res = self.client.queue_prompt(workflow)
                    prompt_id = prompt_res.get("prompt_id")
                    if not prompt_id:
                        raise RuntimeError("ComfyUI не вернул prompt_id задачи.")
                    last_prompt_id = prompt_id
                except Exception as e:
                    raise RuntimeError(f"Ошибка при отправке задачи в ComfyUI: {e}")

                # Ожидание завершения генерации
                t_iter_start = time.time()
                deadline = t_iter_start + timeout
                output_images_info = []

                while time.time() < deadline:
                    time.sleep(0.5)
                    try:
                        hist_item = self.client.get_history(prompt_id)
                        if hist_item:
                            status = hist_item.get("status", {})
                            if status.get("status_str") == "error":
                                messages = status.get("messages", [])
                                raise RuntimeError(f"Ошибка выполнения графа в ComfyUI: {messages}")

                            if status.get("completed", False):
                                outputs = hist_item.get("outputs", {})
                                for _, node_out in outputs.items():
                                    if isinstance(node_out, dict) and "images" in node_out:
                                        imgs = node_out["images"]
                                        if imgs:
                                            output_images_info.extend(imgs)
                                break
                    except Exception as ex:
                        if "Ошибка выполнения графа" in str(ex):
                            raise ex
                        pass

                if not output_images_info:
                    if time.time() >= deadline:
                        raise TimeoutError(f"Превышено время ожидания генерации изображения ({timeout} сек).")
                    raise RuntimeError("ComfyUI завершил задачу, но не вернул выходное изображение.")

                # Скачивание и сохранение изображений текущей итерации
                for img_info in output_images_info:
                    remote_filename = img_info.get("filename")
                    subfolder = img_info.get("subfolder", "")
                    folder_type = img_info.get("type", "output")
                    if not remote_filename:
                        continue

                    image_bytes = self.client.view_image(
                        filename=remote_filename,
                        subfolder=subfolder,
                        folder_type=folder_type
                    )
                    if not image_bytes or len(image_bytes) == 0:
                        raise RuntimeError("Получено пустое изображение (0 байт) от ComfyUI.")

                    safe_name = self._generate_safe_filename()
                    target_path = (self.output_dir / safe_name).resolve()
                    with open(target_path, "wb") as f:
                        f.write(image_bytes)
                    saved_target_paths.append(target_path)
                    total_file_size += len(image_bytes)

            workflow_data = {
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
                "sampler": sampler,
                "scheduler": scheduler,
                "checkpoint": checkpoint,
                "seed": base_seed if base_seed is not None else (used_seeds[0] if used_seeds else None),
                "seeds": used_seeds,
                "count": count
            }
            generation_time = time.time() - t_overall_start

        except Exception as e:
            generation_error = str(e)
        finally:
            # Гарантированное освобождение VRAM через VRAMManager в блоке finally
            if manage_vram and self.vram_manager:
                try:
                    vram_restore_info = self.vram_manager.restore_after_image_generation()
                    if not vram_restore_info.get("success"):
                        cleanup_error = vram_restore_info.get("error", "ComfyUI /free failed")
                except Exception as e:
                    cleanup_error = str(e)
            if context.get("auto_free", True):
                try:
                    self.client.free_memory()
                except Exception as e:
                    if not cleanup_error:
                        cleanup_error = str(e)

        # Обработка результатов
        if generation_error is not None and not saved_target_paths:
            return AgentResult.fail(
                error=generation_error,
                data={
                    "prompt": prompt,
                    "prompt_id": last_prompt_id,
                    "vram_prepare": vram_prepare_info,
                    "vram_restore": vram_restore_info,
                    "vram_cleanup_error": cleanup_error
                }
            )

        # Генерация успешна
        if len(saved_target_paths) == 1:
            safe_name = saved_target_paths[0].name
            msg = f"Изображение успешно сгенерировано: {safe_name}"
        else:
            names = ", ".join(p.name for p in saved_target_paths)
            msg = f"Успешно сгенерировано изображений: {len(saved_target_paths)} ({names})"

        if cleanup_error:
            msg += f" (Предупреждение: ошибка освобождения VRAM: {cleanup_error})"

        res_data = {
            "prompt": prompt,
            "saved_to": [str(p) for p in saved_target_paths],
            "count": len(saved_target_paths),
            "width": width,
            "height": height,
            "file_size_bytes": total_file_size,
            "generation_time_sec": round(generation_time, 2),
            "vram_prepare": vram_prepare_info,
            "vram_restore": vram_restore_info,
            "vram_cleanup_error": cleanup_error
        }
        if workflow_data:
            res_data.update(workflow_data)

        return AgentResult.ok(
            message=msg,
            created_files=[str(p) for p in saved_target_paths],
            data=res_data
        )
