from tools.agent import Agent


agent = Agent()


print("Акакий запущен.")
print("Я могу общаться, работать с файлами проекта и выполнять команды.")
print("Для завершения напиши: выход")


while True:
    user_input = input("\nТы: ").strip()

    if not user_input:
        continue

    if user_input.lower() == "выход":
        print("Акакий завершает работу.")
        break

    try:
        result = agent.process(user_input)

        # Обычный ответ ИИ
        if result["type"] == "chat":
            print(f"\nАкакий:\n{result['answer']}")

        # Результат работы инструмента
        elif result["type"] == "tool":
            tool_name = result["tool"]
            tool_result = result["result"]

            print(f"\n--- Инструмент: {tool_name} ---")

            if isinstance(tool_result, dict):

                if tool_result.get("success"):
                    value = tool_result.get("result")

                    # Выполнение PowerShell-команды
                    if tool_name == "run_command" and isinstance(value, dict):

                        stdout = value.get("stdout", "")
                        stderr = value.get("stderr", "")
                        return_code = value.get("return_code")

                        if stdout:
                            print(f"\nАкакий:\n{stdout}")

                        if stderr:
                            print(f"\nОшибка:\n{stderr}")

                        print(f"\nКод завершения: {return_code}")

                    # Запись файла
                    elif tool_name == "write_file" and isinstance(value, dict):

                        message = value.get("message")

                        if message:
                            print(f"\nАкакий:\n{message}")

                    # Проверка всего проекта
                    elif tool_name == "validate_project" and isinstance(value, dict):

                        print(f"\nАкакий:\n{value.get('message')}")

                        errors = value.get("errors", [])

                        if errors:
                            print("\n--- Ошибки ---")

                            for error in errors:
                                print(f"\nФайл: {error.get('file')}")
                                print(error.get("error"))

                        print(
                            f"\nПроверено файлов: "
                            f"{value.get('files_checked', 0)}"
                        )

                    # Чтение файла
                    elif isinstance(value, tuple):

                        content, error = value

                        if error:
                            print(f"\nОшибка:\n{error}")
                        else:
                            print(f"\nАкакий:\n{content}")

                    # Обычный результат инструмента
                    else:
                        print(f"\nАкакий:\n{value}")

                else:
                    print(f"\nОшибка: {tool_result.get('error')}")

            elif isinstance(tool_result, list):

                for item in tool_result:
                    print(item)

            else:
                print(f"\nАкакий:\n{tool_result}")

            print("-----------------------------")

    except Exception as error:
        print(f"\nОшибка Акакия: {error}")