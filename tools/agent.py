import inspect

import json

import re

from ollama_client import OllamaClient

from tools.dispatcher import dispatch

from tools.planner import Planner

from tools.plan_executor import PlanExecutor

from tools.teamwork import TeamworkCoordinator

from tools.registry import TOOLS, get_tools_schema

from tools.edit_preparer import EditPreparer
from tools.summary import format_task_summary

class Agent:
    """
    Главный интеллектуальный агент Акакия.

    Отвечает за:
    - понимание запроса пользователя;
    - выбор инструмента;
    - создание и выполнение планов;
    - подготовку изменений файлов.
    """

    def __init__(self):
        self.ai = OllamaClient()
        self.edit_preparer = EditPreparer(self.ai)
        self.planner = Planner()
        self.executor = PlanExecutor(self)
        self.teamwork = TeamworkCoordinator(self)

    def choose_tool(self, user_input):
        """
        Определяет, какой инструмент необходимо использовать для детерминированных CLI-команд.
        Любые запросы на естественном языке не перехватываются и передаются в Native Tool Calling.
        """

        normalized_input = user_input.strip().lower().rstrip(".,!?;:")

        # =================================================
        # Поиск конкретного файла (строгая CLI-команда)
        # =================================================

        file_search_patterns = [
            r"^(?:найди|найти)(?:\s+в\s+проекте)?\s+файл\s+([^\s,!?;:]+)$",
        ]

        for pattern in file_search_patterns:
            match = re.match(
                pattern,
                normalized_input,
                flags=re.IGNORECASE
            )

            if match:
                filename = match.group(1).strip()
                filename = filename.rstrip(".,!?;:")

                return {
                    "tool": "find_file",
                    "arguments": {
                        "filename": filename
                    }
                }

        # =================================================
        # Просмотр списка файлов проекта (строгая CLI-команда)
        # =================================================

        list_files_exact = {
            "покажи список файлов проекта",
            "покажи файлы проекта",
            "список файлов проекта",
            "перечисли файлы проекта",
            "покажи список файлов",
            "покажи файлы",
            "список файлов",
            "перечисли файлы",
            "файлы проекта",
        }

        if normalized_input in list_files_exact:
            return {
                "tool": "list_files",
                "arguments": {}
            }

        # =================================================
        # Анализ структуры проекта (строгая CLI-команда)
        # =================================================

        structure_exact = {
            "покажи структуру проекта",
            "покажи структуру проекта акакия",
            "структура проекта",
        }

        if normalized_input in structure_exact:
            return {
                "tool": "list_files",
                "arguments": {}
            }

        # =================================================
        # Поиск функции (строгая CLI-команда)
        # =================================================

        func_match = re.match(
            r"^(?:найди|найти)\s+функцию\s+([a-zA-Z_0-9]+)$",
            normalized_input,
            flags=re.IGNORECASE
        )
        if func_match:
            search_query = f"def {func_match.group(1).strip()}"
            return {
                "tool": "search_files",
                "arguments": {
                    "query": search_query
                }
            }

        # =================================================
        # Поиск по проекту (строгая CLI-команда)
        # =================================================

        search_match = re.match(
            r"^(?:поиск\s+по\s+проекту|(?:найди|найти)\s+в\s+проекте\s+текст)\s+(.+)$",
            normalized_input,
            flags=re.IGNORECASE
        )
        if search_match:
            search_query = search_match.group(1).strip()
            return {
                "tool": "search_files",
                "arguments": {
                    "query": search_query
                }
            }

        # Если ни один детерминированный шаблон не подошёл,
        # возвращаем отсутствие инструмента (маршрутизация передаётся в Native Tool Calling)
        return {
            "tool": None,
            "arguments": {}
        }

    def execute_tool(self, tool_name, arguments):
        """
        Безопасно выполняет выбранный инструмент.

        Перед dispatch:
        - проверяется существование инструмента;
        - проверяется тип аргументов;
        - нормализуются известные синонимы;
        - проверяются неизвестные аргументы;
        - проверяются обязательные параметры.

        Это защищает инструментальный слой от ошибок,
        когда AI передаёт параметр, которого нет
        в реальной сигнатуре функции.
        """

        if not isinstance(tool_name, str) or not tool_name.strip():
            return {
                "success": False,
                "error": "Не указано имя инструмента."
            }

        tool_name = tool_name.strip()

        if tool_name not in TOOLS:
            return {
                "success": False,
                "error": (
                    f"Инструмент не найден: {tool_name}"
                )
            }

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            return {
                "success": False,
                "error": (
                    "Аргументы инструмента должны "
                    "быть объектом JSON."
                )
            }

        normalized_arguments = dict(arguments)

        # =================================================
        # Нормализация известных синонимов
        # =================================================

        if tool_name == "search_files":
            if (
                "pattern" in normalized_arguments
                and "query" not in normalized_arguments
            ):
                normalized_arguments["query"] = (
                    normalized_arguments.pop("pattern")
                )

        # =================================================
        # Получаем реальную сигнатуру инструмента
        # =================================================

        function = TOOLS[tool_name]["function"]
        signature = inspect.signature(function)
        parameters = signature.parameters

        # =================================================
        # Проверяем неизвестные аргументы
        # =================================================

        unknown_arguments = [
            name
            for name in normalized_arguments
            if name not in parameters
        ]

        if unknown_arguments:
            return {
                "success": False,
                "error": (
                    f"Инструмент '{tool_name}' "
                    f"не принимает следующие аргументы: "
                    f"{', '.join(unknown_arguments)}."
                )
            }

        # =================================================
        # Проверяем обязательные аргументы
        # =================================================

        missing_arguments = []

        for name, parameter in parameters.items():
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD
            ):
                continue

            if (
                parameter.default is inspect.Parameter.empty
                and name not in normalized_arguments
            ):
                missing_arguments.append(name)

        if missing_arguments:
            return {
                "success": False,
                "error": (
                    f"Для инструмента '{tool_name}' "
                    f"не хватает обязательных аргументов: "
                    f"{', '.join(missing_arguments)}."
                )
            }

        # =================================================
        # Выполняем инструмент
        # =================================================

        return dispatch(
            tool_name,
            **normalized_arguments
        )

    def serialize_tool_result(self, result):
        """
        Сериализует результат выполнения инструмента для передачи в Ollama с role: tool.
        """
        if isinstance(result, dict):
            # Если это стандартная обёртка dispatch {"success": True, "result": ...}
            if "result" in result and result.get("success") is True:
                inner = result["result"]
                if isinstance(inner, (dict, list)):
                    return json.dumps(inner, ensure_ascii=False, indent=2)
                return str(inner)
            return json.dumps(result, ensure_ascii=False, indent=2)
        elif isinstance(result, (list, tuple)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)

    def prepare_edit(self, filename, user_request):
        """
        Подготавливает изменение файла.
        Делегирует исполнение в EditPreparer, сохраняя стабильный интерфейс фасада.
        """
        return self.edit_preparer.prepare_edit(
            filename=filename,
            user_request=user_request
        )

    def create_plan(self, user_request, research_context=None):
        """
        Создаёт план выполнения задачи.
        """

        return self.planner.create_plan(
            user_request,
            research_context=research_context
        )

    def format_task_summary(self, plan_data, exec_result, research_info=None):
        """
        Формирует агрегированный отчёт о выполнении комплексной задачи.
        Делегирует форматирование в tools.summary.
        """
        return format_task_summary(
            plan_data=plan_data,
            exec_result=exec_result,
            research_info=research_info
        )

    def run_single_correction(self, errors):
        """
        Выполняет строго одну попытку self-healing при синтаксических ошибках.
        Разрешён только точечный инструмент 'edit_file'. 'write_file' запрещён.
        Требует обязательного подтверждения пользователя.
        """
        if not errors:
            return {"success": False, "error": "Нет ошибок для исправления."}

        prompt = (
            "В проекте обнаружены синтаксические ошибки после изменений:\n"
            f"{json.dumps(errors, ensure_ascii=False, indent=2)}\n\n"
            "Вызови инструмент 'edit_file', чтобы точечно исправить ошибку. "
            "Инструмент 'write_file' запрещён для автоматического исправления."
        )

        resp = self.ai.send_chat(
            [
                {"role": "user", "content": prompt}
            ],
            tools=get_tools_schema()
        )

        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            return {
                "success": False,
                "error": "Модель не предложила инструмент для исправления ошибок."
            }

        first_call = tool_calls[0]
        fn_data = first_call.get("function", {})
        fn_name = fn_data.get("name")
        args = fn_data.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass

        if fn_name != "edit_file":
            return {
                "success": False,
                "error": f"Инструмент '{fn_name}' не разрешён для автоматического исправления. Разрешён только 'edit_file'."
            }

        exec_res = self.execute_tool("edit_file", args)
        if not exec_res.get("success", True):
            return {
                "success": False,
                "error": exec_res.get("error", "Исправление отменено пользователем или завершилось ошибкой.")
            }

        val_res = self.execute_tool("validate_project", {})
        val_success = val_res.get("success", True) and not val_res.get("errors")

        return {
            "success": val_success,
            "edit_result": exec_res,
            "validation_result": val_res
        }

    def execute_plan(self, plan=None):
        """
        Выполняет переданный план.

        Если план не передан,
        используется текущий план Planner.
        """

        if plan is None:
            current = self.planner.get_current_plan()

            if not current.get("success"):
                return current

            plan = current.get("plan")

        execution_result = self.executor.execute(plan)

        # Формируем и прикрепляем агрегированную сводку
        summary = self.format_task_summary(plan, execution_result)
        execution_result["summary"] = summary

        return execution_result

    def process(self, user_input):
        """
        Главный обработчик пользовательского запроса.

        Возвращает единый формат результата,
        который ожидает main.py.
        """

        user_input = user_input.strip()

        if not user_input:
            return {
                "type": "chat",
                "answer": "Пустой запрос."
            }

        # =================================================
        # Создание плана
        # =================================================

        if user_input.lower().startswith("план:"):
            request = user_input[5:].strip()

            if not request:
                return {
                    "type": "plan",
                    "tool": "plan",
                    "result": {
                        "success": False,
                        "message": (
                            "После 'план:' необходимо "
                            "указать задачу."
                        )
                    }
                }

            result = self.create_plan(request)

            return {
                "type": "plan",
                "tool": "plan",
                "result": result
            }

        # =================================================
        # Выполнение плана
        # =================================================

        if user_input.lower() in {
            "выполни план",
            "выполнить план",
            "запусти план",
        }:
            result = self.execute_plan()

            return {
                "type": "plan_execution",
                "tool": "execute_plan",
                "result": result
            }

        # =================================================
        # Просмотр текущего плана
        # =================================================

        if user_input.lower() in {
            "покажи план",
            "текущий план",
            "показать план",
        }:
            result = self.planner.get_current_plan()

            return {
                "type": "plan",
                "tool": "get_current_plan",
                "result": result
            }

        # =================================================
        # Очистка плана
        # =================================================

        if user_input.lower() in {
            "очисти план",
            "удали план",
            "сбрось план",
        }:
            result = self.planner.clear_plan()

            return {
                "type": "tool",
                "tool": "clear_plan",
                "result": result
            }

        # =================================================
        # Обычный инструмент
        # =================================================

        # =================================================
        # Teamwork Preview для сложных многошаговых задач
        # =================================================
        if self.teamwork.is_complex_task(user_input):
            execution_result = self.teamwork.run(user_input)
            return {
                "type": "plan_execution",
                "tool": "execute_plan",
                "result": execution_result
            }

        tool_selection = self.choose_tool(
            user_input
        )

        tool_name = tool_selection.get("tool") if tool_selection else None

        if tool_name and str(tool_name).strip().lower() not in {"null", "none"}:
            arguments = tool_selection.get(
                "arguments",
                {}
            )

            result = self.execute_tool(
                tool_name,
                arguments
            )

            return {
                "type": "tool",
                "tool": tool_name,
                "result": result
            }

        # =================================================
        # Native Tool Calling (Ollama)
        # =================================================

        MAX_TOOL_ROUNDS = 5
        MAX_CORRECTION_ATTEMPTS = 1
        correction_attempts = 0
        has_validation_errors = False

        turn_messages = [
            {
                "role": "user",
                "content": user_input
            }
        ]

        response = self.ai.ask(
            user_input,
            add_to_history=True,
            tools=get_tools_schema()
        )

        if isinstance(response, dict):
            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")
            assistant_msg = response.get("message") or {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls
            }
        else:
            tool_calls = []
            content = str(response)
            assistant_msg = {
                "role": "assistant",
                "content": content
            }

        if not tool_calls:
            return {
                "type": "chat",
                "answer": content
            }

        for round_idx in range(MAX_TOOL_ROUNDS):
            # Проверяем, не пытается ли модель превысить лимит попыток исправления
            blocked_by_limit = False
            for call in tool_calls:
                fn_data = call.get("function", {})
                fn_name = fn_data.get("name")
                if has_validation_errors and fn_name == "edit_file":
                    if correction_attempts >= MAX_CORRECTION_ATTEMPTS:
                        blocked_by_limit = True
                        break

            if blocked_by_limit:
                # Превышен лимит попыток исправления. Не выполняем повторный corrective edit.
                # Получаем финальный текстовый ответ без инструментов.
                if not content or not (isinstance(content, str) and content.strip()):
                    final_resp = self.ai.send_tool_step(
                        turn_messages,
                        tools=None
                    )
                    content = final_resp.get("content", "")
                    assistant_msg = final_resp.get("message") or {
                        "role": "assistant",
                        "content": content
                    }
                else:
                    assistant_msg = {
                        "role": "assistant",
                        "content": content
                    }
                turn_messages.append(assistant_msg)
                self.ai.commit_turn(turn_messages)
                return {
                    "type": "chat",
                    "answer": content if (isinstance(content, str) and content.strip()) else "Достигнут лимит попыток исправления. В проекте сохраняются синтаксические ошибки."
                }

            turn_messages.append(assistant_msg)

            mutations_in_round = False

            for call in tool_calls:
                function_data = call.get("function", {})
                tool_name = function_data.get("name")
                arguments = function_data.get("arguments", {})

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except Exception:
                        pass

                # Запрет write_file как корректирующей операции
                if has_validation_errors and tool_name == "write_file":
                    return {
                        "type": "tool",
                        "tool": tool_name,
                        "result": {
                            "success": False,
                            "error": (
                                "Инструмент 'write_file' не разрешён для "
                                "автоматического исправления ошибок валидации. "
                                "Исправление должно быть точечным через 'edit_file'."
                            )
                        }
                    }

                # Если это исправление после обнаружения ошибки валидации, учитываем попытку
                if has_validation_errors and tool_name == "edit_file":
                    correction_attempts += 1

                result = self.execute_tool(
                    tool_name,
                    arguments
                )

                # Если выполнение инструмента вернуло ошибку или отменено пользователем:
                # 1. Немедленно прерываем цепочку
                # 2. Не отправляем повторные запросы в Ollama
                # 3. Не фиксируем незавершённый ход в истории сообщений
                # 4. Возвращаем результат ошибки/отмены пользователю
                if isinstance(result, dict) and not result.get("success", True):
                    # Если до этой отмены/ошибки в текущем раунде уже были применены реальные мутации файлов,
                    # запускаем валидацию только по фактически выполненным изменениям
                    if mutations_in_round:
                        self.execute_tool(
                            "validate_project",
                            {}
                        )
                    return {
                        "type": "tool",
                        "tool": tool_name,
                        "result": result
                    }

                tool_content = self.serialize_tool_result(result)
                tool_message = {
                    "role": "tool",
                    "content": tool_content
                }
                if call.get("id"):
                    tool_message["tool_call_id"] = call["id"]

                turn_messages.append(tool_message)

                if tool_name in ("edit_file", "write_file"):
                    mutations_in_round = True

            # Если в данном раунде выполнялись изменения файлов, запускаем проверку проекта один раз в конце раунда
            if mutations_in_round:
                validation_result = self.execute_tool(
                    "validate_project",
                    {}
                )
                validation_content = self.serialize_tool_result(
                    validation_result
                )
                turn_messages.append({
                    "role": "tool",
                    "content": validation_content
                })
                validation_failed = not validation_result.get("success", True) or bool(validation_result.get("errors"))
                has_validation_errors = validation_failed

            next_response = self.ai.send_tool_step(
                turn_messages,
                tools=get_tools_schema()
            )

            tool_calls = next_response.get("tool_calls", [])
            content = next_response.get("content", "")
            assistant_msg = next_response.get("message") or {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls
            }

            if not tool_calls:
                turn_messages.append(assistant_msg)
                self.ai.commit_turn(turn_messages)
                return {
                    "type": "chat",
                    "answer": content if (isinstance(content, str) and content.strip()) else "Действие успешно выполнено."
                }

        # При достижении лимита раундов запрашиваем финальный ответ без инструментов (tools=None)
        final_resp = self.ai.send_tool_step(
            turn_messages,
            tools=None
        )
        final_content = final_resp.get("content", "").strip() if isinstance(final_resp, dict) else ""
        final_answer = final_content or "Достигнут максимальный лимит шагов инструментов (5). Выполнение остановлено."
        return {
            "type": "chat",
            "answer": final_answer
        }