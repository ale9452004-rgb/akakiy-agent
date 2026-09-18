from pathlib import Path
import subprocess


from config import PROJECT_PATH


def run_git_command(arguments):
    try:
        result = subprocess.run(
            ["git", *arguments],
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
    result = run_git_command(["status", "--short"])

    if not result["success"]:
        return result

    if not result["stdout"].strip():
        result["message"] = "Изменений в Git не обнаружено."
    else:
        result["message"] = "В Git обнаружены изменения."

    return result


def git_diff():
    return run_git_command(["diff"])


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

    # Проверка на конфиденциальные файлы перед индексацией
    sensitive_keywords = [
        ".env", ".key", ".pem", ".pfx", "id_rsa", "id_ed25519", "credentials", "secret", "token"
    ]

    files_to_stage = []
    for line in status["stdout"].splitlines():
        if not line.strip():
            continue
        file_path_str = line[3:].strip()
        file_name_lower = Path(file_path_str).name.lower()
        if any(kw in file_name_lower for kw in sensitive_keywords):
            return {
                "success": False,
                "error": (
                    f"Коммит отклонён из соображений безопасности: обнаружен "
                    f"потенциально конфиденциальный файл '{file_path_str}'. "
                    f"Добавьте его в .gitignore перед коммитом."
                )
            }
        files_to_stage.append(file_path_str)

    if not files_to_stage:
        return {
            "success": False,
            "error": "Нет файлов для коммита."
        }

    print("\n--- Файлы для commit (git status) ---")
    print(status["stdout"].strip())

    print("\n--- Изменения перед commit ---")

    if diff["stdout"].strip():
        print(diff["stdout"])
    else:
        print("Изменения отсутствуют.")

    print("--- Конец изменений ---")

    print(
        f"\nПредлагаемый commit: {commit_message}"
    )

    # Индексируем проверенные файлы
    result = run_git_command(
        [
            "add",
            "--",
            *files_to_stage
        ]
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("stderr") or "Ошибка выполнения git add."
        }

    result = run_git_command(
        [
            "commit",
            "-m",
            commit_message
        ]
    )

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("stderr") or "Ошибка выполнения git commit."
        }

    return {
        "success": True,
        "message": f"Создан commit: {commit_message}",
        "stdout": result["stdout"],
        "commit_message": commit_message
    }


def git_log(limit=10):
    """
    Показывает последние Git-коммиты проекта.
    """

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10

    if limit < 1:
        limit = 10

    if limit > 50:
        limit = 50

    result = run_git_command(
        [
            "log",
            f"-{limit}",
            "--pretty=format:%h|%s|%an|%ad",
            "--date=format:%Y-%m-%d %H:%M"
        ]
    )

    if not result["success"]:
        return result

    commits = []

    for line in result["stdout"].splitlines():

        parts = line.split("|", 3)

        if len(parts) != 4:
            continue

        commits.append({
            "hash": parts[0],
            "message": parts[1],
            "author": parts[2],
            "date": parts[3]
        })

    return {
        "success": True,
        "commits": commits,
        "count": len(commits)
    }

def git_push():
    """
    Отправляет текущую ветку в удалённый Git-репозиторий.
    Перед выполнением требует подтверждение пользователя.
    """

    result = run_git_command(
        [
            "rev-parse",
            "--abbrev-ref",
            "HEAD"
        ]
    )

    if not result["success"]:
        return result

    branch = result["stdout"].strip()

    if not branch:
        return {
            "success": False,
            "error": "Не удалось определить текущую Git-ветку."
        }

    remote_result = run_git_command(
        [
            "remote",
            "-v"
        ]
    )

    if not remote_result["success"]:
        return remote_result

    if not remote_result["stdout"].strip():
        return {
            "success": False,
            "error": "Удалённый Git-репозиторий не настроен."
        }

    print("\n--- Отправка изменений в GitHub ---")
    print(f"Ветка: {branch}")
    print("Удалённый репозиторий:")
    print(remote_result["stdout"])

    push_result = run_git_command(
        [
            "push",
            "origin",
            branch
        ]
    )

    if not push_result["success"]:
        return {
            "success": False,
            "error": push_result.get("stderr") or "Ошибка выполнения git push."
        }

    return {
    "success": True,
    "message": f"Изменения отправлены в GitHub. Ветка: {branch}",
    "stdout": push_result["stdout"],
    "branch": branch
    }