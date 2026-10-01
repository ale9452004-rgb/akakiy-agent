"""
Bootstrap-модуль автоматической регистрации стандартных доменных агентов.

Обеспечивает явную регистрацию базовых доменных агентов (HouseholdAgent, ResearchAgent)
в AgentRegistry, изолируя оркестратор (tools/agent.py) и фасад (agents/service.py)
от знания о конкретных реализациях доменных агентов.
"""

import logging
from typing import Optional

from agents.registry import AgentRegistry, get_agent_registry

logger = logging.getLogger(__name__)


def ensure_default_domain_agents(registry: Optional[AgentRegistry] = None) -> AgentRegistry:
    """
    Регистрирует базовых доменных агентов в реестре, если они еще не зарегистрированы.

    :param registry: Опциональный реестр. Если не передан, используется get_agent_registry().
    :return: Экземпляр реестра с зарегистрированными доменными агентами.
    """
    reg = registry if registry is not None else get_agent_registry()

    if not reg.has("household"):
        try:
            from agents.household import HouseholdAgent
            reg.register(HouseholdAgent())
        except Exception as exc:
            logger.warning("Не удалось зарегистрировать HouseholdAgent при bootstrap: %s", exc)

    if not reg.has("research"):
        try:
            from agents.research import ResearchAgent
            reg.register(ResearchAgent())
        except Exception as exc:
            logger.warning("Не удалось зарегистрировать ResearchAgent при bootstrap: %s", exc)

    if not reg.has("coding"):
        try:
            from agents.coding import CodingAgent
            reg.register(CodingAgent())
        except Exception as exc:
            logger.warning("Не удалось зарегистрировать CodingAgent при bootstrap: %s", exc)

    return reg
