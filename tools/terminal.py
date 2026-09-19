import re
import subprocess

from config import PROJECT_PATH


FORBIDDEN_GIT_PATTERNS = [
    r"\bgit\s+add\b",
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\b",
    r"\bgit\s+restore\b",
    r"\bgit\s+checkout\b",
    r"\bgit\s+branch\s+-[dD]",
    r"\bgit\s+rebase\b",
    r"\bgit\s+merge\b",
]


def run_command(command):
    for pattern in FORBIDDEN_GIT_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return {
                "success": False,
                "error": "Выполнение команд изменения состояния Git (git add, commit, push и др.) через run_command запрещено регламентом безопасности.",
                "stdout": "",
                "stderr": "Операция отклонена: изменение состояния Git через run_command запрещено регламентом безопасности.",
                "return_code": -1
            }

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                command
            ],
            cwd=PROJECT_PATH,
            capture_output=True,
            text=True,
            encoding="cp866",
            errors="replace",
            timeout=120
        )

        success = (result.returncode == 0)
        res = {
            "success": success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }
        if not success:
            res["error"] = result.stderr.strip() or f"Команда завершилась с ошибкой (код {result.returncode})."

        return res

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Команда выполнялась слишком долго и была остановлена.",
            "stdout": "",
            "stderr": "Команда выполнялась слишком долго и была остановлена.",
            "return_code": -1
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "stdout": "",
            "stderr": str(error),
            "return_code": -1
        }