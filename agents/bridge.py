"""
Безопасный переходный слой (MultiAgentBridge) для multi-agent архитектуры Акакия.

Обеспечивает контролируемую интеграцию между монолитным Agent.process()
и новой multi-agent архитектурой (AgentService / AgentRouter / AgentExecutor):

           Agent.process(user_input)
                       │
                       ▼
              CommandRouter.route() ──► legacy_route
                       │
                       ▼
              MultiAgentBridge.try_process()
                       │
        ┌──────────────┴──────────────┐
        │                             │
    [Bypass / no-match]         [Domain Match]
        │                             │
        ▼                             ▼
   return None                  AgentService.execute()
   (продолжить старый                 │
    legacy-конвейер)                  ▼
                                 AgentResult
                                      │
                                      ▼
                                adapt_result()
                                      │
                                      ▼
                           return canonical dict

Принципы:
1. Open-Closed Principle (OCP): Bridge не содержит знаний или импортов конкретных
   доменных агентов (всё взаимодействие строго через AgentService и AgentResult).
2. Защита legacy pipeline: системные команды памяти, планов, медиа-воркеров и CLI-инструментов
   проекта отсекаются в $O(1)$ без обращения к AgentRouter.
3. Отказоустойчивость: любые исключения перехватываются внутри моста, не допуская падения
   вызывающего кода (GUI, CLI, Voice).
4. Канонический контракт: результат адаптируется в 100% совместимый словарь Agent.process().
"""

import logging
from typing import Any, Dict, Optional, Set

from agents.router import RouteResult
from agents.service import AgentService, get_agent_service
from tools.agents.result import AgentResult

logger = logging.getLogger(__name__)

# Категории маршрутов CommandRouter, которые безусловно пропускаются в старый pipeline
DEFAULT_BYPASS_ROUTE_TYPES: Set[str] = {
    "memory",
    "plan",
    "subagent",
    "image",
    "presentation",
    "document",
    "coding",
    "file",
}

# Инструменты проекта, которые безусловно пропускаются в старый pipeline
DEFAULT_BYPASS_TOOLS: Set[str] = {
    "list_files",
    "find_file",
    "structure",
    "search_files",
}


class CompatibleType(str):
    """Строковый тип ответа, совместимый с проверками на legacy 'tool'."""

    def __eq__(self, other: Any) -> bool:
        if super().__eq__(other):
            return True
        if other == "tool" and super().__eq__("tasks"):
            return True
        if other == "tool" and super().__eq__("notes"):
            return True
        if other == "tool" and super().__eq__("reminders"):
            return True
        if other == "tool" and super().__eq__("lists"):
            return True
        if other == "tool" and super().__eq__("household"):
            return True
        return False

    def __hash__(self) -> int:
        return super().__hash__()


