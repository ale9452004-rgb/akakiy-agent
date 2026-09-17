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

        elif result["type"] == "plan":
            plan_result = result.get("result")

            print("\nАкакий:")

            if not isinstance(plan_result, dict):
                print(plan_result)
                continue

            if not plan_result.get("success"):
                print(
                    f"Ошибка: "
                    f"{plan_result.get('message')}"
                )

                raw_response = plan_result.get(
                    "raw_response"
                )

                if raw_response:
                    print("\nОтвет планировщика:")
                    print(raw_response)

                continue

            tool_name = result.get("tool")

            # -------------------------------------------------
            # Создание нового плана
            # -------------------------------------------------

            if tool_name == "plan":

                print("✓ План создан.")

                request = plan_result.get(
                    "request"
                )

                if request:
                    print(
                        f"\nЗадача:\n{request}"
                    )

                status = plan_result.get(
                    "status"
                )

                if status:
                    print(
                        f"\nСтатус: {status}"
                    )

                plan = plan_result.get(
                    "plan"
                )

                if isinstance(plan, dict):

                    steps = plan.get(
                        "steps",
                        []
                    )

                    print(
                        f"\nШагов: "
                        f"{len(steps)}"
                    )

                continue

            # -------------------------------------------------
            # Просмотр текущего плана
            # -------------------------------------------------

            if tool_name == "get_current_plan":

                request = plan_result.get(
                    "request"
                )

                if request:
                    print(
                        f"\nЗадача:\n{request}"
                    )

                status = plan_result.get(
                    "status"
                )

                if status:
                    print(
                        f"\nСтатус: {status}"
                    )

                current_step = plan_result.get(
                    "current_step"
                )

                if current_step is not None:
                    print(
                        f"\nТекущий шаг: "
                        f"{current_step}"
                    )

                plan = plan_result.get(
                    "plan"
                )

                if isinstance(plan, dict):

                    steps = plan.get(
                        "steps",
                        []
                    )

                    if steps:
                        print("\nПЛАН:")

                        for step in steps:

                            step_id = step.get(
                                "id",
                                ""
                            )

                            description = step.get(
                                "description",
                                ""
                            )

                            action = step.get(
                                "action",
                                ""
                            )

                            target = step.get(
                                "target"
                            )

                            command = step.get(
                                "command"
                            )

                            print(
                                f"\n{step_id}. "
                                f"{description}"
                            )

                            if action:
                                print(
                                    f"   Действие: "
                                    f"{action}"
                                )

                            if target:
                                print(
                                    f"   Цель: "
                                    f"{target}"
                                )

                            if command:
                                print(
                                    f"   Команда: "
                                    f"{command}"
                                )

                    verification = plan.get(
                        "verification"
                    )

                    if verification:
                        print(
                            "\nПРОВЕРКА:"
                        )
                        print(
                            verification
                        )

                    expected_result = plan.get(
                        "expected_result"
                    )

                    if expected_result:
                        print(
                            "\nОЖИДАЕМЫЙ РЕЗУЛЬТАТ:"
                        )
                        print(
                            expected_result
                        )

                continue

        elif result["type"] == "tool":
            tool_name = result["tool"]
            tool_result = result["result"]

            print(
                f"\n--- Инструмент: {tool_name} ---"
            )

            if isinstance(tool_result, dict):

                if not tool_result.get("success"):
                    error = tool_result.get("error")
                    message = tool_result.get("message")

                    if error:
                        print(f"\nОшибка: {error}")

                    elif message:
                        print(f"\nАкакий:\n{message}")

                    else:
                        print(
                            f"\nОшибка: "
                            f"{tool_result}"
                        )

                else:
                    value = tool_result.get("result")

                    if tool_name == "git_status":

                        if isinstance(value, dict):
                            message = value.get("message")
                            stdout = value.get(
                                "stdout",
                                ""
                            )
                            stderr = value.get(
                                "stderr",
                                ""
                            )

                            if message:
                                print(
                                    f"\nАкакий:\n"
                                    f"{message}"
                                )

                            if stdout.strip():
                                print(
                                    "\nИзменения:"
                                )
                                print(stdout)

                            if stderr.strip():
                                print(
                                    "\nОшибка:"
                                )
                                print(stderr)

                    elif tool_name == "git_diff":

                        if isinstance(value, dict):
                            stdout = value.get(
                                "stdout",
                                ""
                            )
                            stderr = value.get(
                                "stderr",
                                ""
                            )

                            if stdout.strip():
                                print(
                                    f"\nАкакий:\n"
                                    f"{stdout}"
                                )

                            else:
                                print(
                                    "\nАкакий:\n"
                                    "Изменений нет."
                                )

                            if stderr.strip():
                                print(
                                    "\nОшибка:"
                                )
                                print(stderr)

                    elif tool_name == "git_commit":

                        if isinstance(value, dict):
                            message = value.get(
                                "message"
                            )
                            stdout = value.get(
                                "stdout",
                                ""
                            )
                            stderr = value.get(
                                "stderr",
                                ""
                            )

                            if message:
                                print(
                                    f"\nАкакий:\n"
                                    f"{message}"
                                )

                            if stdout.strip():
                                print("\nGit:")
                                print(stdout)

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_push":

                        if isinstance(value, dict):
                            message = value.get(
                                "message"
                            )
                            branch = value.get(
                                "branch"
                            )
                            stdout = value.get(
                                "stdout",
                                ""
                            )
                            stderr = value.get(
                                "stderr",
                                ""
                            )

                            if message:
                                print("\nАкакий:")
                                print(
                                    f"✓ {message}"
                                )

                            if branch:
                                print(
                                    f"✓ Ветка: "
                                    f"{branch}"
                                )

                            if stdout.strip():
                                print("\nGit:")
                                print(stdout)

                            if stderr.strip():
                                print("\nОшибка:")
                                print(stderr)

                    elif tool_name == "git_log":

                        if isinstance(value, dict):
                            commits = value.get(
                                "commits",
                                []
                            )
                            count = value.get(
                                "count",
                                0
                            )

                            print(
                                "\nАкакий:\n"
                                "История Git:\n"
                            )

                            if not commits:
                                print(
                                    "Коммитов пока нет."
                                )

                            else:
                                for (
                                    index,
                                    commit
                                ) in enumerate(
                                    commits,
                                    start=1
                                ):
                                    print(
                                        f"{index}. "
                                        f"{commit.get('hash', '')} "
                                        f"— "
                                        f"{commit.get('message', '')}"
                                    )

                                    print(
                                        f"   Автор: "
                                        f"{commit.get('author', '')}"
                                    )

                                    print(
                                        f"   Дата: "
                                        f"{commit.get('date', '')}"
                                    )

                                    print()

                            print(
                                f"Всего коммитов: "
                                f"{count}"
                            )

                    elif (
                        tool_name == "run_command"
                        and isinstance(value, dict)
                    ):
                        stdout = value.get(
                            "stdout",
                            ""
                        )
                        stderr = value.get(
                            "stderr",
                            ""
                        )
                        return_code = value.get(
                            "return_code"
                        )

                        if stdout:
                            print(
                                f"\nАкакий:\n"
                                f"{stdout}"
                            )

                        if stderr:
                            print(
                                f"\nОшибка:\n"
                                f"{stderr}"
                            )

                        print(
                            f"\nКод завершения: "
                            f"{return_code}"
                        )

                    elif (
                        tool_name == "write_file"
                        and isinstance(value, dict)
                    ):
                        message = value.get(
                            "message"
                        )

                        if message:
                            print(
                                f"\nАкакий:\n"
                                f"{message}"
                            )

                    elif (
                        tool_name == "validate_project"
                        and isinstance(value, dict)
                    ):
                        print(
                            f"\nАкакий:\n"
                            f"{value.get('message')}"
                        )

                        errors = value.get(
                            "errors",
                            []
                        )

                        if errors:
                            print(
                                "\n--- Ошибки ---"
                            )

                            for error in errors:
                                print(
                                    f"\nФайл: "
                                    f"{error.get('file')}"
                                )

                                print(
                                    error.get(
                                        "error"
                                    )
                                )

                        print(
                            f"\nПроверено файлов: "
                            f"{value.get('files_checked', 0)}"
                        )

                    elif isinstance(
                        value,
                        tuple
                    ):
                        content, error = value

                        if error:
                            print(
                                f"\nОшибка:\n"
                                f"{error}"
                            )

                        else:
                            print(
                                f"\nАкакий:\n"
                                f"{content}"
                            )

                    else:
                        print(
                            f"\nАкакий:\n"
                            f"{value}"
                        )

            elif isinstance(
                tool_result,
                list
            ):

                for item in tool_result:
                    print(item)

            else:
                print(
                    f"\nАкакий:\n"
                    f"{tool_result}"
                )

            print(
                "-----------------------------"
            )

    except Exception as error:
        print(
            f"\nОшибка Акакия: {error}"
        )