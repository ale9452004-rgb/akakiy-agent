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

    eff_edit_type = str(edit_type or plan.action_type or "general").strip().lower()
    if denoise is not None:
        try:
            eff_denoise = max(0.15, min(0.90, float(denoise)))
        except (TypeError, ValueError):
            eff_denoise = plan.denoise
    else:
        eff_denoise = plan.denoise

    eff_positive = plan.compiled_prompt
    if positive_prompt and str(positive_prompt).strip():
        custom_pos = str(positive_prompt).strip()
        if not _CYRILLIC_RE.search(custom_pos):
            eff_positive = custom_pos
        else:
            eff_positive = f"{custom_pos}, {plan.compiled_prompt}".strip(" ,")

    eff_negative = _merge_negative_prompts(negative_prompt, plan.compiled_negative)

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
    }
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
