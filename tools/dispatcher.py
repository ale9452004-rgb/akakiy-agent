from tools.registry import get_tool


_confirmation_handler = None
_action_observer = None


def set_confirmation_handler(handler):
    """
    Устанавливает обработчик запроса подтверждения (например, для GUI).
    handler(tool_name, kwargs) -> bool или str ("да"/"нет").
    Если handler равен None, используется стандартный консольный input().
    """
    global _confirmation_handler
    _confirmation_handler = handler


def set_action_observer(observer):
    """
    Устанавливает наблюдатель за выполнением действий (например, для отображения шагов в GUI).
    observer(event_type, data)
    """
    global _action_observer
    _action_observer = observer


def get_confirmation_handler():
    return _confirmation_handler


def get_action_observer():
    return _action_observer


def get_confirmation_details_text(tool_name, kwargs):
    """
    Формирует текстовое описание параметров инструмента для запроса подтверждения.
    """
    lines = []
    if tool_name == "run_command":
        command = kwargs.get("command", "")
        lines.append("Действие: Выполнение команды оболочки PowerShell")
        lines.append(f"Команда: {command}")

    elif tool_name == "write_file":
        filename = kwargs.get("filename", "")
        content = kwargs.get("content", "")
        size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0
        lines.append(f"Файл: {filename}")
        lines.append(f"Размер содержимого: {size_bytes} байт")

    elif tool_name == "edit_file":
        filename = kwargs.get("filename", "")
        old_text = kwargs.get("old_text", "")
        new_text = kwargs.get("new_text", "")
        lines.append(f"Файл: {filename}")
        lines.append("Замена текста:")
        old_preview = old_text if len(old_text) <= 120 else old_text[:117] + "..."
        new_preview = new_text if len(new_text) <= 120 else new_text[:117] + "..."
        lines.append(f"  Было:  {old_preview}")
        lines.append(f"  Стало: {new_preview}")

    elif tool_name == "git_commit":
        message = kwargs.get("message", "")
        lines.append(f"Сообщение коммита: {message}")
        from tools.git import git_status
        status = git_status()
        if status.get("success") and status.get("stdout", "").strip():
            lines.append("Изменения для коммита:")
            for line in status["stdout"].splitlines():
                lines.append(f"  {line}")
        else:
            lines.append("Изменения: нет обнаруженных изменений")

    elif tool_name == "git_push":
        from tools.git import run_git_command
        branch_res = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_res.get("stdout", "").strip() if branch_res.get("success") else "неизвестно"
        remote_res = run_git_command(["remote", "-v"])
        remote = remote_res.get("stdout", "").strip() if remote_res.get("success") else "не настроен"
        lines.append(f"Ветка: {branch}")
        lines.append(f"Удалённый репозиторий:\n{remote}")

    elif tool_name == "delete_task":
        task_id = kwargs.get("task_id", "")
        lines.append("Действие: Удаление бытовой задачи")
        lines.append(f"Идентификатор / название задачи: {task_id}")

    elif tool_name == "delete_reminder":
        reminder_id = kwargs.get("reminder_id", "")
        lines.append("Действие: Удаление напоминания")
        lines.append(f"Идентификатор / текст напоминания: {reminder_id}")

    elif tool_name == "delete_note":
        note_id = kwargs.get("note_id", "")
        lines.append("Действие: Удаление заметки")
        lines.append(f"Идентификатор / заголовок заметки: {note_id}")

    elif tool_name == "delete_list":
        name = kwargs.get("name", "")
        lines.append("Действие: Удаление списка целиком со всеми пунктами")
        lines.append(f"Имя списка: {name}")

    return "\n".join(lines)


def format_confirmation_details(tool_name, kwargs):
    """
    Выводит детальную информацию перед запросом подтверждения.
    """
    text = get_confirmation_details_text(tool_name, kwargs)
    if text:
        print(text)


def dispatch(tool_name, **kwargs):
    """
    Находит инструмент по имени и запускает его.
    """
    if _action_observer:
        try:
            _action_observer("before_tool", {"tool": tool_name, "kwargs": kwargs})
        except Exception:
            pass

    tool = get_tool(tool_name)

    if tool is None:
        return {
            "success": False,
            "error": f"Инструмент не найден: {tool_name}"
        }

    function = tool["function"]

    if tool.get("requires_confirmation"):
        if _confirmation_handler is not None:
            # Вызываем кастомный обработчик подтверждения (GUI)
            approved = _confirmation_handler(tool_name, kwargs)
            if not approved or (isinstance(approved, str) and approved.strip().lower() not in ["да", "д", "yes", "y"]):
                if _action_observer:
                    try:
                        _action_observer("confirmation_rejected", {"tool": tool_name})
                    except Exception:
                        pass
                return {
                    "success": False,
                    "error": "Пользователь отменил выполнение."
                }
        else:
            print("\n--- Требуется подтверждение ---")
            print(f"Инструмент: {tool_name}")
            format_confirmation_details(tool_name, kwargs)

            confirmation = input("\nРазрешить выполнение? (да/нет): ").strip().lower()

            if confirmation not in ["да", "д", "yes", "y"]:
                return {
                    "success": False,
                    "error": "Пользователь отменил выполнение."
                }

    try:
        result = function(**kwargs)

        if _action_observer:
            try:
                _action_observer("after_tool", {"tool": tool_name, "result": result})
            except Exception:
                pass

        # Если инструмент вернул dict с success=False, транслируем его как ошибку
        if isinstance(result, dict) and not result.get("success", True):
            error_msg = result.get("error") or result.get("message") or "Операция не выполнена."
            error_dict = dict(result)
            error_dict["error"] = error_msg
            return error_dict

        return {
            "success": True,
            "result": result
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }