"""
Исполнитель доменных агентов (AgentExecutor) multi-agent архитектуры Акакия.

Целевая схема:
User Request
     |
     v
AgentRouter
     |
     v
RouteResult
     |
     v
AgentExecutor
     |
     v
BaseAgent.execute(...)
     |
     v
AgentResult

Принципы:
1. Open-Closed Principle (OCP): AgentExecutor не содержит жестких связей или импортов
   конкретных доменных агентов.
2. Универсальный интерфейс: принимает как результат маршрутизации (RouteResult),
   так и напрямую экземпляр BaseAgent.
3. Отказоустойчивость: перехватывает любые исключения во время выполнения агента
   и возвращает стандартизированный канонический AgentResult.fail, не допуская сбоя системы.
4. Прозрачность и сохранение данных: полностью сохраняет возвращенные агентом
   результаты, данные (data), артефакты (artifacts) и созданные файлы (created_files),
   добавляя метаданные маршрута для сквозной трассировки.
"""

import logging
from typing import Any, Dict, Optional, Union

from agents.base import BaseAgent
from agents.router import AgentRouter, RouteResult
from tools.agents.result import AgentResult

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    Единый исполнительный слой для доменных агентов Акакия.
    Обеспечивает валидацию маршрута, проверку доступности агента,
    безопасный вызов agent.execute(...) и возврат канонического AgentResult.
    """

    def __init__(self, router: Optional[AgentRouter] = None) -> None:
        """
        Инициализирует AgentExecutor.

        :param router: Экземпляр AgentRouter для автоматической маршрутизации
                       в методе execute_task. Если не передан, создается экземпляр по умолчанию.
        """
        self.router = router

    def _get_router(self) -> AgentRouter:
        """Возвращает внедренный или стандартный экземпляр AgentRouter."""
        if self.router is not None:
            return self.router
        return AgentRouter()

    def execute(
        self,
        route_or_agent: Union[RouteResult, BaseAgent],
        task: str = "",
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Выполняет задачу через переданный RouteResult или напрямую через BaseAgent.

        :param route_or_agent: Результат работы AgentRouter (RouteResult) либо экземпляр BaseAgent.
        :param task: Текст пользовательской задачи / запроса.
        :param context: Опциональный контекст сессии (память, профиль, настройки).
        :param kwargs: Дополнительные параметры для передачи в execute агента.
        :return: Канонический экземпляр AgentResult.
        """
        # 1. Валидация входного объекта route_or_agent
        if route_or_agent is None:
            return AgentResult.fail(
                error="Маршрут или агент не передан (None).",
                message="Невозможно выполнить задачу: объект маршрутизации не задан."
            )

        agent: Optional[BaseAgent] = None
        route_data: Optional[Dict[str, Any]] = None

        if isinstance(route_or_agent, RouteResult):
            route_data = route_or_agent.to_dict()

            # Проверка флага отключенного агента
            if route_or_agent.is_disabled:
                agent_name = route_or_agent.agent_name or "unknown"
                reason = route_or_agent.reason or f"Агент '{agent_name}' отключен."
                return AgentResult.fail(
                    error=f"Агент '{agent_name}' отключен.",
                    message=reason,
                    data={"route": route_data}
                )

            # Проверка успешности маршрутизации
            if not route_or_agent.success:
                reason = route_or_agent.reason or "Подходящий доменный агент не найден."
                return AgentResult.fail(
                    error="Маршрут не найден.",
                    message=reason,
                    data={"route": route_data}
                )

            # Проверка наличия агента в успешном маршруте
            agent = route_or_agent.agent
            if agent is None:
                return AgentResult.fail(
                    error="Маршрут помечен как успешный, но экземпляр агента отсутствует.",
                    message="Ошибка маршрутизации: агент не определен.",
                    data={"route": route_data}
                )

        elif isinstance(route_or_agent, BaseAgent):
            agent = route_or_agent

        else:
            return AgentResult.fail(
                error=f"Недопустимый тип объекта маршрутизации: '{type(route_or_agent).__name__}'. Ожидается RouteResult или BaseAgent.",
                message="Некорректный вызов исполнителя агентов."
            )

        # 2. Проверка валидности агента
        if not isinstance(agent, BaseAgent):
            return AgentResult.fail(
                error=f"Объект агента не реализует BaseAgent: '{type(agent).__name__}'.",
                message="Ошибка конфигурации агента.",
                data={"route": route_data} if route_data else {}
            )

        if not agent.enabled:
            return AgentResult.fail(
                error=f"Агент '{agent.name}' отключен.",
                message=f"Агент '{agent.name}' отключен и не может выполнять задачи.",
                data={"agent": agent.name, **({"route": route_data} if route_data else {})}
            )

        # 3. Валидация текста задачи
        if task is None or not isinstance(task, str) or not task.strip():
            return AgentResult.fail(
                error="Текст задачи не может быть пустым.",
                message="Получен пустой запрос для выполнения агентом.",
                data={"agent": agent.name, **({"route": route_data} if route_data else {})}
            )

        # 4. Вызов agent.execute(...) с перехватом любых исключений
        try:
            result = agent.execute(task=task, context=context, **kwargs)
        except Exception as exc:
            logger.exception("Исключение при выполнении агента '%s': %s", agent.name, exc)
            return AgentResult.fail(
                error=f"Ошибка выполнения агента '{agent.name}': {str(exc)}",
                message=f"Во время работы агента '{agent.name}' произошла ошибка: {str(exc)}",
                data={
                    "agent": agent.name,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    **({"route": route_data} if route_data else {})
                }
            )

        # 5. Проверка типа возвращенного результата
        if not isinstance(result, AgentResult):
            if isinstance(result, dict) and "success" in result:
                try:
                    result = AgentResult.from_dict(result)
                except Exception:
                    pass

        if not isinstance(result, AgentResult):
            return AgentResult.fail(
                error=f"Агент '{agent.name}' вернул некорректный тип результата: '{type(result).__name__}'. Ожидается AgentResult.",
                message=f"Агент '{agent.name}' вернул некорректный результат.",
                data={
                    "agent": agent.name,
                    "raw_result": str(result),
                    **({"route": route_data} if route_data else {})
                }
            )

        # 6. Обогащение данными маршрута (если есть и ключ еще не занят)
        if route_data and "route" not in result.data:
            result.data["route"] = route_data

        return result

    def execute_task(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Удобный метод сквозного выполнения полного цикла:
        пользовательский запрос -> AgentRouter.route -> AgentExecutor.execute -> AgentResult.

        :param task: Текст пользовательского запроса.
        :param context: Опциональный контекст выполнения.
        :param kwargs: Дополнительные параметры.
        :return: Канонический AgentResult.
        """
        router = self._get_router()
        route_result = router.route(task)
        return self.execute(
            route_or_agent=route_result,
            task=task,
            context=context,
            **kwargs
        )
