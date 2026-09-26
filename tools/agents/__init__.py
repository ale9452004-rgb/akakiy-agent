"""
Пакет специализированных Sub-Agent'ов Акакия (Sub-Agents Architecture).

Экспортирует:
- SubAgent: базовый абстрактный класс специализированного агента;
- AgentContext: структурированный контекст задачи;
- AgentResult: стандартизированный результат выполнения;
- AgentRegistry, get_agent_registry, reset_agent_registry: реестр агентов;
- EchoAgent: эталонный тестовый Sub-Agent.
"""

from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult, Artifact, ArtifactType
from tools.agents.registry import (
    AgentRegistry,
    get_agent_registry,
    reset_agent_registry
)
from tools.agents.echo import EchoAgent
from tools.agents.image import (
    ImageAgent,
    ComfyUIClient,
    RESOLUTION_PRESETS,
    safe_validate_resolution,
    safe_validate_count
)
from tools.agents.presentation import PresentationAgent
from tools.agents.document import DocumentAgent
from tools.agents.research import ResearchAgent
from tools.agents.coding import CodingAgent
from tools.agents.file import FileAgent
from tools.vram import VRAMManager, get_vram_manager, reset_vram_manager

__all__ = [
    "SubAgent",
    "AgentContext",
    "AgentResult",
    "Artifact",
    "ArtifactType",
    "AgentRegistry",
    "get_agent_registry",
    "reset_agent_registry",
    "EchoAgent",
    "ImageAgent",
    "PresentationAgent",
    "DocumentAgent",
    "ResearchAgent",
    "CodingAgent",
    "FileAgent",
    "PipelineStep",
    "TeamworkPipeline",
    "run_agent_pipeline",
    "PlanStep",
    "TaskPlan",
    "Planner",
    "ComfyUIClient",
    "RESOLUTION_PRESETS",
    "safe_validate_resolution",
    "safe_validate_count",
    "VRAMManager",
    "get_vram_manager",
    "reset_vram_manager",
]


def __getattr__(name: str):
    """
    Ленивый импорт внешних компонентов (teamwork, planner)
    для предотвращения циклических зависимостей при прямой загрузке submodules.
    """
    if name in ("PipelineStep", "TeamworkPipeline", "run_agent_pipeline"):
        from tools.teamwork import (
            PipelineStep as _PS,
            TeamworkPipeline as _TP,
            run_agent_pipeline as _RAP,
        )
        globals()["PipelineStep"] = _PS
        globals()["TeamworkPipeline"] = _TP
        globals()["run_agent_pipeline"] = _RAP
        return globals()[name]

    if name in ("PlanStep", "TaskPlan", "Planner"):
        from tools.planner import (
            PlanStep as _PStep,
            TaskPlan as _TPlan,
            Planner as _Pln,
        )
        globals()["PlanStep"] = _PStep
        globals()["TaskPlan"] = _TPlan
        globals()["Planner"] = _Pln
        return globals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return __all__


