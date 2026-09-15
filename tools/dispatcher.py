from tools.registry import get_tool


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

    if tool["requires_confirmation"]:
        print("\n--- Требуется подтверждение ---")
        print(f"Инструмент: {tool_name}")

        confirmation = input("Разрешить выполнение? (да/нет): ").strip().lower()

        if confirmation not in ["да", "д", "yes", "y"]:
            return {
                "success": False,
                "error": "Пользователь отменил выполнение."
            }

    try:
        result = function(**kwargs)

        return {
            "success": True,
            "result": result
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }