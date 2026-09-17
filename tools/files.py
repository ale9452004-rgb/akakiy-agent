from pathlib import Path
import difflib
import shutil
import subprocess


PROJECT_PATH = Path(r"C:\Akakiy agent")


def list_files():
    """Возвращает список файлов и папок проекта."""

    items = []

    for item in sorted(PROJECT_PATH.iterdir()):
        if item.name in [".venv", "__pycache__"]:
            continue

        if item.is_dir():
            items.append(f"[ПАПКА] {item.name}")
        else:
            items.append(f"[ФАЙЛ]  {item.name}")

    return items


def read_file(filename):
    """Читает файл проекта."""

    file_path = PROJECT_PATH / filename

    if not file_path.exists():
        return {
            "success": False,
            "filename": filename,
            "message": f"Файл не найден: {filename}"
        }

    if not file_path.is_file():
        return {
            "success": False,
            "filename": filename,
            "message": f"Это не файл: {filename}"
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
            "filename": filename,
            "message": (
                f"Ошибка чтения файла: {error}"
            )
        }


def write_file(filename, content):
    """Записывает содержимое в файл проекта."""

    file_path = PROJECT_PATH / filename

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(
            content,
            encoding="utf-8"
        )

        return {
            "success": True,
            "filename": filename,
            "message": f"Файл записан: {filename}"
        }

    except Exception as error:
        return {
            "success": False,
            "filename": filename,
            "message": f"Ошибка записи файла: {error}"
        }


def validate_python_file(file_path):
    """
    Проверяет Python-файл на синтаксические ошибки.
    """

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
            "stderr": "Проверка Python выполнялась слишком долго.",
            "return_code": -1
        }

    except Exception as error:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(error),
            "return_code": -1
        }


def edit_file(filename, old_text, new_text):
    """
    Точечно изменяет существующий файл.

    Перед изменением показывает diff.
    После подтверждения создаёт резервную копию.
    После записи проверяет Python-файлы.
    При ошибке автоматически восстанавливает резервную копию.
    """

    file_path = PROJECT_PATH / filename

    if not file_path.exists():
        return {
            "success": False,
            "message": f"Файл не найден: {filename}"
        }

    if not file_path.is_file():
        return {
            "success": False,
            "message": f"Это не файл: {filename}"
        }

    try:
        current_content = file_path.read_text(
            encoding="utf-8"
        )

    except Exception as error:
        return {
            "success": False,
            "message": f"Ошибка чтения файла: {error}"
        }

    if not old_text:
        return {
            "success": False,
            "message": "Старый фрагмент для замены пустой."
        }

    occurrences = current_content.count(old_text)

    if occurrences == 0:
        return {
            "success": False,
            "message": (
                "Исходный фрагмент не найден в файле. "
                "Файл не изменён."
            )
        }

    if occurrences > 1:
        return {
            "success": False,
            "message": (
                f"Исходный фрагмент найден {occurrences} раз. "
                "Изменение отменено для безопасности."
            )
        }

    new_content = current_content.replace(
        old_text,
        new_text,
        1
    )

    diff = list(
        difflib.unified_diff(
            current_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"{filename} (текущий)",
            tofile=f"{filename} (новый)",
            lineterm=""
        )
    )

    if not diff:
        return {
            "success": False,
            "message": "Изменений нет."
        }

    print("\n--- Предлагаемые изменения ---")

    for line in diff:
        print(line)

    print("--- Конец изменений ---")

    confirmation = input(
        "\nПрименить изменения? (да/нет): "
    ).strip().lower()

    if confirmation not in ["да", "д", "yes", "y"]:
        return {
            "success": False,
            "message": "Изменение отменено пользователем."
        }

    # Создаём резервную копию
    backup_path = file_path.with_suffix(
        file_path.suffix + ".bak"
    )

    try:
        shutil.copy2(
            file_path,
            backup_path
        )

    except Exception as error:
        return {
            "success": False,
            "message": (
                "Не удалось создать резервную копию. "
                f"Файл не изменён.\nОшибка: {error}"
            )
        }

    # Записываем новое содержимое
    try:
        file_path.write_text(
            new_content,
            encoding="utf-8"
        )

    except Exception as error:
        return {
            "success": False,
            "message": (
                "Ошибка записи файла. "
                f"Резервная копия сохранена: {backup_path.name}\n"
                f"Ошибка: {error}"
            )
        }

    # Проверяем Python-файл
    if file_path.suffix.lower() == ".py":

        validation = validate_python_file(
            file_path
        )

        if not validation["success"]:

            print("\n--- Обнаружена ошибка Python ---")

            if validation["stderr"]:
                print(validation["stderr"])

            print("\nВосстанавливаю резервную копию...")

            try:
                shutil.copy2(
                    backup_path,
                    file_path
                )

                return {
                    "success": False,
                    "message": (
                        f"Изменение отменено автоматически.\n"
                        f"Файл восстановлен из: {backup_path.name}\n"
                        f"Причина: ошибка Python."
                    )
                }

            except Exception as error:
                return {
                    "success": False,
                    "message": (
                        "КРИТИЧЕСКАЯ ОШИБКА: "
                        "не удалось восстановить файл.\n"
                        f"Резервная копия: {backup_path}\n"
                        f"Ошибка восстановления: {error}"
                    )
                }

    return {
        "success": True,
        "filename": filename,
        "backup": str(backup_path),
        "message": (
            f"Изменения применены: {filename}\n"
            f"Резервная копия: {backup_path.name}\n"
            f"Проверка: успешно"
        )
    }

def search_files(query):
    """
    Ищет текст во всех файлах проекта.

    Если запрос имеет вид:
        def имя_функции

    выполняется более точный поиск определения функции,
    а не обычного текстового совпадения.
    """

    import re

    matches = []

    # Нормализуем запрос
    query = query.strip()

    # Определяем, является ли запрос поиском функции
    function_match = re.fullmatch(
        r"def\s+([A-Za-z_][A-Za-z0-9_]*)",
        query
    )

    function_name = None

    if function_match:
        function_name = function_match.group(1)

    # Перебираем файлы проекта
    for file_path in PROJECT_PATH.rglob("*"):

        # Пропускаем директории
        if not file_path.is_file():
            continue

        # Пропускаем виртуальное окружение
        if ".venv" in file_path.parts:
            continue

        # Пропускаем кэш Python
        if "__pycache__" in file_path.parts:
            continue

        try:
            content = file_path.read_text(
                encoding="utf-8"
            )
        except (
            UnicodeDecodeError,
            PermissionError,
            OSError
        ):
            continue

        lines = content.splitlines()

        for line_number, line in enumerate(
            lines,
            start=1
        ):

            # =========================================
            # Точный поиск определения функции
            # =========================================

            if function_name:

                pattern = (
                    rf"^\s*def\s+"
                    rf"{re.escape(function_name)}"
                    rf"\s*\("
                )

                if re.search(pattern, line):

                    matches.append(
                        {
                            "file": str(
                                file_path.relative_to(
                                    PROJECT_PATH
                                )
                            ),
                            "line": line_number,
                            "content": line.strip()
                        }
                    )

                continue

            # =========================================
            # Обычный поиск текста
            # =========================================

            if query.lower() in line.lower():

                matches.append(
                    {
                        "file": str(
                            file_path.relative_to(
                                PROJECT_PATH
                            )
                        ),
                        "line": line_number,
                        "content": line.strip()
                    }
                )

    return {
        "success": True,
        "query": query,
        "matches": matches,
        "count": len(matches)
    }