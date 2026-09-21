"""
Базовый класс и контракт специализированных Sub-Agent'ов (SubAgent) Акакия.

Sub-Agent представляет собой автономного специализированного исполнителя:
- принимает изолированный AgentContext (задача, файлы, метаданные, результаты предыдущих шагов);
- выполняет специализированную работу (может анализировать код, генерировать артефакты, производить файлы);
- возвращает стандартизированный AgentResult (success, message, created_files, data, error);
- не нарушает существующие инструменты, роутинг или навыки;
- может подключаться и отключаться через AgentRegistry.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from tools.agents.context import AgentContext
from tools.agents.result import AgentResult


class SubAgent(ABC):
    """
    Базовый абстрактный контракт специализированного Sub-Agent'а.
    """

    name: str = ""
    description: str = ""
    capabilities: List[str] = []
    enabled: bool = True

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        enabled: bool = True
    ):
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if capabilities is not None:
            self.capabilities = list(capabilities)
        else:
            self.capabilities = list(self.capabilities)
        self.enabled = enabled

    def validate_context(self, context: AgentContext) -> bool:
        """
        Проверяет пригодность входного контекста перед запуском.
        По умолчанию проверяет, что передан экземпляр AgentContext.
        Может быть переопределен в конкретных агентах.
        """
        return isinstance(context, AgentContext)

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult:
        """
        Основной метод выполнения специализированной задачи.

        Должен возвращать стандартизированный AgentResult.
        """
        raise NotImplementedError("SubAgent обязан реализовать метод run(context).")

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"<SubAgent name='{self.name}' capabilities={self.capabilities} [{status}]>"
