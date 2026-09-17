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

        if result["type"] == "chat":
            print(f"\nАкакий:\n{result['answer']}")

        elif result["type"] == "tool":
            tool_name = result["tool"]
            tool_result = result["result"]

            print(f"\n--- Инструмент: {tool_name} ---")

            if isinstance(tool_result, dict):

                if not tool_result.get("success"):
                    error = tool_result.get("error")
                    message = tool_result.get("message")

                    if error:
                        print(f"\nОшибка: {error}")
                    elif message:
                        print(f"\nАкакий:\n{message}")
                    else:
                        print(f"\nОшибка: {tool_result}")

                else:
                    value = tool_result.get("result")

                    if tool_name == "git_status":
                        if isinstance(value, dict):
                            message = value.get("message")
                            stdout = value.get("stdout", "")
                            stderr = value.get("stderr", "")

                            if message:
                                print(f"\nАкакий:\n{message}")

                            if stdout.strip():
                                print("\nИзменения:")
                                print(stdout)

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_diff":
                        if isinstance(value, dict):
                            stdout = value.get("stdout", "")
                            stderr = value.get("stderr", "")

                            if stdout.strip():
                                print(f"\nАкакий:\n{stdout}")
                            else:
                                print("\nАкакий:\nИзменений нет.")

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_commit":
                        if isinstance(value, dict):
                            message = value.get("message")
                            stdout = value.get("stdout", "")
                            stderr = value.get("stderr", "")

                            if message:
                                print(f"\nАкакий:\n{message}")

                            if stdout.strip():
                                print("\nGit:")
                                print(stdout)

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_push":
                        if isinstance(value, dict):
                            message = value.get("message")
                            branch = value.get("branch")
                            stdout = value.get("stdout", "")
                            stderr = value.get("stderr", "")

                            if message:
                                print("\nАкакий:")
                                print(f"✓ {message}")

                            if branch:
                                print(f"✓ Ветка: {branch}")

                            if stdout.strip():
                                print("\nGit:")
                                print(stdout)

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_log":
                        if isinstance(value, dict):
                            commits = value.get("commits", [])
                            count = value.get("count", 0)

                            print("\nАкакий:\nИстория Git:\n")

                            if not commits:
                                print("Коммитов пока нет.")
                            else:
                                for index, commit in enumerate(commits, start=1):
                                    print(
                                        f"{index}. "
                                        f"{commit.get('hash', '')} — "
                                        f"{commit.get('message', '')}"
                                    )
                                    print(
                                        f"   Автор: {commit.get('author', '')}"
                                    )
                                    print(
                                        f"   Дата: {commit.get('date', '')}"
                                    )
                                    print()

                            print(f"Всего коммитов: {count}")

                    elif tool_name == "run_command" and isinstance(value, dict):
                        stdout = value.get("stdout", "")
                        stderr = value.get("stderr", "")
                        return_code = value.get("return_code")

                        if stdout:
                            print(f"\nАкакий:\n{stdout}")

                        if stderr:
                            print(f"\nОшибка:\n{stderr}")

                        print(f"\nКод завершения: {return_code}")

                    elif tool_name == "write_file" and isinstance(value, dict):
                        message = value.get("message")

                        if message:
                            print(f"\nАкакий:\n{message}")

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

                    elif isinstance(value, tuple):
                        content, error = value

                        if error:
                            print(f"\nОшибка:\n{error}")
                        else:
                            print(f"\nАкакий:\n{content}")

                    else:
                        print(f"\nАкакий:\n{value}")

            elif isinstance(tool_result, list):
                for item in tool_result:
                    print(item)

            else:
                print(f"\nАкакий:\n{tool_result}")

            print("-----------------------------")

    except Exception as error:
        print(f"\nОшибка Акакия: {error}")