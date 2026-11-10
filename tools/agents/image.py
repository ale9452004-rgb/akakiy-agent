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
import math
import os
from pathlib import Path
import random
import shutil
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


def normalize_mask_bbox(
    raw_bbox: Any,
    img_width: Optional[int] = None,
    img_height: Optional[int] = None,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Валидирует и нормализует прямоугольник маски в (left, top, right, bottom) в [0.0, 1.0].
    Поддерживает как нормализованные значения (0..1), так и пиксельные / 0..1000 координаты.
    """
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
        return None
    try:
        vals = [float(v) for v in raw_bbox]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(v) for v in vals):
        return None

    x1, y1, x2, y2 = vals
    max_v = max(abs(x1), abs(y1), abs(x2), abs(y2))
    if max_v > 1.5:
        if img_width and img_height and img_width > 0 and img_height > 0:
            x1 /= float(img_width)
            x2 /= float(img_width)
            y1 /= float(img_height)
            y2 /= float(img_height)
        elif max_v <= 1000.0:
            x1 /= 1000.0
            y1 /= 1000.0
            x2 /= 1000.0
            y2 /= 1000.0

    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    x2 = max(0.0, min(1.0, x2))
    y2 = max(0.0, min(1.0, y2))

    left, right = (x1, x2) if x1 <= x2 else (x2, x1)
    top, bottom = (y1, y2) if y1 <= y2 else (y2, y1)
    if (right - left) < 0.01 or (bottom - top) < 0.01:
        return None

    return (left, top, right, bottom)


def generate_feathered_mask_png(
    source_image_path: str,
    mask_bbox: Any,
    output_path: Path,
    fallback_width: int = 1024,
    fallback_height: int = 1024,
    feather: int = 16,
) -> Tuple[int, int]:
    """
    Создаёт PNG-маску (белый внутри bbox — область правки, чёрный снаружи — сохраняется)
    с мягким размытием краёв (GaussianBlur).
    """
    from PIL import Image, ImageDraw, ImageFilter

    img_w, img_h = int(fallback_width or 1024), int(fallback_height or 1024)
    try:
        with Image.open(source_image_path) as src_im:
            if src_im.size[0] > 0 and src_im.size[1] > 0:
                img_w, img_h = int(src_im.size[0]), int(src_im.size[1])
    except Exception:
        pass

    norm = normalize_mask_bbox(mask_bbox, img_width=img_w, img_height=img_h)
    if norm is None:
        raise ValueError(
            "Некорректный формат mask_bbox: ожидается список из 4 чисел [x1, y1, x2, y2]."
        )

    x1, y1, x2, y2 = norm
    px1 = max(0, min(img_w - 1, int(round(x1 * img_w))))
    py1 = max(0, min(img_h - 1, int(round(y1 * img_h))))
    px2 = max(px1 + 1, min(img_w, int(round(x2 * img_w))))
    py2 = max(py1 + 1, min(img_h, int(round(y2 * img_h))))

    mask_img = Image.new("L", (img_w, img_h), 0)
    draw = ImageDraw.Draw(mask_img)
    draw.rectangle([px1, py1, px2, py2], fill=255)

    try:
        blur_radius = max(0.0, min(128.0, float(feather)))
    except (TypeError, ValueError):
        blur_radius = 16.0
    if blur_radius > 0:
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Сохраняем в RGB, чтобы ComfyUI LoadImageMask(channel="red") однозначно читал маску
    mask_img.convert("RGB").save(str(output_path), format="PNG")
    return img_w, img_h


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

    def get_available_models(self) -> Dict[str, List[str]]:
        """
        Возвращает словарь реально установленных в ComfyUI моделей по категориям.
        """
        models_root = PROJECT_PATH / "workers" / "comfyui" / "models"
        res: Dict[str, List[str]] = {
            "checkpoints": [],
            "controlnet": [],
            "inpaint": [],
            "loras": []
        }
        if not models_root.exists():
            return res

        for category, key in [
            ("checkpoints", "checkpoints"),
            ("controlnet", "controlnet"),
            ("loras", "loras"),
        ]:
            cat_dir = models_root / category
            if cat_dir.is_dir():
                for f in cat_dir.iterdir():
                    if f.is_file() and not f.name.startswith("put_"):
                        res[key].append(f.name)

        return res

    def has_controlnet_openpose(self) -> bool:
        """Проверяет наличие установленной модели ControlNet OpenPose/DWPose для SDXL."""
        return self.find_controlnet_model("openpose") is not None

    def has_controlnet_canny(self) -> bool:
        """Проверяет наличие установленной модели ControlNet Canny для SDXL."""
        return self.find_controlnet_model("canny") is not None

    def find_controlnet_model(self, control_type: str) -> Optional[str]:
        """Возвращает имя файла установленной модели ControlNet заданного типа (или None)."""
        ct = str(control_type or "").strip().lower()
        if not ct:
            return None

        if any(k in ct for k in ("openpose", "pose", "dwpose")):
            terms = ("openpose", "pose", "dwpose")
        elif "canny" in ct:
            terms = ("canny",)
        elif "depth" in ct:
            terms = ("depth",)
        elif any(k in ct for k in ("softedge", "hed", "scribble")):
            terms = ("softedge", "hed", "scribble")
        else:
            terms = (ct,)

        models = self.get_available_models()
        for f in models.get("controlnet", []):
            name_lower = f.lower()
            if any(term in name_lower for term in terms):
                return f
        return None

    def get_inpaint_checkpoint(self) -> Optional[str]:
        """Возвращает имя установленного Inpaint checkpoint (если есть)."""
        models = self.get_available_models()
        for f in models.get("checkpoints", []):
            if "inpaint" in f.lower():
                return f
        return None

    def has_inpaint_model(self) -> bool:
        """Проверяет наличие специализированной Inpaint-модели."""
        models = self.get_available_models()
        for cat in ("checkpoints", "controlnet"):
            for f in models.get(cat, []):
                if "inpaint" in f.lower():
                    return True
        return False

    def build_img2img_workflow(
        self,
        input_image_name: str,
        prompt: str,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        seed: Optional[int] = None,
        denoise: float = 0.65,
        steps: int = DEFAULT_STEPS,
        cfg: float = DEFAULT_CFG,
        sampler: str = DEFAULT_SAMPLER,
        scheduler: str = DEFAULT_SCHEDULER,
        checkpoint: str = DEFAULT_CHECKPOINT
    ) -> Dict[str, Any]:
        """
        Формирует стандартный JSON-граф img2img для SDXL-Lightning 4-step:
        LoadImage -> VAEEncode -> KSampler (denoise) -> VAEDecode -> SaveImage.
        """
        if seed is None:
            seed = random.randint(1, 2**32 - 1)

        denoise = max(0.1, min(1.0, float(denoise)))

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
                    "image": input_image_name
                },
                "class_type": "LoadImage"
            },
            "5": {
                "inputs": {
                    "pixels": ["4", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEEncode"
            },
            "6": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "denoise": denoise,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "7": {
                "inputs": {
                    "samples": ["6", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEDecode"
            },
            "8": {
                "inputs": {
                    "filename_prefix": "Akakiy_ImageAgent_Edit",
                    "images": ["7", 0]
                },
                "class_type": "SaveImage"
            }
        }

    def build_inpaint_workflow(
        self,
        input_image_name: str,
        mask_image_name: str,
        prompt: str,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        seed: Optional[int] = None,
        denoise: float = 0.78,
        steps: int = DEFAULT_STEPS,
        cfg: float = DEFAULT_CFG,
        sampler: str = DEFAULT_SAMPLER,
        scheduler: str = DEFAULT_SCHEDULER,
        checkpoint: str = DEFAULT_CHECKPOINT,
        use_inpaint_conditioning: bool = False,
    ) -> Dict[str, Any]:
        """
        Формирует JSON-граф локального Inpainting:
        - со стандартным checkpoint (в т.ч. SDXL-Lightning): LoadImageMask + SetLatentNoiseMask;
        - со специализированной inpaint-моделью: LoadImageMask + InpaintModelConditioning.
        """
        if seed is None:
            seed = random.randint(1, 2**32 - 1)

        denoise = max(0.15, min(1.0, float(denoise)))

        workflow: Dict[str, Any] = {
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
                    "image": input_image_name
                },
                "class_type": "LoadImage"
            },
            "9": {
                "inputs": {
                    "image": mask_image_name,
                    "channel": "red"
                },
                "class_type": "LoadImageMask"
            },
        }

        if use_inpaint_conditioning:
            workflow["10"] = {
                "inputs": {
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "vae": ["1", 2],
                    "pixels": ["4", 0],
                    "mask": ["9", 0],
                    "noise_mask": True,
                },
                "class_type": "InpaintModelConditioning"
            }
            pos_ref = ["10", 0]
            neg_ref = ["10", 1]
            latent_ref = ["10", 2]
        else:
            workflow["5"] = {
                "inputs": {
                    "pixels": ["4", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEEncode"
            }
            workflow["10"] = {
                "inputs": {
                    "samples": ["5", 0],
                    "mask": ["9", 0]
                },
                "class_type": "SetLatentNoiseMask"
            }
            pos_ref = ["2", 0]
            neg_ref = ["3", 0]
            latent_ref = ["10", 0]

        workflow["6"] = {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": ["1", 0],
                "positive": pos_ref,
                "negative": neg_ref,
                "latent_image": latent_ref
            },
            "class_type": "KSampler"
        }
        workflow["7"] = {
            "inputs": {
                "samples": ["6", 0],
                "vae": ["1", 2]
            },
            "class_type": "VAEDecode"
        }
        workflow["8"] = {
            "inputs": {
                "filename_prefix": "Akakiy_ImageAgent_Inpaint",
                "images": ["7", 0]
            },
            "class_type": "SaveImage"
        }
        return workflow

    def build_controlnet_workflow(
        self,
        input_image_name: str,
        controlnet_name: str,
        prompt: str,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        seed: Optional[int] = None,
        denoise: float = 0.72,
        control_type: str = "canny",
        control_strength: float = 0.8,
        start_percent: float = 0.0,
        end_percent: float = 1.0,
        steps: int = DEFAULT_STEPS,
        cfg: float = DEFAULT_CFG,
        sampler: str = DEFAULT_SAMPLER,
        scheduler: str = DEFAULT_SCHEDULER,
        checkpoint: str = DEFAULT_CHECKPOINT,
    ) -> Dict[str, Any]:
        """
        Формирует JSON-граф редактирования с ControlNet (Canny / OpenPose / Depth).
        При control_type='canny' автоматически подключает встроенный препроцессор Canny.
        """
        if seed is None:
            seed = random.randint(1, 2**32 - 1)

        denoise = max(0.15, min(1.0, float(denoise)))
        control_strength = max(0.0, min(2.0, float(control_strength)))
        ct = str(control_type or "canny").strip().lower()

        workflow: Dict[str, Any] = {
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
                    "image": input_image_name
                },
                "class_type": "LoadImage"
            },
            "5": {
                "inputs": {
                    "pixels": ["4", 0],
                    "vae": ["1", 2]
                },
                "class_type": "VAEEncode"
            },
            "9": {
                "inputs": {
                    "control_net_name": controlnet_name
                },
                "class_type": "ControlNetLoader"
            },
        }

        if ct == "canny":
            workflow["10"] = {
                "inputs": {
                    "image": ["4", 0],
                    "low_threshold": 0.4,
                    "high_threshold": 0.8,
                },
                "class_type": "Canny"
            }
            hint_image_ref = ["10", 0]
        else:
            hint_image_ref = ["4", 0]

        workflow["11"] = {
            "inputs": {
                "positive": ["2", 0],
                "negative": ["3", 0],
                "control_net": ["9", 0],
                "image": hint_image_ref,
                "strength": control_strength,
                "start_percent": max(0.0, min(1.0, float(start_percent))),
                "end_percent": max(0.0, min(1.0, float(end_percent))),
                "vae": ["1", 2],
            },
            "class_type": "ControlNetApplyAdvanced"
        }
        workflow["6"] = {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": ["1", 0],
                "positive": ["11", 0],
                "negative": ["11", 1],
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        }
        workflow["7"] = {
            "inputs": {
                "samples": ["6", 0],
                "vae": ["1", 2]
            },
            "class_type": "VAEDecode"
        }
        workflow["8"] = {
            "inputs": {
                "filename_prefix": "Akakiy_ImageAgent_ControlNet",
                "images": ["7", 0]
            },
            "class_type": "SaveImage"
        }
        return workflow

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

        # 1.2. Извлечение и валидация параметров редактирования (Scenario C)
        action = str(context.get("action", "generate")).strip().lower()
        edit_type = str(context.get("edit_type", "general")).strip().lower()
        source_image_path = context.get("source_image_path")
        mask_bbox = context.get("mask_bbox")
        mask_path_raw = context.get("mask_path")
        mask_path = str(mask_path_raw).strip() if mask_path_raw else None
        feather = context.get("feather", 16)
        raw_control_type = context.get("control_type")
        requested_control_type = str(raw_control_type).strip().lower() if raw_control_type else None
        control_strength = context.get("control_strength", 0.8)
        normalized_mask_bbox = None
        controlnet_name: Optional[str] = None
        inpaint_checkpoint: Optional[str] = None

        if action == "edit":
            if not source_image_path:
                return AgentResult.fail(
                    error="Не указан путь к исходному изображению для редактирования (source_image_path)."
                )
            if not Path(source_image_path).is_file():
                return AgentResult.fail(
                    error=f"Исходное изображение не найдено на диске: {source_image_path}"
                )
            if raw_width is None and raw_height is None:
                try:
                    from PIL import Image
                    with Image.open(source_image_path) as src_im:
                        src_w, src_h = src_im.size
                        if src_w > 0 and src_h > 0:
                            width, height = int(src_w), int(src_h)
                except Exception:
                    pass

            if mask_path:
                if not Path(mask_path).is_file():
                    return AgentResult.fail(
                        error=f"Файл маски не найден на диске: {mask_path}"
                    )
            elif mask_bbox is not None:
                normalized_mask_bbox = normalize_mask_bbox(
                    mask_bbox, img_width=width, img_height=height
                )
                if normalized_mask_bbox is None:
                    return AgentResult.fail(
                        error="Некорректные координаты области маски (mask_bbox): ожидается [x1, y1, x2, y2]."
                    )

            has_explicit_mask = bool(mask_path or normalized_mask_bbox is not None)

            if requested_control_type:
                controlnet_name = self.find_controlnet_model(requested_control_type)
                if not controlnet_name:
                    comp_label = (
                        "ControlNet OpenPose (SDXL)"
                        if any(k in requested_control_type for k in ("openpose", "pose", "dwpose"))
                        else f"ControlNet {requested_control_type.upper() if requested_control_type == 'canny' else requested_control_type.title()} (SDXL)"
                    )
                    msg = (
                        f"Для структурного редактирования с '{requested_control_type}' требуется "
                        f"модель {comp_label}, которая в данный момент не установлена в ComfyUI "
                        f"(workers/comfyui/models/controlnet/).\n\n"
                        "Доступные варианты:\n"
                        "1. Выполнить редактирование без ControlNet (через img2img или точечный inpainting по маске).\n"
                        "2. Сгенерировать новое изображение по уточнённому промпту."
                    )
                    return AgentResult.ok(
                        message=msg,
                        data={
                            "status": "missing_model",
                            "edit_type": edit_type,
                            "control_type": requested_control_type,
                            "missing_component": comp_label,
                            "source_image": str(source_image_path),
                            "alternatives": ["img2img_variation", "generate_new"],
                        }
                    )

            # Проверка доступности специализированных моделей (Rule 5 & Rule 7)
            if edit_type == "pose" and not self.has_controlnet_openpose() and not has_explicit_mask:
                msg = (
                    "Для точного изменения позы персонажа с сохранением исходного изображения требуется "
                    "модель управления позой (ControlNet OpenPose для SDXL), которая в данный момент "
                    "не установлена в ComfyUI.\n\n"
                    "Доступные варианты:\n"
                    "1. Сгенерировать новое изображение с нужной позой по уточненному промпту.\n"
                    "2. Создать вариацию через img2img (с изменением композиции без жесткой фиксации позы).\n\n"
                    "Уточните, какой вариант вы хотите выполнить."
                )
                return AgentResult.ok(
                    message=msg,
                    data={
                        "status": "missing_model",
                        "edit_type": "pose",
                        "missing_component": "ControlNet OpenPose (SDXL)",
                        "source_image": str(source_image_path),
                        "alternatives": ["generate_new", "img2img_variation"]
                    }
                )

            if edit_type == "remove" and not self.has_inpaint_model() and not has_explicit_mask:
                msg = (
                    "Для точечного удаления объекта с сохранением остального изображения требуется "
                    "модель Inpainting или разметка маски, которая в данный момент не установлена в ComfyUI.\n\n"
                    "Доступные варианты:\n"
                    "1. Перегенерировать изображение с уточнением (только один объект, без лишних деталей).\n"
                    "2. Создать вариацию через img2img.\n\n"
                    "Уточните, какой вариант вы хотите выполнить."
                )
                return AgentResult.ok(
                    message=msg,
                    data={
                        "status": "missing_model",
                        "edit_type": "remove",
                        "missing_component": "Inpainting Model / Segmentation Mask",
                        "source_image": str(source_image_path),
                        "alternatives": ["revise_prompt", "img2img_variation"]
                    }
                )

            if has_explicit_mask:
                inpaint_checkpoint = self.get_inpaint_checkpoint()

        # 2. Проверка доступности ComfyUI Worker
        if not self.client.is_available():
            try:
                from infrastructure.comfyui_manager import get_comfyui_manager
                comfy_mgr = get_comfyui_manager()
                if comfy_mgr.is_starting():
                    wait_timeout = getattr(comfy_mgr, "timeout", 30.0)
                    if not comfy_mgr.wait_until_ready(timeout=wait_timeout):
                        return AgentResult.fail(
                            error="Локальный ComfyUI Worker ещё запускается. Пожалуйста, повторите запрос через несколько секунд."
                        )
            except Exception:
                pass

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
        staged_input_name = None
        staged_input_path = None
        staged_mask_name = None
        staged_mask_path = None
        if action == "edit" and source_image_path:
            try:
                comfy_input_dir = PROJECT_PATH / "workers" / "comfyui" / "input"
                comfy_input_dir.mkdir(parents=True, exist_ok=True)
                src_p = Path(source_image_path)
                stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                staged_input_name = f"edit_in_{stamp}{src_p.suffix}"
                staged_input_path = comfy_input_dir / staged_input_name
                shutil.copy2(src_p, staged_input_path)

                if mask_path:
                    mask_src_p = Path(mask_path)
                    staged_mask_name = f"mask_{stamp}{mask_src_p.suffix or '.png'}"
                    staged_mask_path = comfy_input_dir / staged_mask_name
                    shutil.copy2(mask_src_p, staged_mask_path)
                elif normalized_mask_bbox is not None:
                    staged_mask_name = f"mask_{stamp}.png"
                    staged_mask_path = comfy_input_dir / staged_mask_name
                    generate_feathered_mask_png(
                        source_image_path=str(source_image_path),
                        mask_bbox=list(normalized_mask_bbox),
                        output_path=staged_mask_path,
                        fallback_width=width,
                        fallback_height=height,
                        feather=feather,
                    )
            except Exception as ex:
                for p in (staged_input_path, staged_mask_path):
                    if p and p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                return AgentResult.fail(
                    error=f"Ошибка подготовки входных файлов в ComfyUI input: {ex}"
                )

        saved_target_paths = []
        total_file_size = 0
        generation_time = 0.0
        generation_error = None
        last_prompt_id = None
        workflow_data = None
        vram_restore_info = None
        cleanup_error = None
        used_seeds = []
        edit_mode = "txt2img"

        t_overall_start = time.time()
        try:
            # 3.1. Семантическая компиляция и обогащение промпта для SDXL-Lightning
            skip_compile = bool(context.get("skip_compile", False))
            if not skip_compile and action != "edit":
                from tools.prompt_compiler import compile_image_prompt
                effective_prompt, effective_negative, prompt_meta = compile_image_prompt(
                    raw_prompt=prompt,
                    count=count,
                    negative_prompt=context.get("negative_prompt"),
                    is_revision=bool(context.get("is_revision", False)),
                    critique_details=context.get("critique_details")
                )
                llm_translated = context.get("llm_translated_prompt")
                if prompt_meta.get("subject") is None and llm_translated and str(llm_translated).strip():
                    effective_prompt = str(llm_translated).strip()
                    prompt_meta = dict(prompt_meta)
                    prompt_meta["llm_translated"] = True
            else:
                effective_prompt = prompt
                raw_neg = context.get("negative_prompt")
                effective_negative = str(raw_neg) if raw_neg else self.DEFAULT_NEGATIVE_PROMPT
                prompt_meta = {}

            negative_prompt = effective_negative
            raw_ckpt = context.get("checkpoint")
            checkpoint = str(raw_ckpt) if raw_ckpt else (
                inpaint_checkpoint if (staged_mask_name and inpaint_checkpoint) else self.DEFAULT_CHECKPOINT
            )
            use_inpaint_cond = bool(staged_mask_name and ("inpaint" in checkpoint.lower()))
            default_steps = (
                20 if ("inpaint" in checkpoint.lower() and "lightning" not in checkpoint.lower())
                else self.DEFAULT_STEPS
            )
            default_cfg = (
                6.5 if ("inpaint" in checkpoint.lower() and "lightning" not in checkpoint.lower())
                else self.DEFAULT_CFG
            )
            steps = int(context.get("steps", default_steps))
            cfg = float(context.get("cfg", default_cfg))
            sampler = str(context.get("sampler", self.DEFAULT_SAMPLER))
            scheduler = str(context.get("scheduler", self.DEFAULT_SCHEDULER))
            base_seed = context.get("seed")
            timeout = int(context.get("timeout", self.timeout))

            self.output_dir.mkdir(parents=True, exist_ok=True)

            for i in range(count):
                if base_seed is not None:
                    curr_seed = int(base_seed) + i
                else:
                    curr_seed = random.randint(1, 2**32 - 1)
                used_seeds.append(curr_seed)

                if action == "edit" and staged_input_name:
                    if staged_mask_name:
                        edit_mode = "inpaint"
                        denoise = float(context.get("denoise", 0.78))
                        workflow = self.build_inpaint_workflow(
                            input_image_name=staged_input_name,
                            mask_image_name=staged_mask_name,
                            prompt=effective_prompt,
                            negative_prompt=effective_negative,
                            seed=curr_seed,
                            denoise=denoise,
                            steps=steps,
                            cfg=cfg,
                            sampler=sampler,
                            scheduler=scheduler,
                            checkpoint=checkpoint,
                            use_inpaint_conditioning=use_inpaint_cond,
                        )
                    elif controlnet_name:
                        edit_mode = "controlnet"
                        denoise = float(context.get("denoise", 0.72))
                        workflow = self.build_controlnet_workflow(
                            input_image_name=staged_input_name,
                            controlnet_name=controlnet_name,
                            prompt=effective_prompt,
                            negative_prompt=effective_negative,
                            seed=curr_seed,
                            denoise=denoise,
                            control_type=requested_control_type or "canny",
                            control_strength=float(control_strength if control_strength is not None else 0.8),
                            steps=steps,
                            cfg=cfg,
                            sampler=sampler,
                            scheduler=scheduler,
                            checkpoint=checkpoint,
                        )
                    else:
                        edit_mode = "img2img"
                        denoise = float(context.get("denoise", 0.65))
                        workflow = self.build_img2img_workflow(
                            input_image_name=staged_input_name,
                            prompt=effective_prompt,
                            negative_prompt=effective_negative,
                            seed=curr_seed,
                            denoise=denoise,
                            steps=steps,
                            cfg=cfg,
                            sampler=sampler,
                            scheduler=scheduler,
                            checkpoint=checkpoint
                        )
                else:
                    edit_mode = "txt2img"
                    workflow = self.build_workflow(
                        prompt=effective_prompt,
                        negative_prompt=effective_negative,
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
                "raw_prompt": prompt,
                "positive_prompt": effective_prompt,
                "negative_prompt": effective_negative,
                "prompt_metadata": prompt_meta,
                "edit_mode": edit_mode,
                "mask_used": bool(staged_mask_name),
                "controlnet_used": controlnet_name,
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
            # Очистка временных файлов (вход + маска) в ComfyUI input при редактировании
            for staged_p in (staged_input_path, staged_mask_path):
                if staged_p:
                    try:
                        if staged_p.exists():
                            staged_p.unlink()
                    except Exception:
                        pass

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

        # Генерация/редактирование успешны
        if len(saved_target_paths) == 1:
            safe_name = saved_target_paths[0].name
            if action == "edit":
                msg = f"Изображение успешно отредактировано: {safe_name}"
            else:
                msg = f"Изображение успешно сгенерировано: {safe_name}"
        else:
            names = ", ".join(p.name for p in saved_target_paths)
            if action == "edit":
                msg = f"Успешно отредактировано изображений: {len(saved_target_paths)} ({names})"
            else:
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
