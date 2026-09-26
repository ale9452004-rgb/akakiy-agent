"""
Реестр специализированных Sub-Agent'ов (AgentRegistry) Акакия.

Обеспечивает:
- потокобезопасную регистрацию, отмену регистрации и поиск sub-agent'ов;
- включение и отключение агентов на лету без изменения ядра системы;
- синглтон-доступ и автозагрузку встроенных агентов (EchoAgent);
- возможность сброса реестра для изоляции тестов.
"""

import threading
from typing import Dict, List, Optional

from tools.agents.base import SubAgent


class AgentRegistry:
    """
    Потокобезопасный реестр Sub-Agent'ов.
    """

    def __init__(self):
        self._agents: Dict[str, SubAgent] = {}
        self._lock = threading.RLock()

    def register(self, agent: SubAgent) -> None:
        """
        Регистрирует SubAgent в реестре.
        """
        if not isinstance(agent, SubAgent):
            raise TypeError(f"Ожидается экземпляр SubAgent, получен {type(agent)}")

        name = getattr(agent, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("SubAgent обязан иметь непустое строковое имя (name).")

        name = name.strip()

        with self._lock:
            self._agents[name] = agent

    def unregister(self, name: str) -> Optional[SubAgent]:
        """
        Удаляет SubAgent из реестра по имени.
        """
        with self._lock:
            return self._agents.pop(str(name).strip(), None)

    def get(self, name: str) -> Optional[SubAgent]:
        """
        Возвращает SubAgent по имени или None.
        """
        with self._lock:
            return self._agents.get(str(name).strip())

    def has(self, name: str) -> bool:
        """
        Проверяет наличие агента в реестре.
        """
        with self._lock:
            return str(name).strip() in self._agents

    def enable(self, name: str) -> bool:
        """
        Включает SubAgent по имени.
        """
        with self._lock:
            agent = self._agents.get(str(name).strip())
            if agent is not None:
                agent.enabled = True
                return True
            return False

    def disable(self, name: str) -> bool:
        """
        Отключает SubAgent по имени.
        """
        with self._lock:
            agent = self._agents.get(str(name).strip())
            if agent is not None:
                agent.enabled = False
                return True
            return False

    def list_agents(self, enabled_only: bool = True) -> List[SubAgent]:
        """
        Возвращает список зарегистрированных агентов.
        """
        with self._lock:
            if enabled_only:
                return [a for a in self._agents.values() if a.enabled]
            return list(self._agents.values())

    def get_all(self, enabled_only: bool = True) -> List[SubAgent]:
        """
        Алиас для list_agents (единообразие с SkillRegistry).
        """
        return self.list_agents(enabled_only=enabled_only)

    def clear(self) -> None:
        """
        Очищает реестр агентов.
        """
        with self._lock:
            self._agents.clear()


_registry_instance: Optional[AgentRegistry] = None
_registry_lock = threading.RLock()


def _init_default_registry() -> AgentRegistry:
    """Создаёт реестр и регистрирует стандартных агентов."""
    from tools.agents.echo import EchoAgent
    from tools.agents.image import ImageAgent
    from tools.agents.presentation import PresentationAgent
    from tools.agents.document import DocumentAgent

    reg = AgentRegistry()
    reg.register(EchoAgent())
    reg.register(ImageAgent())
    reg.register(PresentationAgent())
    reg.register(DocumentAgent())
    return reg


def get_agent_registry() -> AgentRegistry:
    """
    Возвращает глобальный синглтон AgentRegistry с инициализированными встроенными агентами.
    """
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = _init_default_registry()
        return _registry_instance


def reset_agent_registry() -> None:
    """
    Сбрасывает синглтон реестра агентов (используется для изоляции в тестах).
    """
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
