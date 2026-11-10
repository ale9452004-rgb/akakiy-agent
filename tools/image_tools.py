"""
Инструментальный слой (Native Tool Calling) для генерации, редактирования
и управления контекстом изображений через Qwen (`qwen3:8b`).

Обеспечивает:
- `generate_image`: генерация новых изображений через ImageAgent (SDXL-Lightning);
- `edit_image`: редактирование активного или указанного PNG-изображения через EditPlanner + ImageAgent;
- `get_active_image`: инспекция текущего активного изображения и истории правок;
- `select_image`: выбор конкретного файла PNG как активного контекста.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from tools.agents import AgentContext, AgentResult, get_agent_registry
from tools.agents.image import ImageAgent, RESOLUTION_PRESETS, safe_validate_count, safe_validate_resolution
from tools.edit_planner import EditPlanner
from tools.image_context import ImageContextTracker
from tools.prompt_compiler import BASE_NEGATIVE_PROMPT, PromptCompiler, translate_prompt_to_sdxl_tags

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")

_active_agent_var: ContextVar[Optional[Any]] = ContextVar("akakiy_active_image_agent", default=None)
_fallback_image_context: Optional[ImageContextTracker] = None


@contextmanager
def bind_active_image_agent(agent: Optional[Any]):
    """Привязывает экземпляр Agent к текущему контексту выполнения инструментов."""
    token = _active_agent_var.set(agent)
    try:
        yield
    finally:
        _active_agent_var.reset(token)


def get_bound_image_agent() -> Optional[Any]:
    """Возвращает текущий привязанный Agent (или None)."""
    return _active_agent_var.get()


def get_fallback_image_context() -> ImageContextTracker:
    """Возвращает изолированный fallback-трекер для прямых вызовов вне Agent."""
    global _fallback_image_context
    if _fallback_image_context is None:
        _fallback_image_context = ImageContextTracker()
    return _fallback_image_context


def reset_fallback_image_context() -> None:
    """Сбрасывает fallback-трекер (для тестов)."""
    global _fallback_image_context
    _fallback_image_context = None


def _resolve_context_tracker(agent: Optional[Any]) -> ImageContextTracker:
    if agent is not None and hasattr(agent, "image_context") and agent.image_context is not None:
        return agent.image_context
    return get_fallback_image_context()


def _sync_agent_legacy_cache(
    agent: Optional[Any],
    tracker: ImageContextTracker,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    if agent is None:
        return
    legacy = tracker.to_legacy_dict(validate_disk=True)
    if artifacts is not None:
        legacy["artifacts"] = artifacts
    if data is not None:
        legacy["data"] = data
    agent._last_image_result = legacy


def _run_image_subagent(agent: Optional[Any], task: str, **kwargs: Any) -> AgentResult:
    if agent is not None and hasattr(agent, "run_subagent"):
        kwargs.setdefault("_permission_approved", True)
        return agent.run_subagent("image", task=task, **kwargs)

    registry = get_agent_registry()
    img_agent = registry.get("image")
    if img_agent is None:
        img_agent = ImageAgent()
        registry.register(img_agent)

    ctx = AgentContext(task=task, metadata=dict(kwargs), parent_agent=agent)
    return img_agent.run(ctx)


def _merge_negative_prompts(*parts: Optional[str]) -> str:
    merged: List[str] = []
    seen = set()
    for part in parts:
        if not part:
            continue
        for token in str(part).split(","):
            cleaned = token.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key not in seen:
                seen.add(key)
                merged.append(cleaned)
    return ", ".join(merged) if merged else BASE_NEGATIVE_PROMPT


def generate_image(
    prompt: str,
    aspect_ratio: str = "square",
    count: int = 1,
    negative_prompt: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Генерирует новое изображение по описанию (предпочтительно английские SDXL-теги).
    """
    raw_prompt = str(prompt or "").strip()
    if not raw_prompt:
        return {
            "success": False,
            "error": "Не указан текст описания (prompt) для генерации изображения.",
        }

    agent = get_bound_image_agent()
    tracker = _resolve_context_tracker(agent)

    eff_aspect = str(aspect_ratio or "square").strip().lower()
    eff_count = safe_validate_count(count)

    eff_width = width
    eff_height = height
    if eff_width is None or eff_height is None:
        if eff_aspect in RESOLUTION_PRESETS:
            eff_width, eff_height = RESOLUTION_PRESETS[eff_aspect]
        else:
            eff_width, eff_height = safe_validate_resolution(eff_width or 1024, eff_height or 1024)
    else:
        eff_width, eff_height = safe_validate_resolution(eff_width, eff_height)

    has_cyrillic = bool(_CYRILLIC_RE.search(raw_prompt))
    subagent_kwargs: Dict[str, Any] = {
        "action": "generate",
        "width": eff_width,
        "height": eff_height,
        "aspect_ratio": eff_aspect,
        "count": eff_count,
    }

    if not has_cyrillic:
        # Qwen уже сформировал английский SDXL-промпт — передаём его без урезания словарями
        _, compiler_neg, _ = PromptCompiler.compile(
            raw_prompt,
            count=eff_count,
            negative_prompt=negative_prompt,
        )
        eff_neg = _merge_negative_prompts(negative_prompt, compiler_neg, BASE_NEGATIVE_PROMPT)
        subagent_kwargs["skip_compile"] = True
        subagent_kwargs["negative_prompt"] = eff_neg
    else:
        # На русском — запускаем компилятор и опциональный LLM-перевод при неизвестном объекте
        _, compiler_neg, comp_meta = PromptCompiler.compile(
            raw_prompt,
            count=eff_count,
            negative_prompt=negative_prompt,
        )
        subagent_kwargs["negative_prompt"] = _merge_negative_prompts(negative_prompt, compiler_neg)
        if comp_meta.get("subject") is None and agent is not None and getattr(agent, "ai", None):
            translated = translate_prompt_to_sdxl_tags(raw_prompt, agent.ai)
            if translated:
                subagent_kwargs["llm_translated_prompt"] = translated

    sub_res = _run_image_subagent(agent, task=raw_prompt, **subagent_kwargs)
    if not sub_res.success:
        err_msg = sub_res.error or sub_res.message or "Неизвестная ошибка генерации изображения."
        return {
            "success": False,
            "error": err_msg,
            "created_files": [],
            "artifacts": [],
        }

    artifacts_dicts = [a.to_dict() if hasattr(a, "to_dict") else a for a in sub_res.artifacts]
    created = list(sub_res.created_files)
    res_data = dict(getattr(sub_res, "data", {}) or {})
    stored_prompt = res_data.get("positive_prompt") or raw_prompt

    if created:
        tracker.track_generation(
            file_path=created[0],
            prompt=stored_prompt,
            is_revision=False,
            width=res_data.get("width", eff_width),
            height=res_data.get("height", eff_height),
            aspect_ratio=eff_aspect,
            count=len(created),
            raw_prompt=raw_prompt,
        )
        _sync_agent_legacy_cache(agent, tracker, artifacts=artifacts_dicts, data=res_data)

    return {
        "success": True,
        "message": sub_res.message,
        "created_files": created,
        "artifacts": artifacts_dicts,
        "active_image_path": created[0] if created else tracker.get_active_image_path(validate_disk=True),
        "prompt": raw_prompt,
        "positive_prompt": res_data.get("positive_prompt", raw_prompt),
        "negative_prompt": res_data.get("negative_prompt", subagent_kwargs.get("negative_prompt")),
        "width": res_data.get("width", eff_width),
        "height": res_data.get("height", eff_height),
    }


