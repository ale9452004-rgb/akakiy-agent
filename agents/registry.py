"""
Реестр агентов (AgentRegistry) multi-agent архитектуры Акакия.

Обеспечивает:
- явную, потокобезопасную регистрацию и управление жизненным циклом агентов;
- получение агента по имени с нормализацией регистра;
- выборку списка агентов (всех или только активных);
- поиск агентов по конкретной возможности (capability) или инструменту (tool);
- безопасное выполнение задач через агента с гарантированным возвратом AgentResult;
- полное отсутствие неявной глобальной магии и автопоиска, изоляцию в тестах через clear() и reset_agent_registry().
"""

import threading
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from tools.agents.result import AgentResult


class AgentRegistry:
    """
    Потокобезопасный реестр агентов multi-agent архитектуры.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}
        self._lock = threading.RLock()

    def _normalize_name(self, name: str) -> str:
        """Нормализует имя агента для регистронезависимого поиска."""
        return str(name).strip().lower()

    def register(self, agent: BaseAgent, override: bool = True) -> None:
        """
        Регистрирует агента в реестре.

        :param agent: Экземпляр класса, унаследованного от BaseAgent.
        :param override: Разрешить ли перезапись существующего агента с таким же именем.
        """
        if not isinstance(agent, BaseAgent):
            raise TypeError(
                f"Ожидается экземпляр BaseAgent, получен {type(agent).__name__}"
            )

        name = getattr(agent, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Агент обязан иметь непустое строковое имя (name).")

        key = self._normalize_name(name)

        with self._lock:
            if not override and key in self._agents:
                raise ValueError(f"Агент с именем '{name}' уже зарегистрирован в реестре.")
            self._agents[key] = agent

    def unregister(self, name: str) -> Optional[BaseAgent]:
        """
        Удаляет агента из реестра по имени.
        Возвращает удалённого агента или None, если агент не был найден.
        """
        key = self._normalize_name(name)
        with self._lock:
            return self._agents.pop(key, None)

    def get(self, name: str) -> Optional[BaseAgent]:
        """
        Возвращает зарегистрированного агента по имени или None.
        """
        key = self._normalize_name(name)
        with self._lock:
            return self._agents.get(key)

    def has(self, name: str) -> bool:
        """
        Проверяет наличие агента в реестре.
        """
        key = self._normalize_name(name)
        with self._lock:
            return key in self._agents

    def enable(self, name: str) -> bool:
        """
        Включает агента по имени. Возвращает True, если агент найден и включён.
        """
        with self._lock:
            agent = self.get(name)
            if agent is not None:
                agent.enabled = True
                return True
            return False

    def disable(self, name: str) -> bool:
        """
        Отключает агента по имени. Возвращает True, если агент найден и отключён.
        """
        with self._lock:
            agent = self.get(name)
            if agent is not None:
                agent.enabled = False
                return True
            return False

    def list_agents(self, enabled_only: bool = False) -> List[BaseAgent]:
        """
        Возвращает список зарегистрированных агентов.

        :param enabled_only: Если True, возвращаются только включённые (enabled) агенты.
        """
        with self._lock:
            if enabled_only:
                return [a for a in self._agents.values() if a.enabled]
            return list(self._agents.values())

    def find_by_capability(self, capability: str, enabled_only: bool = False) -> List[BaseAgent]:
        """
        Находит всех агентов, обладающих указанной возможностью (capability).
        """
        clean_cap = str(capability).strip().lower()
        with self._lock:
            return [
                a for a in self._agents.values()
                if a.has_capability(clean_cap) and (not enabled_only or a.enabled)
            ]

    def find_by_tool(self, tool_name: str, enabled_only: bool = False) -> List[BaseAgent]:
        """
        Находит всех агентов, к которым привязан указанный инструмент.
        """
        clean_tool = str(tool_name).strip().lower()
        with self._lock:
            return [
                a for a in self._agents.values()
                if a.has_tool(clean_tool) and (not enabled_only or a.enabled)
            ]

    def execute(
        self,
        agent_name: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Безопасно маршрутизирует выполнение задачи через агента по его имени.

        :param agent_name: Имя агента в реестре.
        :param task: Текст задачи.
        :param context: Контекст задачи.
        :return: AgentResult (в случае ошибки возвращается AgentResult.fail).
        """
        agent = self.get(agent_name)
        if agent is None:
            return AgentResult.fail(
                error=f"Агент '{agent_name}' не найден в AgentRegistry.",
                message=f"Ошибка маршрутизации: агент '{agent_name}' отсутствует в системе."
            )

        if not agent.enabled:
            return AgentResult.fail(
                error=f"Агент '{agent.name}' отключен.",
                message=f"Агент '{agent.name}' в данный момент неактивен."
            )

        try:
            return agent.execute(task=task, context=context, **kwargs)
        except Exception as ex:
            return AgentResult.fail(
                error=f"Исключение при выполнении агента '{agent.name}': {ex}",
                message=f"Сбой выполнения агента '{agent.name}': {ex}"
            )

    def clear(self) -> None:
        """
        Полностью очищает реестр (для изоляции в тестах).
        """
        with self._lock:
            self._agents.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __repr__(self) -> str:
        with self._lock:
            names = list(self._agents.keys())
            return f"<AgentRegistry count={len(names)} agents={names}>"


# Синглтон-хранилище (при необходимости совместного использования)
_global_registry: Optional[AgentRegistry] = None
_global_registry_lock = threading.RLock()


def get_agent_registry() -> AgentRegistry:
    """
    Возвращает экземпляр глобального реестра агентов без скрытых автозагрузок.
    """
    global _global_registry
    with _global_registry_lock:
        if _global_registry is None:
            _global_registry = AgentRegistry()
        return _global_registry


def reset_agent_registry() -> None:
    """
    Сбрасывает глобальный экземпляр реестра агентов (для изоляции в тестах).
    """
    global _global_registry
    with _global_registry_lock:
        if _global_registry is not None:
            _global_registry.clear()
            _global_registry = None
