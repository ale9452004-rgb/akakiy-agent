import subprocess

from config import PROJECT_PATH


def run_command(command):
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

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Команда выполнялась слишком долго и была остановлена.",
            "return_code": -1
        }

    except Exception as error:
        return {
            "stdout": "",
            "stderr": str(error),
            "return_code": -1
        }