def edit_image(
    instruction: str,
    target_image_path: Optional[str] = None,
    edit_type: Optional[str] = None,
    positive_prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    denoise: Optional[float] = None,
    mask_bbox: Optional[List[float]] = None,
    mask_path: Optional[str] = None,
    feather: int = 12,
    control_type: Optional[str] = None,
    control_strength: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Редактирует активное или указанное изображение с учётом типа правки и промптов.
    """
    clean_instr = str(instruction or "").strip()
    if not clean_instr:
        return {
            "success": False,
            "error": "Не указана инструкция редактирования (instruction).",
        }

    agent = get_bound_image_agent()
    tracker = _resolve_context_tracker(agent)

    source_path: Optional[str] = None
    if target_image_path:
        cand = str(target_image_path).strip()
        if not os.path.isfile(cand):
            return {
                "success": False,
                "error": f"Файл изображения не найден на диске: {cand}",
            }
        source_path = cand
    else:
        source_path = tracker.get_active_image_path(validate_disk=True)

    if not source_path:
        return {
            "success": False,
            "error": (
                "Нет активного изображения для редактирования. "
                "Сначала сгенерируйте изображение или передайте путь target_image_path."
            ),
        }

    base_prompt = tracker.get_active_prompt()
    planner = EditPlanner(ai_client=None)
    plan = planner.plan(
        instruction=clean_instr,
        base_prompt=base_prompt,
        active_image_path=source_path,
        use_llm=False,
    )

    req_type = str(edit_type or "").strip().lower()
    eff_edit_type = (
        req_type
        if req_type not in ("", "general", "auto")
        else str(plan.action_type or req_type or "general").strip().lower()
    )
    has_mask_arg = bool((mask_path and str(mask_path).strip()) or mask_bbox is not None)
    if denoise is not None:
        try:
            max_denoise = 0.98 if has_mask_arg else 0.90
            eff_denoise = max(0.15, min(max_denoise, float(denoise)))
        except (TypeError, ValueError):
            eff_denoise = plan.denoise
    else:
        eff_denoise = plan.denoise

    eff_positive = plan.compiled_prompt
    has_custom_en_positive = False
    if positive_prompt and str(positive_prompt).strip():
        custom_pos = str(positive_prompt).strip()
        if not _CYRILLIC_RE.search(custom_pos):
            eff_positive = custom_pos
            has_custom_en_positive = True
        else:
            eff_positive = f"{custom_pos}, {plan.compiled_prompt}".strip(" ,")

    plan_neg_adds = ", ".join(getattr(plan, "negative_prompt_additions", []) or [])
    if has_custom_en_positive and has_mask_arg:
        if negative_prompt and str(negative_prompt).strip():
            if eff_edit_type == "replace" and plan_neg_adds:
                eff_negative = _merge_negative_prompts(negative_prompt, plan_neg_adds, BASE_NEGATIVE_PROMPT)
            else:
                eff_negative = _merge_negative_prompts(negative_prompt, BASE_NEGATIVE_PROMPT)
        else:
            eff_negative = _merge_negative_prompts(plan_neg_adds, BASE_NEGATIVE_PROMPT)
    else:
        eff_negative = _merge_negative_prompts(negative_prompt, plan.compiled_negative)

    clean_mask_path = str(mask_path).strip() if mask_path else None
    if clean_mask_path and not os.path.isfile(clean_mask_path):
        return {
            "success": False,
            "error": f"Файл маски не найден на диске: {clean_mask_path}",
        }

    norm_bbox: Optional[List[float]] = None
    if mask_bbox is not None and not clean_mask_path:
        src_w: Optional[int] = None
        src_h: Optional[int] = None
        try:
            from PIL import Image
            with Image.open(source_path) as im:
                src_w, src_h = im.size
        except Exception:
            pass
        norm_bbox = _normalize_bbox(mask_bbox, img_width=src_w, img_height=src_h)
        if norm_bbox is None:
            return {
                "success": False,
                "error": "Некорректные координаты mask_bbox: ожидается список [x1, y1, x2, y2] в диапазоне 0..1.",
            }

    try:
        eff_feather = max(0, min(128, int(feather)))
    except (TypeError, ValueError):
        eff_feather = 12

    if denoise is None and (clean_mask_path or norm_bbox is not None) and eff_edit_type in ("remove", "add", "replace", "general"):
        min_masked_denoise = 0.94 if eff_edit_type in ("replace", "remove") else 0.90
        eff_denoise = max(eff_denoise, min_masked_denoise)

    subagent_kwargs: Dict[str, Any] = {
        "action": "edit",
        "edit_type": eff_edit_type,
        "edit_instruction": clean_instr,
        "source_image_path": source_path,
        "negative_prompt": eff_negative,
        "denoise": eff_denoise,
        "what_to_change": plan.what_to_change,
        "what_to_keep": plan.what_to_keep,
        "skip_compile": True,
        "feather": eff_feather,
    }
    if clean_mask_path:
        subagent_kwargs["mask_path"] = clean_mask_path
    elif norm_bbox is not None:
        subagent_kwargs["mask_bbox"] = norm_bbox

    if control_type and str(control_type).strip():
        subagent_kwargs["control_type"] = str(control_type).strip().lower()
    if control_strength is not None:
        try:
            subagent_kwargs["control_strength"] = max(0.0, min(2.0, float(control_strength)))
        except (TypeError, ValueError):
            pass

    if tracker.active_image and isinstance(tracker.active_image.metadata, dict):
        w_meta = tracker.active_image.metadata.get("width")
        h_meta = tracker.active_image.metadata.get("height")
        if w_meta is not None:
            subagent_kwargs["width"] = w_meta
        if h_meta is not None:
            subagent_kwargs["height"] = h_meta

    sub_res = _run_image_subagent(agent, task=eff_positive, **subagent_kwargs)
    if not sub_res.success:
        err_msg = sub_res.error or sub_res.message or "Ошибка редактирования изображения."
        return {
            "success": False,
            "error": err_msg,
            "source_image_path": source_path,
            "created_files": [],
            "artifacts": [],
        }

    res_data = dict(getattr(sub_res, "data", {}) or {})
    if res_data.get("status") == "missing_model":
        return {
            "success": True,
            "status": "missing_model",
            "edit_type": res_data.get("edit_type", eff_edit_type),
            "missing_component": res_data.get("missing_component"),
            "alternatives": res_data.get("alternatives", []),
            "source_image_path": source_path,
            "active_image_path": source_path,
            "message": sub_res.message,
            "created_files": [],
            "artifacts": [],
        }

    artifacts_dicts = [a.to_dict() if hasattr(a, "to_dict") else a for a in sub_res.artifacts]
    created = list(sub_res.created_files)
    if created:
        tracker.track_edit(
            file_path=created[0],
            instruction=clean_instr,
            prompt=eff_positive,
            source_image_path=source_path,
            edit_type=eff_edit_type,
            width=res_data.get("width"),
            height=res_data.get("height"),
            denoise=eff_denoise,
        )
        _sync_agent_legacy_cache(agent, tracker, artifacts=artifacts_dicts, data=res_data)

    return {
        "success": True,
        "message": sub_res.message,
        "created_files": created,
        "artifacts": artifacts_dicts,
        "active_image_path": created[0] if created else source_path,
        "source_image_path": source_path,
        "edit_type": eff_edit_type,
        "edit_mode": res_data.get("edit_mode"),
        "mask_used": bool(res_data.get("mask_used", False)),
        "denoise": eff_denoise,
        "positive_prompt": res_data.get("positive_prompt", eff_positive),
        "negative_prompt": res_data.get("negative_prompt", eff_negative),
    }


def get_active_image() -> Dict[str, Any]:
    """
    Возвращает информацию о текущем активном изображении и истории правок в сессии.
    """
    agent = get_bound_image_agent()
    tracker = _resolve_context_tracker(agent)

    active_path = tracker.get_active_image_path(validate_disk=True)
    if not active_path:
        return {
            "success": True,
            "has_active_image": False,
            "active_image_path": None,
            "root_image_path": tracker.get_root_image_path(),
            "prompt": "",
            "width": None,
            "height": None,
            "history_count": len(tracker.history),
            "history": tracker.get_history_summary(),
            "message": "Активное изображение не выбрано.",
        }

    meta = dict(tracker.active_image.metadata) if tracker.active_image else {}
    width = meta.get("width")
    height = meta.get("height")
    if (width is None or height is None) and os.path.isfile(active_path):
        try:
            from PIL import Image
            with Image.open(active_path) as im:
                width, height = im.size
        except Exception:
            pass

    return {
        "success": True,
        "has_active_image": True,
        "active_image_path": active_path,
        "root_image_path": tracker.get_root_image_path(),
        "prompt": tracker.get_active_prompt(),
        "width": width,
        "height": height,
        "history_count": len(tracker.history),
        "history": tracker.get_history_summary(),
        "message": f"Активное изображение: {Path(active_path).name}",
    }


def select_image(file_path: str, prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Устанавливает указанный файл PNG как текущее активное изображение для последующих правок.
    """
    agent = get_bound_image_agent()
    tracker = _resolve_context_tracker(agent)

    ok, entry, msg = tracker.select_active_image(
        file_path=file_path,
        prompt=prompt,
        validate_disk=True,
    )
    if not ok or entry is None:
        return {
            "success": False,
            "error": msg,
        }

    _sync_agent_legacy_cache(agent, tracker)
    return {
        "success": True,
        "active_image_path": entry.file_path,
        "prompt": entry.prompt,
        "message": msg,
    }


def _normalize_bbox(
    raw_bbox: Any,
    img_width: Optional[int] = None,
    img_height: Optional[int] = None,
    prefer_scale_1000: bool = False,
) -> Optional[List[float]]:
    """
    Валидирует и нормализует bounding box в [x1, y1, x2, y2] (0.0 .. 1.0).
    Поддерживает шкалу 0..1, смешанный/полный формат 0..1000 (Qwen3-VL) и пиксельные координаты.
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
    # Значения до ~1.5 считаем лёгким выходом за [0..1] и просто зажимаем;
    # при > 1.5 различаем смешанную шкалу (0..1 + 0..1000), сетку 0..1000 и пиксели.
    if max_v > 1.5:
        has_unit_float = any(0.0 < abs(v) <= 1.0 for v in (x1, y1, x2, y2))
        if has_unit_float and max_v <= 1000.0:
            x1 = x1 if abs(x1) <= 1.5 else x1 / 1000.0
            y1 = y1 if abs(y1) <= 1.5 else y1 / 1000.0
            x2 = x2 if abs(x2) <= 1.5 else x2 / 1000.0
            y2 = y2 if abs(y2) <= 1.5 else y2 / 1000.0
        elif prefer_scale_1000 and max_v <= 1000.0:
            x1 /= 1000.0
            y1 /= 1000.0
            x2 /= 1000.0
            y2 /= 1000.0
        elif img_width and img_height and img_width > 0 and img_height > 0:
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

    return [round(left, 4), round(top, 4), round(right, 4), round(bottom, 4)]


def _parse_vision_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """Извлекает JSON-объект из ответа Vision-модели."""
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def inspect_image(
    question: str,
    image_path: Optional[str] = None,
    return_bbox: bool = False,
) -> Dict[str, Any]:
    """
    Анализирует содержимое активного или указанного PNG-изображения через локальную Vision-модель
    (`qwen3-vl:4b`), отвечает на вопрос и при return_bbox=True возвращает координаты области [x1, y1, x2, y2].
    """
    clean_q = str(question or "").strip()
    if not clean_q:
        return {
            "success": False,
            "error": "Не указан вопрос для инспекции изображения (question).",
        }

    agent = get_bound_image_agent()
    tracker = _resolve_context_tracker(agent)

    if image_path and str(image_path).strip():
        target_path = str(image_path).strip()
        if not os.path.isfile(target_path):
            return {
                "success": False,
                "error": f"Файл изображения не найден на диске: {target_path}",
            }
    else:
        target_path = tracker.get_active_image_path(validate_disk=True)
        if not target_path:
            return {
                "success": False,
                "error": (
                    "Нет активного изображения для инспекции. "
                    "Сначала сгенерируйте изображение или передайте путь image_path."
                ),
            }

    from infrastructure.ollama_manager import DEFAULT_VISION_MODEL, get_ollama_manager
    from ollama_client import OllamaClient
    from tools.settings import get_app_settings

    try:
        cfg_model = getattr(get_app_settings(), "vision_model", None)
    except Exception:
        cfg_model = None
    vision_model = (
        cfg_model.strip()
        if isinstance(cfg_model, str) and cfg_model.strip()
        else DEFAULT_VISION_MODEL
    )

    ollama_mgr = get_ollama_manager()
    avail, avail_msg = ollama_mgr.check_vision_model_available(vision_model)
    if not avail:
        return {
            "success": False,
            "error": avail_msg,
            "missing_vision_model": vision_model,
            "image_path": target_path,
        }

    img_width: Optional[int] = None
    img_height: Optional[int] = None
    try:
        from PIL import Image
        with Image.open(target_path) as im:
            img_width, img_height = im.size
    except Exception:
        pass

    bound_ai = getattr(agent, "ai", None) if agent is not None else None
    client = bound_ai if isinstance(bound_ai, OllamaClient) else OllamaClient()

    try:
        if return_bbox:
            vision_prompt = (
                "Analyze this image carefully and answer strictly based on what is actually visible.\n"
                "Return ONLY a JSON object with this schema:\n"
                "{\n"
                '  "answer": "concise factual answer in Russian",\n'
                '  "mask_bbox": [x1, y1, x2, y2],\n'
                '  "objects": [{"label": "object name", "bbox": [x1, y1, x2, y2]}]\n'
                "}\n"
                "Rules: use integer grid coordinates [0, 1000] for [left, top, right, bottom] "
                "(0 is left/top edge, 1000 is right/bottom edge) OR floats in [0.0, 1.0]; "
                "include at most 5 key objects in 'objects'; set 'mask_bbox': null if no target region applies.\n\n"
                f"Question: {clean_q}"
            )
            bbox_schema = {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "mask_bbox": {
                        "type": ["array", "null"],
                        "items": {"type": "number"},
                    },
                    "objects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "bbox": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                            },
                            "required": ["label", "bbox"],
                        },
                    },
                },
                "required": ["answer", "mask_bbox"],
            }
            res = client.send_vision_query(
                prompt=vision_prompt,
                images=target_path,
                model=vision_model,
                response_format=bbox_schema,
                think=False,
                options={"num_predict": 512, "temperature": 0.1},
            )
            raw_content = str(res.get("content", "")).strip()
            parsed = _parse_vision_json(raw_content)

            objects_clean: List[Dict[str, Any]] = []
            mask_bbox: Optional[List[float]] = None
            answer_text = raw_content

            if parsed:
                if isinstance(parsed.get("answer"), str) and parsed["answer"].strip():
                    answer_text = parsed["answer"].strip()
                raw_mask = parsed.get("mask_bbox")
                if raw_mask is None:
                    raw_mask = parsed.get("mask_bbox_1000")
                mask_bbox = _normalize_bbox(
                    raw_mask,
                    img_width,
                    img_height,
                    prefer_scale_1000=True,
                )
                raw_objs = parsed.get("objects")
                if isinstance(raw_objs, list):
                    for obj in raw_objs:
                        if not isinstance(obj, dict):
                            continue
                        raw_obj_bbox = obj.get("bbox")
                        if raw_obj_bbox is None:
                            raw_obj_bbox = obj.get("bbox_1000")
                        norm_obj_bbox = _normalize_bbox(
                            raw_obj_bbox,
                            img_width,
                            img_height,
                            prefer_scale_1000=True,
                        )
                        if norm_obj_bbox is not None:
                            objects_clean.append({
                                "label": str(obj.get("label") or "object"),
                                "bbox": norm_obj_bbox,
                            })
                    if mask_bbox is None and objects_clean:
                        mask_bbox = objects_clean[0]["bbox"]

            return {
                "success": True,
                "image_path": target_path,
                "vision_model": vision_model,
                "answer": answer_text or "Анализ изображения выполнен.",
                "width": img_width,
                "height": img_height,
                "objects": objects_clean,
                "mask_bbox": mask_bbox,
                "message": answer_text or "Анализ изображения выполнен.",
            }
        else:
            vision_prompt = (
                "Внимательно рассмотри изображение и ответь кратко и точно по-русски "
                "только по тому, что реально видно на картинке (предметы, цвета, количество, позы, фон и дефекты). "
                'Верни JSON формата {"answer": "..."}.\n\n'
                f"Вопрос: {clean_q}"
            )
            qa_schema = {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                },
                "required": ["answer"],
            }
            res = client.send_vision_query(
                prompt=vision_prompt,
                images=target_path,
                model=vision_model,
                response_format=qa_schema,
                think=False,
                options={"num_predict": 512, "temperature": 0.1},
            )
            raw_content = str(res.get("content", "")).strip()
            parsed = _parse_vision_json(raw_content)
            if parsed and isinstance(parsed.get("answer"), str) and parsed["answer"].strip():
                answer_text = parsed["answer"].strip()
            else:
                answer_text = raw_content
            if not answer_text:
                return {
                    "success": False,
                    "error": f"Vision-модель '{vision_model}' вернула пустой ответ.",
                    "image_path": target_path,
                }
            return {
                "success": True,
                "image_path": target_path,
                "vision_model": vision_model,
                "answer": answer_text,
                "width": img_width,
                "height": img_height,
                "objects": [],
                "mask_bbox": None,
                "message": answer_text,
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Ошибка при анализе изображения через Vision-модель '{vision_model}': {e}",
            "image_path": target_path,
            "vision_model": vision_model,
        }
