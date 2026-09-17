from pathlib import Path
import re
import subprocess

PROJECT_PATH = Path(r"C:\Akakiy agent")


def list_files():
    files = []

    for file_path in PROJECT_PATH.rglob("*"):
        if not file_path.is_file():
            continue

        if ".venv" in file_path.parts:
            continue

        if "__pycache__" in file_path.parts:
            continue

        files.append(str(file_path.relative_to(PROJECT_PATH)))

    return {
        "success": True,
        "files": files,
        "count": len(files)
    }


def read_file(filename):
    file_path = PROJECT_PATH / filename

    if not file_path.exists():
        return {
            "success": False,
            "error": f"Файл не найден: {filename}"
        }

    if not file_path.is_file():
        return {
            "success": False,
            "error": f"Это не файл: {filename}"
        }

    try:
        content = file_path.read_text(
            encoding="utf-8"
        )

        return {
            "success": True,
            "filename": filename,
            "content": content
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }


def write_file(filename, content):
    file_path = PROJECT_PATH / filename

    try:
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file_path.write_text(
            content,
            encoding="utf-8"
        )

        return {
            "success": True,
            "filename": filename,
            "message": "Файл записан."
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }


def validate_python_file(file_path):
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
            errors="replace"
        )

        if result.returncode == 0:
            return {
                "success": True,
                "message": "Синтаксис корректен."
            }

        return {
            "success": False,
            "error": result.stderr
        }

    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }


def edit_file(filename, old_text, new_text):
    file_path = PROJECT_PATH / filename

    if not file_path.exists():
        return {
            "success": False,
            "error": f"Файл не найден: {filename}"
        }

    try:
        content = file_path.read_text(
            encoding="utf-8"
        )
    except Exception as error:
        return {
            "success": False,
            "error": str(error)
        }

    if old_text not in content:
        return {
            "success": False,
            "error": "Искомый текст не найден в файле."
        }

    occurrences = content.count(old_text)

    if occurrences > 1:
        return {
            "success": False,
            "error": (
                f"Искомый текст найден {occurrences} раз. "
                "Изменение не выполнено."
            )
        }

    new_content = content.replace(
        old_text,
        new_text,
        1
    )

    import difflib

    diff = "".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=filename,
            tofile=filename
        )
    )

    print("\n--- Предлагаемые изменения ---")
    print(diff)
    print("--- Конец изменений ---")

    confirmation = input(
        "Применить изменения? (да/нет): "
    ).strip().lower()

    if confirmation not in ["да", "д", "yes", "y"]:
        return {
            "success": False,
            "error": "Пользователь отменил изменение."
        }

    backup_path = file_path.with_suffix(
        file_path.suffix + ".bak"
    )

    try:
        backup_path.write_text(
            content,
            encoding="utf-8"
        )

        file_path.write_text(
            new_content,
            encoding="utf-8"
        )

        if file_path.suffix.lower() == ".py":
            validation = validate_python_file(file_path)

            if not validation["success"]:
                file_path.write_text(
                    content,
                    encoding="utf-8"
                )

                return {
                    "success": False,
                    "error": (
                        "Изменение откатено: "
                        f"{validation.get('error', 'ошибка синтаксиса')}"
                    )
                }

        return {
            "success": True,
            "filename": filename,
            "message": "Изменение применено.",
            "backup": str(
                backup_path.relative_to(PROJECT_PATH)
            )
        }

    except Exception as error:
        try:
            file_path.write_text(
                content,
                encoding="utf-8"
            )
        except Exception:
            pass

        return {
            "success": False,
            "error": str(error)
        }


def search_files(query):
    query = query.strip()

    if not query:
        return {
            "success": False,
            "error": "Поисковый запрос пуст."
        }

    function_match = re.fullmatch(
        r"def\s+([A-Za-z_][A-Za-z0-9_]*)",
        query
    )

    function_name = (
        function_match.group(1)
        if function_match
        else None
    )

    matches = []

    for file_path in PROJECT_PATH.rglob("*"):
        if not file_path.is_file():
            continue

        if ".venv" in file_path.parts:
            continue

        if "__pycache__" in file_path.parts:
            continue

        if file_path.suffix.lower() != ".py":
            continue

        try:
            content = file_path.read_text(
                encoding="utf-8-sig"
            )
        except (UnicodeDecodeError, OSError):
            continue

        lines = content.splitlines()

        for line_number, line in enumerate(
            lines,
            start=1
        ):
            if function_name:
                pattern = (
                    rf"^\s*def\s+"
                    rf"{re.escape(function_name)}\s*\("
                )

                if re.search(pattern, line):
                    matches.append({
                        "file": str(
                            file_path.relative_to(
                                PROJECT_PATH
                            )
                        ),
                        "line": line_number,
                        "content": line.strip()
                    })

            elif query.lower() in line.lower():
                matches.append({
                    "file": str(
                        file_path.relative_to(
                            PROJECT_PATH
                        )
                    ),
                    "line": line_number,
                    "content": line.strip()
                })

    return {
        "success": True,
        "query": query,
        "matches": matches,
        "count": len(matches)
    }