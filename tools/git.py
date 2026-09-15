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