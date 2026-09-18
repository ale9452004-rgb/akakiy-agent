from pathlib import Path
import subprocess


from config import PROJECT_PATH


def validate_project():
    """
    Проверяет все Python-файлы проекта на синтаксические ошибки.
    """

    python_files = []

    for file_path in PROJECT_PATH.rglob("*.py"):
        if ".venv" in file_path.parts:
            continue

        if "__pycache__" in file_path.parts:
            continue

        python_files.append(file_path)

    python_files.sort()

    if not python_files:
        return {
            "success": True,
            "files_checked": 0,
            "errors": [],
            "message": "Python-файлы для проверки не найдены."
        }

    errors = []

    for file_path in python_files:
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "py_compile",
                    str(file_path)
                ],
                cwd=PROJECT_PATH,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )

            if result.returncode != 0:
                errors.append({
                    "file": str(
                        file_path.relative_to(PROJECT_PATH)
                    ),
                    "error": result.stderr.strip()
                })

        except subprocess.TimeoutExpired:
            errors.append({
                "file": str(
                    file_path.relative_to(PROJECT_PATH)
                ),
                "error": "Проверка выполнялась слишком долго."
            })

        except Exception as error:
            errors.append({
                "file": str(
                    file_path.relative_to(PROJECT_PATH)
                ),
                "error": str(error)
            })

    if errors:
        return {
            "success": False,
            "files_checked": len(python_files),
            "errors": errors,
            "message": (
                f"Проверка завершена. "
                f"Найдено ошибок: {len(errors)}."
            )
        }

    return {
        "success": True,
        "files_checked": len(python_files),
        "errors": [],
        "message": (
            f"Проверка завершена успешно. "
            f"Проверено Python-файлов: {len(python_files)}."
        )
    }