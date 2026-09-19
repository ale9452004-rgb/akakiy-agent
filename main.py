from commands import show_help, show_status
from tools.agent import Agent
from cli_formatters import (
    print_step_result,
    print_plan,
    print_tool_result
)


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("--gui", "-g", "gui"):
        from gui import main as gui_main
        gui_main()
        return

    agent = Agent()

    print("Акакий запущен.")
    print(
        "Я могу общаться, работать с файлами проекта "
        "и выполнять команды."
    )
    print(
        "Команды: 'помощь' — список команд, "
        "'статус' — состояние Акакия, "
        "'выход' — завершить работу."
    )

    while True:

        user_input = input(
            "\nТы: "
        ).strip()

        if not user_input:
            continue

        if user_input.lower() == "выход":

            print(
                "Акакий завершает работу."
            )

            break

        if user_input.lower() == "статус":
            show_status()
            continue

        if user_input.lower() in ("помощь", "help"):
            show_help()
            continue

        try:

            result = agent.process(
                user_input
            )

            # =============================================
            # Обычный чат
            # =============================================

            if result["type"] == "chat":

                print(
                    f"\nАкакий:\n"
                    f"{result['answer']}"
                )

            # =============================================
            # Выполнение плана
            # =============================================

            elif result["type"] == "plan_execution":

                execution_result = result.get(
                    "result"
                )

                print("\nАкакий:")

                if not isinstance(
                    execution_result,
                    dict
                ):

                    print(
                        execution_result
                    )

                    continue

                summary = execution_result.get("summary")
                if summary:
                    print(f"\n{summary}")
                    continue

                results = execution_result.get(
                    "results",
                    []
                )

                if not execution_result.get(
                    "success"
                ):

                    print(
                        f"Ошибка: "
                        f"{execution_result.get('message')}"
                    )

                    if results:

                        print(
                            "\nВыполненные шаги:"
                        )

                        for step_result in results:
                            print_step_result(
                                step_result
                            )

                    continue

                print(
                    "✓ План выполнен."
                )

                print(
                    f"\nВыполнено шагов: "
                    f"{len(results)}"
                )

                for step_result in results:

                    print_step_result(
                        step_result
                    )

                continue

            # =============================================
            # План
            # =============================================

            elif result["type"] == "plan":

                print_plan(
                    result.get("result"),
                    result.get("tool")
                )

                continue

            # =============================================
            # Обычный инструмент
            # =============================================

            elif result["type"] == "tool":

                print_tool_result(
                    result["tool"],
                    result["result"]
                )

                continue

        except Exception as error:

            print(
                f"\nОшибка Акакия: "
                f"{error}"
            )


if __name__ == "__main__":
    main()