"""
Базовый интерфейс и абстрактный контракт агентов (BaseAgent) для multi-agent архитектуры Акакия.

Концепция:
Akakiy Agent Core
       │
       ↓
  Agent Registry
       │
       ├── Household Agent  (бытовые задачи, списки, напоминания)
       ├── Research Agent   (сбор информации, поиск, анализ)
       ├── Coding Agent     (анализ и модификация кода, терминал)
       └── Memory Agent     (долговременная память, факты, предпочтения)

Каждый агент:
- имеет имя (name), описание (description), список возможностей (capabilities) и список инструментов (tools);
- реализует универсальный метод execute(task, context=..., **kwargs);
- возвращает стандартизированный AgentResult (успех, сообщение, данные, ошибки, артефакты);
- является изолированной единицей логики, регистрируемой в AgentRegistry.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from tools.agents.result import AgentResult


class BaseAgent(ABC):
    """
    Базовый абстрактный класс специализированного агента Акакия.
    Определяет единый интерфейс взаимодействия, метаданные и контракт выполнения.
    """

    name: str = ""
    description: str = ""
    capabilities: List[str] = []
    tools: List[str] = []
    enabled: bool = True

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        enabled: bool = True,
        **kwargs: Any
    ):
        if name is not None:
            self.name = str(name).strip()
        if description is not None:
            self.description = str(description).strip()

        # Инициализация списков с защитой от изменения общих классовых атрибутов
        if capabilities is not None:
            self.capabilities = [str(c).strip().lower() for c in capabilities]
        else:
            self.capabilities = [str(c).strip().lower() for c in self.capabilities]

        if tools is not None:
            self.tools = [str(t).strip() for t in tools]
        else:
            self.tools = [str(t).strip() for t in self.tools]

        self.enabled = bool(enabled)
        self.metadata: Dict[str, Any] = dict(kwargs)

    @abstractmethod
    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Основная точка входа для выполнения задачи агентом.

        :param task: Текстовое описание задачи или запрос пользователя.
        :param context: Опциональный контекст выполнения (данные сессии, память, настройки).
        :param kwargs: Дополнительные специфические параметры задачи.
        :return: Экземпляр AgentResult (success, message, data, created_files, artifacts, error).
        """
        raise NotImplementedError("Каждый агент обязан реализовать метод execute(task, context=...).")

    def has_capability(self, capability: str) -> bool:
        """
        Проверяет, поддерживает ли агент указанную возможность (capability).
        Поиск нечувствителен к регистру и концевым пробелам.
        """
        if not capability:
            return False
        clean_cap = str(capability).strip().lower()
        return clean_cap in self.capabilities

    def has_tool(self, tool_name: str) -> bool:
        """
        Проверяет, привязан ли к агенту указанный инструмент.
        Поиск нечувствителен к регистру и концевым пробелам.
        """
        if not tool_name:
            return False
        clean_tool = str(tool_name).strip().lower()
        return any(t.lower() == clean_tool for t in self.tools)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует спецификацию агента в словарь метаданных."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "enabled": self.enabled,
            "metadata": dict(self.metadata)
        }

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        caps_str = ", ".join(self.capabilities) if self.capabilities else "none"
        tools_str = ", ".join(self.tools) if self.tools else "none"
        return (
            f"<Agent '{self.name}' caps=[{caps_str}] "
            f"tools=[{tools_str}] [{status}]>"
        )
