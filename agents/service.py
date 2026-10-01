"""
Сервисный слой multi-agent архитектуры Акакия (AgentService).

Целевая схема:
User Request / Caller
         │
         ▼
    AgentService
         │
         ├─► route(task) / preview_route(task) ──► AgentRouter ──► RouteResult
         │
         └─► execute(task, context, **kwargs)
                 │
                 ▼
             AgentRouter ──► RouteResult
                 │
                 ▼
            AgentExecutor ──► BaseAgent.execute(...) ──► AgentResult

Принципы:
1. Единая высокоуровневая точка входа для взаимодействия с multi-agent системой.
2. Open-Closed Principle (OCP): AgentService не импортирует и ничего не знает о конкретных
   доменных агентах. Вся маршрутизация и исполнение происходят через абстракции.
3. Отсутствие дублирования логики: сервис делегирует выбор агента в AgentRouter,
   а проверку, безопасное исполнение и перехват исключений — в AgentExecutor.
4. Возможность инспекции: поддержка предварительного просмотра маршрута до исполнения
   через методы route() и preview_route().
5. Поддержка Dependency Injection: явная передача router, executor и registry
   с автоматическим использованием проектных синглтонов по умолчанию.
"""

import logging
import threading
from typing import Any, Dict, Optional

from agents.base import BaseAgent
from agents.executor import AgentExecutor
from agents.registry import AgentRegistry, get_agent_registry
from agents.router import AgentRouter, RouteResult
from tools.agents.result import AgentResult

logger = logging.getLogger(__name__)


class AgentService:
    """
    Фасадный сервис multi-agent архитектуры.
    Объединяет AgentRouter и AgentExecutor в единую точку входа.
    """

    def __init__(
        self,
        router: Optional[AgentRouter] = None,
        executor: Optional[AgentExecutor] = None,
        registry: Optional[AgentRegistry] = None,
    ) -> None:
        """
        Инициализирует AgentService.

        :param router: Экземпляр AgentRouter. Если не задан, создается с привязкой к registry.
        :param executor: Экземпляр AgentExecutor. Если не задан, создается с привязкой к router.
        :param registry: Экземпляр AgentRegistry. Если не задан, используется глобальный реестр.
        """
        if registry is not None:
            self.registry = registry
        elif router is not None and getattr(router, "registry", None) is not None:
            self.registry = router.registry
        else:
            self.registry = get_agent_registry()

        if router is not None:
            self.router = router
        else:
            self.router = AgentRouter(registry=self.registry)

        if executor is not None:
            self.executor = executor
        else:
            self.executor = AgentExecutor(router=self.router)

    def route(self, task: str) -> RouteResult:
        """
        Определяет целевого агента для задачи без её фактического выполнения.

        :param task: Текст пользовательского запроса.
        :return: RouteResult с информацией о выбранном агенте или причине отказа.
        """
        if task is None or not isinstance(task, str) or not task.strip():
            return RouteResult.no_match(reason="Получен пустой запрос для маршрутизации.")
        return self.router.route(task)

    def preview_route(self, task: str) -> RouteResult:
        """
        Алиас метода route для явного предварительного просмотра маршрутизации.
        """
        return self.route(task)

    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Выполняет полный цикл обработки задачи:
        валидация -> маршрутизация -> безопасное исполнение -> возврат канонического AgentResult.

        :param task: Текст пользовательского запроса.
        :param context: Опциональный контекст выполнения.
        :param kwargs: Дополнительные параметры для агента.
        :return: Канонический экземпляр AgentResult.
        """
        # 1. Структурированная валидация входного запроса
        if task is None or not isinstance(task, str) or not task.strip():
            return AgentResult.fail(
                error="Текст задачи не может быть пустым.",
                message="Получен пустой запрос для сервиса агентов."
            )

        try:
            # 2. Определение маршрута через AgentRouter
            route_result = self.route(task)

            # 3. Делегирование исполнения в AgentExecutor
            return self.executor.execute(
                route_or_agent=route_result,
                task=task,
                context=context,
                **kwargs
            )
        except Exception as exc:
            logger.exception("Непредвиденная ошибка в AgentService: %s", exc)
            return AgentResult.fail(
                error=f"Ошибка сервиса агентов ({type(exc).__name__}): {exc}",
                message=f"Во время обработки задачи в AgentService произошла ошибка: {exc}",
                data={"exception_type": type(exc).__name__, "exception_message": str(exc)}
            )

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает информацию о текущем состоянии и конфигурации сервиса."""
        registered_agents = []
        if self.registry is not None:
            registered_agents = [
                {"name": a.name, "enabled": a.enabled, "capabilities": a.capabilities}
                for a in self.registry.list_agents(enabled_only=False)
            ]

        return {
            "service": "AgentService",
            "has_router": self.router is not None,
            "has_executor": self.executor is not None,
            "registered_agents_count": len(registered_agents),
            "registered_agents": registered_agents,
        }

    def __repr__(self) -> str:
        count = len(self.registry) if self.registry is not None else 0
        return f"<AgentService registry_agents={count}>"


# =============================================================================
# Глобальное синглтон-управление для сервиса
# =============================================================================

_global_service: Optional[AgentService] = None
_global_service_lock = threading.RLock()


def get_agent_service() -> AgentService:
    """
    Возвращает синглтон-экземпляр AgentService.
    При первом обращении лениво инициализирует сервис со стандартным окружением.
    """
    global _global_service
    with _global_service_lock:
        if _global_service is None:
            _global_service = AgentService()
        return _global_service


def reset_agent_service() -> None:
    """
    Сбрасывает синглтон-экземпляр AgentService (используется для изоляции в тестах).
    """
    global _global_service
    with _global_service_lock:
        _global_service = None
