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
from tools.agents.result import AgentResult
from tools.agents.registry import (
    AgentRegistry,
    get_agent_registry,
    reset_agent_registry
)
from tools.agents.echo import EchoAgent

__all__ = [
    "SubAgent",
    "AgentContext",
    "AgentResult",
    "AgentRegistry",
    "get_agent_registry",
    "reset_agent_registry",
    "EchoAgent",
]
