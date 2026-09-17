from tools.dispatcher import dispatch


class PlanExecutor:
    """
    Выполняет структурированный план по шагам.

    Executor получает готовый план от Planner
    и последовательно выполняет его действия.
    """

    def __init__(self, agent=None):
        self.agent = agent

    def execute(self, plan):
        """
        Выполняет переданный план.
        """

        if not isinstance(plan, dict):
            return {
                "success": False,
                "message": "План имеет некорректный формат."
            }

        steps = plan.get("steps")

        if not isinstance(steps, list) or not steps:
            return {
                "success": False,
                "message": "В плане отсутствуют шаги."
            }

        results = []

        for step in steps:

            result = self._execute_step(
                step,
                results
            )

            results.append(result)

            if not result.get("success"):
                return {
                    "success": False,
                    "message": (
                        f"Выполнение остановлено "
                        f"на шаге {step.get('id')}."
                    ),
                    "step": step,
                    "results": results
                }

        return {
            "success": True,
            "message": "План выполнен успешно.",
            "results": results
        }

    def _execute_step(self, step, previous_results):
        """
        Выполняет один шаг плана.
        """

        if not isinstance(step, dict):
            return {
                "success": False,
                "message": "Шаг имеет некорректный формат."
            }

        action = step.get("action")
        target = step.get("target")
        command = step.get("command")
        query = step.get("query")
        details = step.get("details", "")

        context = self._build_context(
            previous_results
        )

        if action == "search":
            return self._execute_search(
                query,
                details,
                context
            )

        if action == "analyze":

            resolved_target = self._resolve_target(
                target,
                previous_results
            )

            content = self._get_read_content(
                resolved_target,
                previous_results
            )

            return self._execute_analyze(
                resolved_target,
                details,
                context,
                content
            )

        if action == "read":

            resolved_target = self._resolve_target(
                target,
                previous_results
            )

            return self._execute_read(
                resolved_target,
                details,
                context
            )

        if action == "edit":
            return self._execute_edit(
                target,
                details,
                context
            )

        if action == "command":
            return self._execute_command(
                command,
                details,
                context
            )

        if action == "validate":
            return self._execute_validate(
                details,
                context
            )

        if action == "git":
            return self._execute_git(
                command,
                details,
                context
            )

        return {
            "success": False,
            "message": (
                f"Неизвестное действие: {action}"
            )
        }

    def _execute_search(
        self,
        query,
        details,
        context
    ):
        """
        Выполняет поиск по проекту.
        """

        if not query:
            return {
                "success": False,
                "message": (
                    "Для search не указан query."
                )
            }

        result = dispatch(
            "search_files",
            query=query
        )

        return {
            "success": result.get("success", False),
            "action": "search",
            "query": query,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_analyze(
        self,
        target,
        details,
        context,
        content=None
    ):
        """
        Анализирует файл.

        Если content уже получен предыдущим шагом read,
        повторное чтение файла не выполняется.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для analyze не указан target."
                )
            }

        if content is not None:

            result = dispatch(
                "analyze_file",
                filename=target,
                task=details,
                content=content
            )

        else:

            result = dispatch(
                "analyze_file",
                filename=target,
                task=details
            )

        return {
            "success": result.get("success", False),
            "action": "analyze",
            "target": target,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_read(
        self,
        target,
        details,
        context
    ):
        """
        Читает файл.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для read не указан target."
                )
            }

        result = dispatch(
            "read_file",
            filename=target
        )

        return {
            "success": result.get("success", False),
            "action": "read",
            "target": target,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_edit(
        self,
        target,
        details,
        context
    ):
        """
        Подготавливает и выполняет изменение файла.
        """

        if not target:
            return {
                "success": False,
                "message": (
                    "Для edit не указан target."
                )
            }

        if self.agent is None:
            return {
                "success": False,
                "message": (
                    "PlanExecutor не получил Agent."
                )
            }

        user_request = self._build_edit_request(
            target,
            details,
            context
        )

        prepared = self.agent.prepare_edit(
            target,
            user_request
        )

        if not prepared.get("success"):
            return {
                "success": False,
                "action": "edit",
                "target": target,
                "details": details,
                "result": prepared,
                "context": context
            }

        edit_result = dispatch(
            "edit_file",
            filename=target,
            old_text=prepared["old_text"],
            new_text=prepared["new_text"]
        )

        return {
            "success": edit_result.get("success", False),
            "action": "edit",
            "target": target,
            "details": details,
            "result": edit_result,
            "context": context
        }

    def _execute_command(
        self,
        command,
        details,
        context
    ):
        """
        Выполняет команду.
        """

        if not command:
            return {
                "success": False,
                "message": (
                    "Для command не указана команда."
                )
            }

        result = dispatch(
            "run_command",
            command=command
        )

        return {
            "success": result.get("success", False),
            "action": "command",
            "command": command,
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_validate(
        self,
        details,
        context
    ):
        """
        Выполняет полную проверку Python-проекта.
        """

        result = dispatch(
            "validate_project"
        )

        return {
            "success": result.get("success", False),
            "action": "validate",
            "details": details,
            "result": result,
            "context": context
        }

    def _execute_git(
        self,
        command,
        details,
        context
    ):
        """
        Выполняет Git-команду.
        """

        if not command:
            return {
                "success": False,
                "message": (
                    "Для git не указана команда."
                )
            }

        result = dispatch(
            "run_command",
            command=command
        )

        return {
            "success": result.get("success", False),
            "action": "git",
            "command": command,
            "details": details,
            "result": result,
            "context": context
        }

    def _resolve_target(
        self,
        target,
        previous_results
    ):
        """
        Определяет файл для read/analyze.

        Приоритет:

        1. target из плана, если он указан.
        2. Файл из последнего успешного search.
        3. None.

        target из плана имеет приоритет, потому что search_files()
        ищет текст внутри файлов и не гарантирует, что первое
        совпадение является целевым файлом.
        """

        if target:
            return target

        for result in reversed(previous_results):

            if result.get("action") != "search":
                continue

            if not result.get("success"):
                continue

            tool_result = result.get("result")

            if not isinstance(tool_result, dict):
                continue

            if not tool_result.get("success"):
                continue

            search_result = tool_result.get(
                "result"
            )

            if not isinstance(search_result, dict):
                continue

            if not search_result.get("success"):
                continue

            matches = search_result.get(
                "matches",
                []
            )

            if not isinstance(matches, list):
                continue

            if not matches:
                continue

            first_match = matches[0]

            if not isinstance(first_match, dict):
                continue

            file_name = first_match.get(
                "file"
            )

            if file_name:
                return file_name

        return None

    def _get_read_content(
        self,
        target,
        previous_results
    ):
        """
        Получает содержимое файла из предыдущего
        успешного шага read.

        Возвращает None, если подходящего результата
        read нет.
        """

        if not target:
            return None

        for result in reversed(previous_results):

            if result.get("action") != "read":
                continue

            if not result.get("success"):
                continue

            if result.get("target") != target:
                continue

            tool_result = result.get("result")

            if not isinstance(tool_result, dict):
                continue

            if not tool_result.get("success"):
                continue

            read_result = tool_result.get(
                "result"
            )

            if not isinstance(read_result, dict):
                continue

            if not read_result.get("success"):
                continue

            content = read_result.get(
                "content"
            )

            if content is not None:
                return content

        return None

    def _build_context(
        self,
        previous_results
    ):
        """
        Формирует контекст из предыдущих шагов.
        """

        context = []

        for item in previous_results:

            context.append({
                "action": item.get("action"),
                "target": item.get("target"),
                "query": item.get("query"),
                "command": item.get("command"),
                "success": item.get("success"),
                "result": item.get("result")
            })

        return context

    def _build_edit_request(
        self,
        target,
        details,
        context
    ):
        """
        Формирует запрос для подготовки изменения файла.
        """

        request = (
            f"Измени файл {target}.\n\n"
            f"Задача текущего шага:\n"
            f"{details}\n"
        )

        if context:

            request += (
                "\nРезультаты предыдущих шагов:\n"
            )

            for item in context:

                request += (
                    f"\nДействие: "
                    f"{item.get('action')}\n"
                    f"Цель: "
                    f"{item.get('target')}\n"
                    f"Поиск: "
                    f"{item.get('query')}\n"
                    f"Успешно: "
                    f"{item.get('success')}\n"
                    f"Результат: "
                    f"{item.get('result')}\n"
                )

        return request
