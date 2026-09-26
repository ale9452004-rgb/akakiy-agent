from pathlib import Path
import re
import subprocess

from config import PROJECT_PATH


def resolve_safe_path(filename, base_path=None):
    """
    Проверяет и возвращает безопасный Path внутри PROJECT_PATH (или base_path).
    Защищает от Path Traversal, выхода за пределы проекта через '..'
    или абсолютные пути вне проекта.
    Возвращает кортеж (resolved_path, error_dict_or_None).
    """
    if not filename or not str(filename).strip():
        return None, {
            "success": False,
            "error": "Имя файла не может быть пустым."
        }

    try:
        project_resolved = Path(base_path).resolve() if base_path else PROJECT_PATH.resolve()
        raw_path = Path(str(filename).strip())

        if raw_path.is_absolute():
            resolved = raw_path.resolve()
        else:
            resolved = (project_resolved / raw_path).resolve()

        if not resolved.is_relative_to(project_resolved):
            return None, {
                "success": False,
                "error": f"Доступ запрещён: путь выходит за пределы проекта ({filename})."
            }

        return resolved, None

    except Exception as error:
        return None, {
            "success": False,
            "error": f"Некорректный путь к файлу '{filename}': {error}"
        }


def list_files():
    files = []

    for file_path in PROJECT_PATH.rglob("*"):
        if not file_path.is_file():
            continue

        if ".venv" in file_path.parts:
            continue

        if "__pycache__" in file_path.parts:
            continue

        if ".git" in file_path.parts:
            continue

        files.append(str(file_path.relative_to(PROJECT_PATH)))

    return {
        "success": True,
        "files": files,
        "count": len(files)
    }


def find_file(filename):
    filename = filename.strip()

    if not filename:
        return {
            "success": False,
            "error": "Имя файла пустое."
        }

    normalized_filename = filename.replace("\\", "/").strip("/")

    matches = []

    for file_path in PROJECT_PATH.rglob("*"):
        if not file_path.is_file():
            continue

        if ".venv" in file_path.parts:
            continue

        if "__pycache__" in file_path.parts:
            continue

        relative_path = str(
            file_path.relative_to(PROJECT_PATH)
        ).replace("\\", "/")

        if (
            relative_path == normalized_filename
            or file_path.name == normalized_filename
        ):
            matches.append(relative_path)

    return {
        "success": True,
        "filename": filename,
        "matches": matches,
        "count": len(matches)
    }


def read_file(filename, base_path=None):
    file_path, error = resolve_safe_path(filename, base_path=base_path)

    if error:
        return error

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


def write_file(filename, content, base_path=None):
    file_path, error = resolve_safe_path(filename, base_path=base_path)

    if error:
        return error

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


def edit_file(filename, old_text, new_text, base_path=None):
    file_path, error = resolve_safe_path(filename, base_path=base_path)

    if error:
        return error

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

    print("\n--- Применяемые изменения ---")
    print(diff)
    print("--- Конец изменений ---")

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


        target_base = Path(base_path).resolve() if base_path else PROJECT_PATH.resolve()
        backup_str = (
            str(backup_path.relative_to(target_base))
            if backup_path.is_relative_to(target_base)
            else str(backup_path)
        )

        return {
            "success": True,
            "filename": filename,
            "message": "Изменение применено.",
            "backup": backup_str
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