"""
Доменный агент бытового управления (HouseholdAgent) multi-agent архитектуры Акакия.

Отвечает за:
- управление бытовыми задачами (создание, просмотр, завершение, удаление);
- управление напоминаниями (установка, просмотр, проверка наступивших, удаление);
- управление заметками (создание, просмотр, поиск, удаление);
- управление именованными списками (создание, добавление пунктов, отметка, удаление).

Архитектурный принцип:
HouseholdAgent является высокоуровневым доменным фасадом (Domain Agent),
наследующим BaseAgent и возвращающим канонический AgentResult.
Вся бизнес-логика и хранение делегируются существующему HouseholdManager,
исключая дублирование кода и механизмов хранения.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from agents.base import BaseAgent
from tools.agents.result import AgentResult
from tools.household import HouseholdManager, get_household_manager
from tools.router import CommandRouter

logger = logging.getLogger(__name__)


class HouseholdAgent(BaseAgent):
    """
    Высокоуровневый доменный агент управления бытовыми сценариями Акакия.
    """

    name: str = "household"
    description: str = "Управление бытовыми задачами, списками, заметками и напоминаниями."
    capabilities: List[str] = [
        "household",
        "tasks",
        "reminders",
        "notes",
        "lists"
    ]
    tools: List[str] = [
        "create_task",
        "list_tasks",
        "complete_task",
        "delete_task",
        "create_reminder",
        "list_reminders",
        "complete_reminder",
        "delete_reminder",
        "check_due_reminders",
        "create_note",
        "list_notes",
        "search_notes",
        "delete_note",
        "create_list",
        "show_list",
        "add_list_item",
        "complete_list_item",
        "toggle_list_item",
        "delete_list_item",
        "delete_list"
    ]

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        tools: Optional[List[str]] = None,
        enabled: bool = True,
        household_manager: Optional[HouseholdManager] = None,
        router: Optional[CommandRouter] = None,
        **kwargs: Any
    ):
        super().__init__(
            name=name if name is not None else self.name,
            description=description if description is not None else self.description,
            capabilities=capabilities,
            tools=tools,
            enabled=enabled,
            **kwargs
        )
        self.household_manager = household_manager
        self._router = router

    def _get_manager(self) -> HouseholdManager:
        """Возвращает внедрённый или глобальный синглтон HouseholdManager."""
        if self.household_manager is not None:
            return self.household_manager
        return get_household_manager()

    def _get_router(self) -> CommandRouter:
        """Возвращает внедрённый или стандартный экземпляр CommandRouter."""
        if self._router is not None:
            return self._router
        return CommandRouter()

    def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> AgentResult:
        """
        Основная точка входа для исполнения бытовой задачи.

        Поддерживает:
        1. Явный вызов инструмента через `action` или `tool` в kwargs/context.
        2. Прямой вызов по имени метода (если task совпадает с именем инструмента).
        3. Естественные текстовые запросы через детерминированное распознавание существующего CommandRouter.

        :param task: Текст бытовой команды или имя инструмента.
        :param context: Опциональный контекст вызова.
        :param kwargs: Параметры для передачи в метод HouseholdManager.
        :return: Канонический AgentResult.
        """
        task_str = str(task).strip() if task is not None else ""

        # 1. Извлечение явного инструмента/действия
        explicit_tool = (
            kwargs.get("action")
            or kwargs.get("tool")
            or (context.get("action") if isinstance(context, dict) else None)
            or (context.get("tool") if isinstance(context, dict) else None)
        )

        tool_name: Optional[str] = None
        args: Dict[str, Any] = {}

        if explicit_tool:
            clean_tool = str(explicit_tool).strip().lower()
            if clean_tool in self.tools:
                tool_name = clean_tool
                # Собираем аргументы из kwargs, исключая служебные поля
                args = {k: v for k, v in kwargs.items() if k not in ("action", "tool", "args", "arguments")}
                if "arguments" in kwargs and isinstance(kwargs["arguments"], dict):
                    args.update(kwargs["arguments"])
                elif "args" in kwargs and isinstance(kwargs["args"], dict):
                    args.update(kwargs["args"])

                # Если аргументы не были переданы структурированно, пробуем применить task_str
                if not args and task_str and task_str != explicit_tool:
                    args = self._infer_single_arg(tool_name, task_str)

        # 2. Проверка прямого совпадения task с именем инструмента
        if not tool_name and task_str.lower() in self.tools:
            tool_name = task_str.lower()
            args = {k: v for k, v in kwargs.items() if k not in ("action", "tool", "args", "arguments")}
            if "arguments" in kwargs and isinstance(kwargs["arguments"], dict):
                args.update(kwargs["arguments"])
            elif "args" in kwargs and isinstance(kwargs["args"], dict):
                args.update(kwargs["args"])

        # 3. Естественный запрос через существующий CommandRouter (без создания нового Router)
        if not tool_name:
            if not task_str:
                return AgentResult.fail(
                    error="Получен пустой запрос для HouseholdAgent.",
                    message="Бытовая задача не может быть пустой.",
                    data={"agent": self.name}
                )

            decision = self._get_router().choose_tool(task_str)
            candidate_tool = decision.get("tool")

            if candidate_tool and candidate_tool in self.tools:
                tool_name = candidate_tool
                args = dict(decision.get("arguments", {}))
                # Дополняем явными kwargs при их наличии
                extra_args = {k: v for k, v in kwargs.items() if k not in ("action", "tool", "args", "arguments")}
                args.update(extra_args)

        # 4. Обработка неизвестной или неподдерживаемой команды
        if not tool_name or tool_name not in self.tools:
            return AgentResult.fail(
                error=f"Неизвестная или неподдерживаемая бытовая команда: '{task_str}'",
                message=f"Команда '{task_str}' не поддерживается HouseholdAgent.",
                data={"task": task_str, "agent": self.name}
            )

        # 5. Исполнение операции через существующий HouseholdManager
        manager = self._get_manager()
        method = getattr(manager, tool_name, None)

        if not method or not callable(method):
            return AgentResult.fail(
                error=f"Метод '{tool_name}' не реализован в HouseholdManager.",
                message=f"Не удалось вызвать бытовую операцию '{tool_name}'.",
                data={"tool": tool_name, "agent": self.name}
            )

        try:
            res = method(**args)
        except TypeError as ex:
            logger.warning(f"Несоответствие сигнатуры при вызове {tool_name}({args}): {ex}")
            return AgentResult.fail(
                error=f"Неверные аргументы для операции '{tool_name}': {ex}",
                message=f"Не удалось выполнить '{tool_name}': проверьте параметры вызова.",
                data={"tool": tool_name, "args": args}
            )
        except Exception as ex:
            logger.error(f"Исключение при вызове HouseholdManager.{tool_name}({args}): {ex}", exc_info=True)
            return AgentResult.fail(
                error=f"Ошибка слоя HouseholdManager ({type(ex).__name__}): {ex}",
                message=f"Сбой при выполнении бытовой операции: {ex}",
                data={"tool": tool_name, "args": args}
            )

        # 6. Обработка результата существующего HouseholdManager
        if isinstance(res, dict):
            payload_data = dict(res)
            if "result" not in payload_data:
                payload_data["result"] = res
            if res.get("success", False):
                return AgentResult.ok(
                    message=res.get("message", "Бытовая операция успешно выполнена."),
                    data=payload_data
                )
            else:
                err_msg = res.get("error") or res.get("message") or "Ошибка бытовой операции."
                return AgentResult.fail(
                    error=str(err_msg),
                    message=str(res.get("message") or err_msg),
                    data=payload_data
                )

        return AgentResult.ok(
            message="Операция выполнена.",
            data={"result": res}
        )

    def _infer_single_arg(self, tool_name: str, value: str) -> Dict[str, Any]:
        """Вспомогательный маппинг одиночной строки в ключевой аргумент метода."""
        if tool_name == "create_task":
            return {"title": value}
        if tool_name in ("complete_task", "delete_task"):
            return {"task_id": value}
        if tool_name == "create_note":
            return {"title": value, "content": value}
        if tool_name in ("delete_note",):
            return {"note_id": value}
        if tool_name == "search_notes":
            return {"query": value}
        if tool_name in ("create_list", "show_list", "delete_list"):
            return {"name": value}
        if tool_name in ("complete_reminder", "delete_reminder"):
            return {"reminder_id": value}
        return {}
