import inspect

import json

import re

from ollama_client import OllamaClient

from tools.dispatcher import dispatch

from tools.planner import Planner

from tools.plan_executor import PlanExecutor

from tools.teamwork import TeamworkCoordinator

from tools.registry import TOOLS, get_tools_schema
from tools.memory import get_memory_manager
from tools.context import ContextManager, get_context_manager
from skills.registry import get_skill_registry

from tools.edit_preparer import EditPreparer
from tools.summary import format_task_summary
from tools.router import CommandRouter, get_router

class Agent:
    """
    Главный интеллектуальный агент Акакия.

    Отвечает за:
    - понимание запроса пользователя;
    - выбор инструмента и навыка;
    - создание и выполнение планов;
    - подготовку изменений файлов;
    - координацию единого контекста диалога и памяти.
    """

    def __init__(self, memory_manager=None, context_manager=None, ai_client=None, skill_registry=None, router=None):
        mem = memory_manager or get_memory_manager()
        self.context_manager = context_manager or ContextManager(memory_manager=mem)
        self.ai = ai_client or OllamaClient()
        self.skill_registry = skill_registry or get_skill_registry()
        self.router = router or CommandRouter()
        self.edit_preparer = EditPreparer(self.ai)
        self.planner = Planner(context_manager=self.context_manager, ai_client=self.ai)
        self.executor = PlanExecutor(self)
        self.teamwork = TeamworkCoordinator(self)
        self._sync_memory_to_system_prompt()

    @property
    def memory(self):
        return self.context_manager.memory_manager

    @memory.setter
    def memory(self, val):
        self.context_manager.memory_manager = val

    def _sync_memory_to_system_prompt(self):
        """
        Устанавливает чистый системный промпт без инъекций пользовательских данных.
        Пользовательские данные передаются модели исключительно как справочные данные.
        """
        self.ai.set_system_prompt(self.context_manager.get_system_prompt())

    def _record_interaction(self, user_input, response_payload_or_text, tool_name=None, is_native_chat=False):
        """Фиксирует ход диалога в едином ContextManager."""
        if not user_input or not str(user_input).strip():
            return

        self.context_manager.record_interaction(
            user_input,
            response_payload_or_text,
            tool_name=tool_name
        )
        if not is_native_chat:
            self.ai.messages = self.context_manager.build_messages_for_llm("")[:-1]

    def choose_tool(self, user_input):
        """
        Определяет, какой инструмент необходимо использовать для детерминированных CLI-команд.
        Делегирует в CommandRouter.
        """
        return self.router.choose_tool(user_input)

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

        if tool_name == "remember":
            if "fact" in normalized_arguments and "text" not in normalized_arguments:
                normalized_arguments["text"] = normalized_arguments.pop("fact")

        if tool_name == "complete_task":
            if "id" in normalized_arguments and "task_id" not in normalized_arguments:
                normalized_arguments["task_id"] = normalized_arguments.pop("id")

        if tool_name == "delete_task":
            if "id" in normalized_arguments and "task_id" not in normalized_arguments:
                normalized_arguments["task_id"] = normalized_arguments.pop("id")

        if tool_name == "delete_note":
            if "id" in normalized_arguments and "note_id" not in normalized_arguments:
                normalized_arguments["note_id"] = normalized_arguments.pop("id")

        if tool_name == "delete_reminder":
            if "id" in normalized_arguments and "reminder_id" not in normalized_arguments:
                normalized_arguments["reminder_id"] = normalized_arguments.pop("id")

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
        Главный обработчик пользовательского запроса (оркестратор).

        Конвейер:
        CommandRouter (fast-path: memory / plan / tools) -> Teamwork -> SkillRegistry -> Native Tool Calling (Ollama).
        """

        user_input = user_input.strip()

        if not user_input:
            return {
                "type": "chat",
                "answer": "Пустой запрос."
            }

        # 1. Детерминированная маршрутизация через CommandRouter
        route = self.router.route(user_input)
        route_type = route.get("type")

        # 1.1. Долговременная память (Memory Fast-Path)
        if route_type == "memory":
            action = route.get("action")
            if action == "remember":
                fact_text = route.get("text", "")
                success, msg, _ = self.memory.remember(fact_text)
                if success:
                    self._sync_memory_to_system_prompt()
                self._record_interaction(user_input, msg)
                return {
                    "type": "chat",
                    "answer": msg
                }
            elif action == "recall":
                summary = self.memory.format_memories_summary()
                self._record_interaction(user_input, summary)
                return {
                    "type": "chat",
                    "answer": summary
                }
            elif action == "forget":
                target = route.get("target", "")
                success, msg = self.memory.forget(target)
                if success:
                    self._sync_memory_to_system_prompt()
                self._record_interaction(user_input, msg)
                return {
                    "type": "chat",
                    "answer": msg
                }
            elif action == "search":
                query = route.get("query", "")
                results = self.memory.search(query)
                if results:
                    summary = self.memory.format_memories_summary(results)
                else:
                    summary = f'В памяти ничего не найдено по запросу "{query}".'
                self._record_interaction(user_input, summary)
                return {
                    "type": "chat",
                    "answer": summary
                }
            elif action == "clear":
                _, msg = self.memory.clear_long_term()
                self._sync_memory_to_system_prompt()
                self._record_interaction(user_input, msg)
                return {
                    "type": "chat",
                    "answer": msg
                }

        # 1.2. Управление планами (Planning Fast-Path)
        if route_type == "plan":
            action = route.get("action")
            if action == "create":
                request = route.get("request", "")
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
                plan_res = {
                    "type": "plan",
                    "tool": "plan",
                    "result": result
                }
                self._record_interaction(user_input, plan_res)
                return plan_res
            elif action == "execute":
                result = self.execute_plan()
                exec_res = {
                    "type": "plan_execution",
                    "tool": "execute_plan",
                    "result": result
                }
                self._record_interaction(user_input, exec_res)
                return exec_res
            elif action == "get":
                result = self.planner.get_current_plan()
                resp = {
                    "type": "plan",
                    "tool": "get_current_plan",
                    "result": result
                }
                self._record_interaction(user_input, resp)
                return resp
            elif action == "clear":
                result = self.planner.clear_plan()
                resp = {
                    "type": "tool",
                    "tool": "clear_plan",
                    "result": result
                }
                self._record_interaction(user_input, resp)
                return resp

        # 2. Teamwork Preview для сложных многошаговых задач
        if self.teamwork.is_complex_task(user_input):
            execution_result = self.teamwork.run(user_input)
            resp = {
                "type": "plan_execution",
                "tool": "execute_plan",
                "result": execution_result
            }
            self._record_interaction(user_input, resp)
            return resp

        # 3. Детерминированный запуск инструментов (Tool Fast-Path)
        if route_type == "tool":
            tool_name = route.get("tool")
            if tool_name and str(tool_name).strip().lower() not in {"null", "none"}:
                arguments = route.get("arguments", {})
                result = self.execute_tool(
                    tool_name,
                    arguments
                )
                if tool_name in ("remember", "forget_memory"):
                    self._sync_memory_to_system_prompt()

                resp = {
                    "type": "tool",
                    "tool": tool_name,
                    "result": result
                }
                self._record_interaction(user_input, resp, tool_name=tool_name)
                return resp

        # =================================================
        # Skill Selection
        # =================================================
        active_skill = None
        if hasattr(self, "skill_registry") and self.skill_registry:
            active_skill = self.skill_registry.find_matching_skill(user_input)

        if active_skill and getattr(active_skill, "enabled", True):
            tools_for_llm = active_skill.get_tools_schema()
            extra_instruction = active_skill.system_prompt
        else:
            tools_for_llm = get_tools_schema()
            extra_instruction = None

        # =================================================
        # Native Tool Calling (Ollama)
        # =================================================

        MAX_TOOL_ROUNDS = 5
        MAX_CORRECTION_ATTEMPTS = 1
        correction_attempts = 0
        has_validation_errors = False

        # Формируем сообщения с учётом единого ContextManager, релевантной памяти и контекста навыка
        llm_messages = self.context_manager.build_messages_for_llm(
            user_input,
            include_memory=True,
            extra_system_instruction=extra_instruction
        )
        current_user_msg = llm_messages[-1]
        turn_messages = [current_user_msg]

        if hasattr(self.ai, "send_chat") and callable(self.ai.send_chat):
            response = self.ai.send_chat(
                llm_messages,
                tools=tools_for_llm
            )
        else:
            response = self.ai.ask(
                user_input,
                add_to_history=False,
                tools=tools_for_llm
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
            turn_messages.append(assistant_msg)
            self.context_manager.commit_turn_messages(turn_messages, clean_user_input=user_input)
            if hasattr(self.ai, "messages"):
                self.ai.messages = self.context_manager.build_messages_for_llm("")[:-1]
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
                    step_msgs = llm_messages[:-1] + turn_messages
                    if hasattr(self.ai, "send_chat") and callable(self.ai.send_chat):
                        final_resp = self.ai.send_chat(step_msgs, tools=None)
                    else:
                        final_resp = self.ai.send_tool_step(turn_messages, tools=None)
                    content = final_resp.get("content", "") if isinstance(final_resp, dict) else str(final_resp)
                    assistant_msg = (final_resp.get("message") if isinstance(final_resp, dict) else None) or {
                        "role": "assistant",
                        "content": content
                    }
                else:
                    assistant_msg = {
                        "role": "assistant",
                        "content": content
                    }
                turn_messages.append(assistant_msg)
                self.context_manager.commit_turn_messages(turn_messages, clean_user_input=user_input)
                if hasattr(self.ai, "messages"):
                    self.ai.messages = self.context_manager.build_messages_for_llm("")[:-1]
                ans = content if (isinstance(content, str) and content.strip()) else "Достигнут лимит попыток исправления. В проекте сохраняются синтаксические ошибки."
                return {
                    "type": "chat",
                    "answer": ans
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
                    resp = {
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
                    self._record_interaction(user_input, resp, tool_name=tool_name, is_native_chat=False)
                    return resp

                # Если это исправление после обнаружения ошибки валидации, учитываем попытку
                if has_validation_errors and tool_name == "edit_file":
                    correction_attempts += 1

                result = self.execute_tool(
                    tool_name,
                    arguments
                )
                if tool_name in ("remember", "forget_memory"):
                    self._sync_memory_to_system_prompt()

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
                    resp = {
                        "type": "tool",
                        "tool": tool_name,
                        "result": result
                    }
                    self._record_interaction(user_input, resp, tool_name=tool_name, is_native_chat=False)
                    return resp

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

            step_messages = llm_messages[:-1] + turn_messages
            if hasattr(self.ai, "send_chat") and callable(self.ai.send_chat):
                next_response = self.ai.send_chat(
                    step_messages,
                    tools=tools_for_llm
                )
            else:
                next_response = self.ai.send_tool_step(
                    turn_messages,
                    tools=tools_for_llm
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
                self.context_manager.commit_turn_messages(turn_messages, clean_user_input=user_input)
                if hasattr(self.ai, "messages"):
                    self.ai.messages = self.context_manager.build_messages_for_llm("")[:-1]
                ans = content if (isinstance(content, str) and content.strip()) else "Действие успешно выполнено."
                return {
                    "type": "chat",
                    "answer": ans
                }

        # При достижении лимита раундов запрашиваем финальный ответ без инструментов (tools=None)
        step_messages = llm_messages[:-1] + turn_messages
        if hasattr(self.ai, "send_chat") and callable(self.ai.send_chat):
            final_resp = self.ai.send_chat(
                step_messages,
                tools=None
            )
        else:
            final_resp = self.ai.send_tool_step(
                turn_messages,
                tools=None
            )
        final_content = final_resp.get("content", "").strip() if isinstance(final_resp, dict) else ""
        final_answer = final_content or "Достигнут максимальный лимит шагов инструментов (5). Выполнение остановлено."
        turn_messages.append({"role": "assistant", "content": final_answer})
        self.context_manager.commit_turn_messages(turn_messages, clean_user_input=user_input)
        if hasattr(self.ai, "messages"):
            self.ai.messages = self.context_manager.build_messages_for_llm("")[:-1]
        return {
            "type": "chat",
            "answer": final_answer
        }