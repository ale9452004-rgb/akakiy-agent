"""
Пакет multi-agent архитектуры персонального ассистента Акакий.

Обеспечивает фундамент для специализированных агентов:
- Household Agent (бытовые дела, напоминания, списки);
- Research Agent (поиск, аналитика, документация);
- Coding Agent (анализ, рефакторинг и исполнение кода);
- Memory Agent (долговременная память, профиль пользователя, факты).
"""

from agents.base import BaseAgent
from agents.registry import AgentRegistry, get_agent_registry, reset_agent_registry
from agents.household import HouseholdAgent
from agents.research import ResearchAgent
from agents.router import AgentRouter, RouteResult
from agents.executor import AgentExecutor
from agents.service import AgentService, get_agent_service, reset_agent_service
from agents.bridge import MultiAgentBridge
from agents.bootstrap import ensure_default_domain_agents

__all__ = [
    "BaseAgent",
    "AgentRegistry",
    "get_agent_registry",
    "reset_agent_registry",
    "HouseholdAgent",
    "ResearchAgent",
    "AgentRouter",
    "RouteResult",
    "AgentExecutor",
    "AgentService",
    "get_agent_service",
    "reset_agent_service",
    "MultiAgentBridge",
    "ensure_default_domain_agents",
]