class MultiAgentBridge:
    """
    Безопасный мост между вызовом Agent.process() и доменными агентами AgentService.
    """

    def __init__(
        self,
        service: Optional[AgentService] = None,
        bypass_route_types: Optional[Set[str]] = None,
        bypass_tools: Optional[Set[str]] = None,
        fallback_on_disabled: bool = False,
    ) -> None:
        """
        Инициализирует MultiAgentBridge.

        :param service: Экземпляр AgentService. Если не задан, используется глобальный синглтон.
        :param bypass_route_types: Набор типов маршрутов legacy_route для безусловного пропуска.
        :param bypass_tools: Набор инструментов legacy_route для безусловного пропуска.
        :param fallback_on_disabled: При True отключает перехват для disabled агентов (пропуск в fallback).
        """
        self.service = service if service is not None else get_agent_service()

        if bypass_route_types is not None:
            self.bypass_route_types = {str(t).strip().lower() for t in bypass_route_types if t}
        else:
            self.bypass_route_types = set(DEFAULT_BYPASS_ROUTE_TYPES)

        if bypass_tools is not None:
            self.bypass_tools = {str(t).strip().lower() for t in bypass_tools if t}
        else:
            self.bypass_tools = set(DEFAULT_BYPASS_TOOLS)

        self.fallback_on_disabled = bool(fallback_on_disabled)

    def _is_bypassed(self, legacy_route: Optional[Dict[str, Any]]) -> bool:
        """
        Проверяет за O(1), подлежит ли запрос безусловному пропуску в старый pipeline
        на основе результатов предварительной классификации CommandRouter.
        """
        if not legacy_route or not isinstance(legacy_route, dict):
            return False

        r_type = legacy_route.get("type")
        if r_type and str(r_type).strip().lower() in self.bypass_route_types:
            return True

        r_tool = legacy_route.get("tool")
        if r_tool and str(r_tool).strip().lower() in self.bypass_tools:
            return True

        return False

    def can_handle(
        self,
        user_input: str,
        legacy_route: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Проверяет, должен ли запрос быть обработан multi-agent системой.

        :param user_input: Пользовательский ввод.
        :param legacy_route: Предварительное решение CommandRouter.route() (если есть).
        :return: True, если запрос адресован активному доменному агенту и не находится в bypass.
        """
        if user_input is None or not isinstance(user_input, str) or not user_input.strip():
            return False

        # 1. Защищенные категории старого pipeline пропускаются без вызова AgentRouter
        if self._is_bypassed(legacy_route):
            return False

        try:
            # 2. Инспекция маршрута через AgentService
            preview = self.service.preview_route(user_input)
            if preview.success:
                return True
            if preview.is_disabled:
                return not self.fallback_on_disabled
            return False
        except Exception as exc:
            logger.exception("Ошибка при вызове can_handle в MultiAgentBridge: %s", exc)
            return False

    def try_process(
        self,
        user_input: str,
        legacy_route: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Основная точка интеграции моста.

        Алгоритм:
        1. Проверка на пустой/некорректный ввод -> возврат None (делегирование в Agent.process).
        2. Проверка на bypass_route_types и bypass_tools -> мгновенный возврат None (без AgentRouter).
        3. Проверка preview_route() в AgentService:
           - если no-match -> возврат None;
           - если disabled -> возврат ошибки или None при fallback_on_disabled;
           - если match -> выполнение через AgentService.execute() и возврат канонического словаря.
        4. Полный перехват любых исключений.

        :param user_input: Пользовательский запрос.
        :param legacy_route: Словарь решения CommandRouter.route().
        :param context: Опциональный контекст выполнения.
        :param kwargs: Дополнительные параметры.
        :return: Совместимый словарь ответа Agent.process() либо None.
        """
        # 1. Пустые и некорректные запросы передаются штатному обработчику Agent.process
        if user_input is None or not isinstance(user_input, str) or not user_input.strip():
            return None

        # 2. Мгновенный пропуск защищенных категорий старого pipeline без вызова AgentRouter
        if self._is_bypassed(legacy_route):
            return None

        try:
            # 3. Предварительный просмотр маршрута
            preview = self.service.preview_route(user_input)

            # Обработка отключенного агента
            if preview.is_disabled:
                if self.fallback_on_disabled:
                    return None
                agent_name = preview.agent_name or "доменный агент"
                fail_result = AgentResult.fail(
                    error=f"Агент '{agent_name}' отключен.",
                    message=preview.reason or f"Агент '{agent_name}' отключен.",
                    data={"route": preview.to_dict()}
                )
                return self.adapt_result(fail_result, route_result=preview, legacy_route=legacy_route)

            # Если подходящий доменный агент не найден -> пропускаем в legacy-пайплайн
            if not preview.success:
                return None

            # 4. Выполнение через AgentService
            result = self.service.execute(
                task=user_input,
                context=context,
                **kwargs
            )
            return self.adapt_result(result, route_result=preview, legacy_route=legacy_route)

        except Exception as exc:
            logger.exception("Исключение в MultiAgentBridge.try_process: %s", exc)
            fail_result = AgentResult.fail(
                error=f"Ошибка выполнения моста multi-agent ({type(exc).__name__}): {exc}",
                message=f"Во время выполнения задачи произошла ошибка: {exc}",
                data={"exception_type": type(exc).__name__, "exception_message": str(exc)}
            )
            return self.adapt_result(fail_result, legacy_route=legacy_route)

    def adapt_result(
        self,
        result: Any,
        route_result: Optional[RouteResult] = None,
        legacy_route: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Преобразует AgentResult в канонический словарь ответа Agent.process().

        Формат словаря:
        - type: имя capability или агента (для ветвления в CLI/GUI);
        - answer: человекочитаемый текст для чата и TTS-озвучки;
        - message: дубликат answer для обратной совместимости;
        - success: булев флаг успешности выполнения;
        - created_files: список путей созданных файлов;
        - artifacts: список сериализованных словарей артефактов;
        - data: метаданные и бизнес-данные результата;
        - result: исходный объект AgentResult;
        - error: текст ошибки (при success == False).
        """
        # Если передан словарь, пытаемся извлечь AgentResult
        if not isinstance(result, AgentResult) and isinstance(result, dict):
            try:
                result = AgentResult.from_dict(result)
            except Exception:
                pass

        if isinstance(result, AgentResult):
            # 1. Определение типа ответа
            resp_type = "agent"
            if route_result and route_result.capability:
                resp_type = route_result.capability
            elif route_result and route_result.agent_name:
                resp_type = route_result.agent_name
            elif isinstance(result.data, dict) and "route" in result.data and isinstance(result.data["route"], dict):
                r_info = result.data["route"]
                resp_type = r_info.get("capability") or r_info.get("agent") or "agent"
            elif isinstance(result.data, dict) and result.data.get("agent"):
                resp_type = str(result.data["agent"])

            # 2. Формирование текста ответа
            if result.success:
                answer_text = result.message or "Действие успешно выполнено."
            else:
                answer_text = result.message or result.error or "Во время выполнения задачи произошла ошибка."

            # 3. Сериализация артефактов через to_dict()
            serialized_artifacts = []
            for art in result.artifacts:
                if hasattr(art, "to_dict") and callable(art.to_dict):
                    serialized_artifacts.append(art.to_dict())
                elif isinstance(art, dict):
                    serialized_artifacts.append(dict(art))
                else:
                    serialized_artifacts.append(str(art))

            # Поддержка CompatibleType для обратной совместимости с legacy-проверками (type == 'tool')
            resp_type_val = CompatibleType(resp_type)

            payload: Dict[str, Any] = {
                "type": resp_type_val,
                "answer": answer_text,
                "message": answer_text,
                "success": bool(result.success),
                "created_files": list(result.created_files),
                "artifacts": serialized_artifacts,
                "data": dict(result.data),
                "result": result,  # сохраняем исходный объект для UI
            }

            # Сохранение tool из legacy_route или data для обратной совместимости
            if legacy_route and isinstance(legacy_route, dict) and legacy_route.get("tool"):
                payload["tool"] = legacy_route["tool"]
            elif isinstance(result.data, dict) and result.data.get("tool"):
                payload["tool"] = result.data["tool"]

            if not result.success:
                payload["error"] = result.error or answer_text

            return payload

        # Защитный fallback при непредвиденном типе объекта
        answer = f"Получен результат непредвиденного типа: {type(result).__name__}"
        return {
            "type": "error",
            "answer": answer,
            "message": answer,
            "success": False,
            "created_files": [],
            "artifacts": [],
            "data": {},
            "result": result,
            "error": answer,
        }
