"""
Форматтеры консольного вывода для CLI-режима Акакия.
Выводят результаты выполнения шагов, планов и инструментов.
"""


def print_step_result(step_result):
    """
    Красиво выводит результат выполнения одного шага плана.
    """
    action = step_result.get("action")
    target = step_result.get("target")
    command = step_result.get("command")
    success = step_result.get("success")

    print(f"\nДействие: {action}")

    if target:
        print(f"Цель: {target}")

    if command:
        print(f"Команда: {command}")

    print(
        "Статус: "
        f"{'успешно' if success else 'ошибка'}"
    )

    result = step_result.get("result")

    if not result:
        return

    if not isinstance(result, dict):
        print(f"Результат: {result}")
        return

    # Результат инструмента
    if "result" in result:
        tool_result = result.get("result")

        if isinstance(tool_result, dict):
            message = tool_result.get("message")

            if message:
                print(f"Сообщение: {message}")

            # Результат чтения файла
            content = tool_result.get("content")

            if content is not None:
                lines_count = len(content.splitlines())
                size_kb = len(content.encode("utf-8")) / 1024

                print(
                    f"✓ Файл прочитан. "
                    f"Строк: {lines_count}. "
                    f"Размер: {size_kb:.1f} KB."
                )

            # Результат анализа
            analysis = tool_result.get("analysis")

            if analysis is not None:
                print("\n--- Анализ ---")
                print(analysis)

            # Ошибки
            errors = tool_result.get("errors")

            if errors:
                print("\n--- Ошибки ---")

                for error in errors:
                    print(error)

            # Общий результат
            if (
                message is None
                and content is None
                and analysis is None
                and not errors
            ):
                print("\nРезультат:")
                print(tool_result)

        elif tool_result is not None:
            print("\nРезультат:")
            print(tool_result)

    else:
        print("\nРезультат:")
        print(result)


def print_plan(plan_result, tool_name):
    """
    Выводит информацию о текущем плане.
    """
    print("\nАкакий:")

    if not isinstance(plan_result, dict):
        print(plan_result)
        return

    if not plan_result.get("success"):
        print(
            f"Ошибка: "
            f"{plan_result.get('message')}"
        )

        raw_response = plan_result.get("raw_response")

        if raw_response:
            print("\nОтвет планировщика:")
            print(raw_response)

        return

    # =============================================
    # Создание плана
    # =============================================
    if tool_name == "plan":
        print("✓ План создан.")

        request = plan_result.get("request")
        if request:
            print(f"\nЗадача:\n{request}")

        status = plan_result.get("status")
        if status:
            print(f"\nСтатус: {status}")

        plan = plan_result.get("plan")
        if isinstance(plan, dict):
            steps = plan.get("steps", [])
            print(f"\nШагов: {len(steps)}")

        return

    # =============================================
    # Текущий план
    # =============================================
    if tool_name == "get_current_plan":
        request = plan_result.get("request")
        if request:
            print(f"\nЗадача:\n{request}")

        status = plan_result.get("status")
        if status:
            print(f"\nСтатус: {status}")

        current_step = plan_result.get("current_step")
        if current_step is not None:
            print(f"\nТекущий шаг: {current_step}")

        plan = plan_result.get("plan")
        if not isinstance(plan, dict):
            return

        steps = plan.get("steps", [])
        if steps:
            print("\nПЛАН:")

            for step in steps:
                step_id = step.get("id", "")
                description = step.get("description", "")
                action = step.get("action", "")
                target = step.get("target")
                command = step.get("command")
                details = step.get("details")

                print(f"\n{step_id}. {description}")

                if action:
                    print(f"   Действие: {action}")
                if target:
                    print(f"   Цель: {target}")
                if command:
                    print(f"   Команда: {command}")
                if details:
                    print(f"   Детали: {details}")

        verification = plan.get("verification")
        if verification:
            print("\nПРОВЕРКА:")
            print(verification)

        expected_result = plan.get("expected_result")
        if expected_result:
            print("\nОЖИДАЕМЫЙ РЕЗУЛЬТАТ:")
            print(expected_result)


def print_tool_result(tool_name, tool_result):
    """
    Выводит результат обычного инструмента.
    """
    print(f"\n--- Инструмент: {tool_name} ---")

    if not isinstance(tool_result, dict):
        print(tool_result)
        print("-----------------------------")
        return

    if not tool_result.get("success"):
        error = tool_result.get("error")
        message = tool_result.get("message")

        if error:
            print(f"\nОшибка: {error}")
        elif message:
            print(f"\nАкакий:\n{message}")
        else:
            print(f"\nОшибка: {tool_result}")

        print("-----------------------------")
        return

    value = tool_result.get("result")

    if tool_name == "validate_project":
        if isinstance(value, dict):
            print(f"\nАкакий:\n{value.get('message')}")

            errors = value.get("errors", [])
            if errors:
                print("\n--- Ошибки ---")
                for error in errors:
                    print(f"\nФайл: {error.get('file')}")
                    print(error.get('error'))

            print(f"\nПроверено файлов: {value.get('files_checked', 0)}")

    elif tool_name == "run_command":
        if isinstance(value, dict):
            stdout = value.get("stdout", "")
            stderr = value.get("stderr", "")
            return_code = value.get("return_code")

            if stdout:
                print(f"\nАкакий:\n{stdout}")
            if stderr:
                print(f"\nОшибка:\n{stderr}")

            print(f"\nКод завершения: {return_code}")

    elif tool_name == "git_status":
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
                print(f"\nАкакий:\n✓ {message}")
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
                        f"{index}. {commit.get('hash', '')} — {commit.get('message', '')}\n"
                        f"   Автор: {commit.get('author', '')}\n"
                        f"   Дата: {commit.get('date', '')}\n"
                    )
            print(f"Всего коммитов: {count}")

    elif tool_name == "write_file":
        if isinstance(value, dict):
            message = value.get("message")
            if message:
                print(f"\nАкакий:\n{message}")

    else:
        print(f"\nАкакий:\n{value}")

    print("-----------------------------")
