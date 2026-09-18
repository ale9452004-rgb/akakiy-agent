from tools.registry import get_tool


def format_confirmation_details(tool_name, kwargs):
    """
    Выводит детальную информацию перед запросом подтверждения.
    """
    if tool_name == "run_command":
        command = kwargs.get("command", "")
        print(f"Команда: {command}")

    elif tool_name == "write_file":
        filename = kwargs.get("filename", "")
        content = kwargs.get("content", "")
        size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0
        print(f"Файл: {filename}")
        print(f"Размер содержимого: {size_bytes} байт")

    elif tool_name == "edit_file":
        filename = kwargs.get("filename", "")
        old_text = kwargs.get("old_text", "")
        new_text = kwargs.get("new_text", "")
        print(f"Файл: {filename}")
        print("Замена текста:")
        old_preview = old_text if len(old_text) <= 120 else old_text[:117] + "..."
        new_preview = new_text if len(new_text) <= 120 else new_text[:117] + "..."
        print(f"  Было:  {old_preview}")
        print(f"  Стало: {new_preview}")

    elif tool_name == "git_commit":
        message = kwargs.get("message", "")
        print(f"Сообщение коммита: {message}")
        from tools.git import git_status
        status = git_status()
        if status.get("success") and status.get("stdout", "").strip():
            print("Изменения для коммита:")
            for line in status["stdout"].splitlines():
                print(f"  {line}")
        else:
            print("Изменения: нет обнаруженных изменений")

    elif tool_name == "git_push":
        from tools.git import run_git_command
        branch_res = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch_res.get("stdout", "").strip() if branch_res.get("success") else "неизвестно"
        remote_res = run_git_command(["remote", "-v"])
        remote = remote_res.get("stdout", "").strip() if remote_res.get("success") else "не настроен"
        print(f"Ветка: {branch}")
        print(f"Удалённый репозиторий:\n{remote}")


def dispatch(tool_name, **kwargs):
    """
    Находит инструмент по имени и запускает его.
    """

    tool = get_tool(tool_name)

    if tool is None:
        return {
            "success": False,
            "error": f"Инструмент не найден: {tool_name}"
        }

    function = tool["function"]

    if tool.get("requires_confirmation"):
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

        # Если инструмент вернул dict с success=False, транслируем его как ошибку
        if isinstance(result, dict) and not result.get("success", True):
            error_msg = result.get("error") or result.get("message") or "Операция не выполнена."
            return {
                "success": False,
                "error": error_msg
            }

        return {
            "success": True,
            "result": result
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }