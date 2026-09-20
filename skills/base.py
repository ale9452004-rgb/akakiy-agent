"""
Базовый класс и контракт для системы Skills (Навыков) Акакия.

Навыки представляют собой модульные расширения возможностей ассистента:
- не создают собственных клиентов LLM (OllamaClient);
- не создают отдельной истории сообщений;
- используют существующие инструменты из tools.registry;
- не обходят механизмы безопасности (Dispatcher, confirmation, validation);
- могут подключаться и отключаться динамически.
"""

from typing import Any, Dict, List, Optional
from tools.registry import get_tools_schema


class BaseSkill:
    """
    Базовый контракт навыка Акакия.
    """

    name: str = ""
    description: str = ""
    tools: List[str] = []
    system_prompt: Optional[str] = None
    enabled: bool = True

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        enabled: bool = True
    ):
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if tools is not None:
            self.tools = list(tools)
        else:
            self.tools = list(self.tools)
        if system_prompt is not None:
            self.system_prompt = system_prompt
        self.enabled = enabled

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Возвращает OpenAPI/Ollama схемы инструментов, объявленных данным навыком.
        Схемы извлекаются напрямую из tools.registry.TOOLS без дублирования.
        """
        return get_tools_schema(self.tools)

    def matches(self, user_input: str) -> bool:
        """
        Определяет, относится ли запрос пользователя к данному навыку детерминированно.
        Переопределяется в конкретных подклассах навыков.
        """
        return False

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return f"<Skill name='{self.name}' tools={self.tools} [{status}]>"
