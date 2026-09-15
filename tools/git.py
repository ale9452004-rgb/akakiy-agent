import subprocess


PROJECT_PATH = r"C:\Akakiy agent"


def run_git_command(arguments):
    """
    Выполняет Git-команду в проекте.
    """

    try:
        result = subprocess.run(
            [
                "git",
                *arguments
            ],
            cwd=PROJECT_PATH,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Git-команда выполнялась слишком долго.",
            "return_code": -1
        }

    except Exception as error:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(error),
            "return_code": -1
        }


def git_status():
    """
    Показывает состояние Git-репозитория.
    """

    result = run_git_command(
        [
            "status",
            "--short"
        ]
    )

    if not result["success"]:
        return result

    if not result["stdout"].strip():
        result["message"] = "Изменений в Git не обнаружено."
    else:
        result["message"] = "В Git обнаружены изменения."

    return result


def git_diff():
    """
    Показывает текущие изменения Git.
    """

    return run_git_command(
        [
            "diff"
        ]
    )


def get_next_commit_number():
    """
    Определяет следующий номер коммита.

    Ищет коммиты с префиксом:
    001:
    002:
    003:
    """

    result = run_git_command(
        [
            "log",
            "--format=%s"
        ]
    )

    if not result["success"]:
        return {
            "success": False,
            "message": result["stderr"]
        }

    highest_number = 0

    for line in result["stdout"].splitlines():

        if ":" not in line:
            continue

        prefix = line.split(":", 1)[0].strip()

        if not prefix.isdigit():
            continue

        number = int(prefix)

        if number > highest_number:
            highest_number = number

    return {
        "success": True,
        "number": highest_number + 1
    }


def git_commit(message):
    """
    Создаёт Git-коммит с автоматически назначенным номером.

    Перед commit показывает изменения и требует
    явного подтверждения пользователя.
    """

    if not message or not message.strip():
        return {
            "success": False,
            "message": "Описание коммита не может быть пустым."
        }

    status = git_status()

    if not status["success"]:
        return status

    if not status["stdout"].strip():
        return {
            "success": False,
            "message": "Нет изменений для коммита."
        }

    diff = git_diff()

    if not diff["success"]:
        return diff

    number_result = get_next_commit_number()

    if not number_result["success"]:
        return number_result

    number = number_result["number"]

    commit_message = (
        f"{number:03d}: {message.strip()}"
    )

    print("\n--- Изменения перед commit ---")

    if diff["stdout"].strip():
        print(diff["stdout"])
    else:
        print("Изменения отсутствуют.")

    print("--- Конец изменений ---")

    print(
        f"\nПредлагаемый commit: {commit_message}"
    )

    confirmation = input(
        "\nСоздать этот commit? (да/нет): "
    ).strip().lower()

    if confirmation not in ["да", "д", "yes", "y"]:
        return {
            "success": False,
            "message": "Создание commit отменено пользователем."
        }

    result = run_git_command(
        [
            "add",
            "."
        ]
    )

    if not result["success"]:
        return result

    result = run_git_command(
        [
            "commit",
            "-m",
            commit_message
        ]
    )

    if not result["success"]:
        return result

    return {
        "success": True,
        "message": f"Создан commit: {commit_message}",
        "stdout": result["stdout"],
        "commit_message": commit_message
    }