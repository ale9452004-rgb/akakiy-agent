"""
Модуль тестового эталонного Sub-Agent'а (EchoAgent).

Служит для безопасного тестирования инфраструктуры sub-agent'ов:
- проверки жизненного цикла передачи контекста;
- верификации возврата успешных и ошибочных AgentResult;
- эмулирования генерации файлов через mock_files.
"""

from typing import List, Optional

from tools.agents.base import SubAgent
from tools.agents.context import AgentContext
from tools.agents.result import AgentResult


class EchoAgent(SubAgent):
    """
    Тестовый SubAgent, возвращающий диагностическое эхо задачи и метаданных.
    """

    name: str = "echo"
    description: str = "Тестовый sub-agent, возвращающий эхо задачи и метаданных контекста."
    capabilities: List[str] = ["echo", "test", "diagnostic"]

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        enabled: bool = True
    ):
        super().__init__(
            name=name or self.name,
            description=description or self.description,
            capabilities=capabilities or self.capabilities,
            enabled=enabled
        )

    def run(self, context: AgentContext) -> AgentResult:
        """
        Выполняет эхо-обработку задачи.
        """
        if not self.validate_context(context):
            return AgentResult.fail(
                error="Некорректный контекст: ожидается экземпляр AgentContext."
            )

        if not self.enabled:
            return AgentResult.fail(
                error=f"Sub-agent '{self.name}' отключен."
            )

        # Поддержка эмуляции ошибки для тестирования сбойных сценариев
        should_fail = (
            bool(context.get("fail"))
            or "simulate_error" in context.task.lower()
        )
        if should_fail:
            error_text = str(context.get("error_text") or "Симуляция ошибки в EchoAgent.")
            return AgentResult.fail(
                error=error_text,
                message=f"EchoAgent завершился с ошибкой: {error_text}",
                data={
                    "echo_task": context.task,
                    "echo_metadata": context.metadata
                }
            )

        # Поддержка эмуляции созданных файлов
        mock_files = context.get("mock_files") or []
        if isinstance(mock_files, (list, tuple)):
            created_files = [str(f) for f in mock_files]
        else:
            created_files = [str(mock_files)]

        msg = f"EchoAgent успешно обработал задачу: {context.task}" if context.task else "EchoAgent успешно завершил работу."

        return AgentResult.ok(
            message=msg,
            created_files=created_files,
            data={
                "echo_task": context.task,
                "echo_files": list(context.files),
                "echo_metadata": dict(context.metadata),
                "previous_results_count": len(context.previous_results)
            }
        )
