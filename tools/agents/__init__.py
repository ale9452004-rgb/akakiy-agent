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
    "ComfyUIClient",
    "RESOLUTION_PRESETS",
    "safe_validate_resolution",
    "safe_validate_count",
    "VRAMManager",
    "get_vram_manager",
    "reset_vram_manager",
]

