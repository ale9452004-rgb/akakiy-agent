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

    def __init__(
        self,
        router: Optional[AgentRouter] = None,
        observer: Optional[Any] = None,
    ) -> None:
        """
        Инициализирует AgentExecutor.

        :param router: Экземпляр AgentRouter для автоматической маршрутизации
                       в методе execute_task. Если не передан, создается экземпляр по умолчанию.
        :param observer: Опциональный наблюдатель за событиями (observer(event_type, data)).
                         Если не задан, используется tools.dispatcher.get_action_observer.
        """
        self.router = router
        self._observer = observer

    def _get_router(self) -> AgentRouter:
        """Возвращает внедренный или стандартный экземпляр AgentRouter."""
        if self.router is not None:
            return self.router
        return AgentRouter()

    def _get_observer(self) -> Optional[Any]:
        """Возвращает внедренный или глобальный наблюдатель за действиями."""
        if hasattr(self, "_observer") and self._observer is not None:
            return self._observer
        try:
            from tools.dispatcher import get_action_observer
            return get_action_observer()
        except Exception:
            return None

    def execute(
        self,
        route_or_agent: Union[RouteResult, BaseAgent],
        task: str = "",
        context: Optional[Any] = None,
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

        # 4. Подготовка событий жизненного цикла агента
        obs = self._get_observer()
        agent_name = getattr(agent, "name", "unknown")
        display_name = getattr(agent, "display_name", "") or agent_name

        # Отправка события before_agent
        if obs:
            try:
                obs("before_agent", {
                    "agent": agent_name,
                    "display_name": display_name,
                    "task": task,
                })
            except Exception as obs_exc:
                logger.debug("Ошибка в action_observer before_agent: %s", obs_exc)

        # Сохранение исходного callback для восстановления в finally
        from agents.context import AgentContext

        original_callback = None
        has_orig_callback_attr = False

        if isinstance(context, AgentContext):
            exec_context = context
            original_callback = exec_context.progress_callback
            has_orig_callback_attr = True
        elif isinstance(context, dict):
            exec_context = AgentContext(task=task, metadata=context)
        elif context is None:
            exec_context = AgentContext(task=task)
        else:
            exec_context = context
            if hasattr(exec_context, "progress_callback"):
                original_callback = getattr(exec_context, "progress_callback")
                has_orig_callback_attr = True

        # Подготовка progress callback для Domain Agent
        def _on_progress(step: str, **extra: Any) -> None:
            current_obs = self._get_observer()
            if current_obs:
                try:
                    current_obs("agent_progress", {
                        "agent": agent_name,
                        "display_name": display_name,
                        "step": str(step),
                        "task": task,
                        **extra,
                    })
                except Exception as p_exc:
                    logger.debug("Ошибка в action_observer agent_progress: %s", p_exc)

            if original_callback and callable(original_callback):
                try:
                    original_callback(step, **extra)
                except Exception as orig_exc:
                    logger.debug("Ошибка в исходном progress_callback: %s", orig_exc)

        # Временно устанавливаем callback на время выполнения агента
        if hasattr(exec_context, "progress_callback"):
            try:
                exec_context.progress_callback = _on_progress
            except Exception:
                pass

        # 5. Вызов agent.execute(...) с перехватом любых исключений и гарантией очистки в finally
        try:
            try:
                result = agent.execute(task=task, context=exec_context, **kwargs)
            except Exception as exc:
                logger.exception("Исключение при выполнении агента '%s': %s", agent_name, exc)
                if obs:
                    try:
                        obs("after_agent", {
                            "agent": agent_name,
                            "display_name": display_name,
                            "task": task,
                            "success": False,
                            "error": str(exc),
                        })
                    except Exception as obs_exc:
                        logger.debug("Ошибка в action_observer after_agent (exception): %s", obs_exc)

                return AgentResult.fail(
                    error=f"Ошибка выполнения агента '{agent_name}': {str(exc)}",
                    message=f"Во время работы агента '{agent_name}' произошла ошибка: {str(exc)}",
                    data={
                        "agent": agent_name,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        **({"route": route_data} if route_data else {})
                    }
                )

            # 6. Проверка типа возвращенного результата
            if not isinstance(result, AgentResult):
                if isinstance(result, dict) and "success" in result:
                    try:
                        result = AgentResult.from_dict(result)
                    except Exception:
                        pass

            if not isinstance(result, AgentResult):
                fail_res = AgentResult.fail(
                    error=f"Агент '{agent_name}' вернул некорректный тип результата: '{type(result).__name__}'. Ожидается AgentResult.",
                    message=f"Агент '{agent_name}' вернул некорректный результат.",
                    data={
                        "agent": agent_name,
                        "raw_result": str(result),
                        **({"route": route_data} if route_data else {})
                    }
                )
                if obs:
                    try:
                        obs("after_agent", {
                            "agent": agent_name,
                            "display_name": display_name,
                            "task": task,
                            "success": False,
                            "error": fail_res.error,
                        })
                    except Exception as obs_exc:
                        logger.debug("Ошибка в action_observer after_agent: %s", obs_exc)
                return fail_res

            # 7. Обогащение данными маршрута (если есть и ключ еще не занят)
            if route_data and "route" not in result.data:
                result.data["route"] = route_data

            # 8. Отправка события after_agent
            if obs:
                try:
                    obs("after_agent", {
                        "agent": agent_name,
                        "display_name": display_name,
                        "task": task,
                        "success": bool(result.success),
                        **({"error": result.error} if not result.success and result.error else {}),
                    })
                except Exception as obs_exc:
                    logger.debug("Ошибка в action_observer after_agent: %s", obs_exc)

            return result
        finally:
            # Восстанавливаем исходный callback при любом исходе (успех, ошибка, исключение)
            if has_orig_callback_attr and hasattr(exec_context, "progress_callback"):
                try:
                    exec_context.progress_callback = original_callback
                except Exception:
                    pass

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
