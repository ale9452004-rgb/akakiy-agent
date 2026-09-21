import sys
from pathlib import Path
import requests


from config import PROJECT_PATH
from tools.backup import export_data, import_data


def show_status():
    print("\n--- Статус Акакия ---")
    print(f"Проект: {PROJECT_PATH}")
    print(f"Python: {sys.version.split()[0]}")
    print("Модель: qwen3:8b")

    ollama_status = "недоступен"
    system_status = "ошибка (нет связи с Ollama)"

    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=3)
        if response.status_code == 200:
            models = [m.get("name", "") for m in response.json().get("models", [])]
            if any("qwen3:8b" in m for m in models):
                ollama_status = "подключён"
                system_status = "работает"
            else:
                ollama_status = "подключён (модель qwen3:8b не найдена)"
                system_status = "требуется загрузка модели"
        else:
            ollama_status = f"ошибка (HTTP {response.status_code})"
            system_status = "сервис недоступен"
    except requests.RequestException:
        ollama_status = "недоступен (сервер не запущен)"
        system_status = "ошибка (нет связи с Ollama)"

    print(f"Ollama: {ollama_status}")
    print(f"Статус: {system_status}")
    print("---------------------")


def show_help():
    print("\n--- Справка по командам Акакия ---")
    print("Быстрые команды CLI:")
    print("  :status, :s, статус      - показать статус системы")
    print("  :files, :ls, files       - список файлов проекта")
    print("  :read <файл>, :cat <файл> - просмотреть содержимое файла")
    print("  :export [файл]           - экспортировать данные в JSON")
    print("  :import <файл>           - импортировать данные из backup-файла")
    print("  :help, :h, помощь        - показать эту справку")
    print("  :exit, :quit, выход      - завершить работу")
    print("\nРабота с планами:")
    print("  план: <задача>           - составить план выполнения задачи")
    print("  покажи план              - показать текущий план")
    print("  выполни план             - запустить текущий план на выполнение")
    print("  очисти план              - сбросить текущий план")
    print("\nПамять и контекст:")
    print("  запомни: <факт>          - сохранить факт в долговременную память")
    print("  что ты помнишь           - показать все сохранённые воспоминания")
    print("  найди в памяти: <текст>  - найти факты в памяти (или 'вспомни: <текст>')")
    print("  забудь: <id или текст>   - удалить запись из памяти по номеру или тексту")
    print("  очисти память            - полностью стереть долговременную память")
    print("\nЗапросы к инструментам:")
    print("  покажи список файлов     - список всех файлов проекта")
    print("  найди файл <имя>         - найти файл по имени в проекте")
    print("  найди функцию <имя>      - найти определение функции в кодовой базе")
    print("  поиск по проекту <текст> - найти текст в файлах проекта")
    print("----------------------------------")


# =====================================================================
# Вспомогательные функции быстрого доступа CLI
# =====================================================================

def show_files():
    """Выводит список файлов проекта в консоль."""
    from tools.files import list_files

    print("\n--- Файлы проекта ---")

    result = list_files()
    files = result.get("files", []) if isinstance(result, dict) else result

    for item in files:
        print(item)

    print("---------------------")


def read_file(filename):
    """Читает файл проекта и возвращает его содержимое."""
    from tools.files import read_file as tool_read_file

    result = tool_read_file(filename)

    if not result.get("success", False):
        print(f"\n{result.get('error', 'Ошибка чтения файла')}")
        return None

    return result.get("content")


def _safe_print(text: str = ""):
    """Безопасный вывод строки в консоль с защитой от UnicodeEncodeError."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_bytes = str(text).encode(encoding, errors="replace")
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(safe_bytes + b"\n")
            sys.stdout.buffer.flush()
        else:
            print(safe_bytes.decode(encoding, errors="replace"))


def handle_cli_command(user_input: str) -> bool:
    """
    Обрабатывает быстрые команды CLI REPL (алиасы :status, :files, :read, :help и т.д.).
    Возвращает True, если ввод был распознан и обработан как CLI-команда,
    или False, если ввод должен быть передан дальше в Agent.process().
    """
    if not user_input or not isinstance(user_input, str):
        return False

    raw = user_input.strip()
    if not raw:
        return False

    cmd_lower = raw.lower()

    # 1. Статус
    if cmd_lower in (":status", ":статус", ":s", "статус", "status", "show_status"):
        show_status()
        return True

    # 2. Справка
    if cmd_lower in (":help", ":помощь", ":h", ":?", "?", "помощь", "help", "show_help"):
        show_help()
        return True

    # 3. Список файлов проекта
    if cmd_lower in (":files", ":файлы", ":ls", ":dir", ":f", "files", "show_files"):
        show_files()
        return True

    # 4. Чтение файла проекта
    parts = raw.split(maxsplit=1)
    first_token = parts[0].lower()

    read_command_tokens = (":read", ":cat", ":read_file", ":view", ":прочитай", "read_file")

    def _display_file(fname: str):
        content = read_file(fname)
        if content is not None:
            content = content.lstrip("\ufeff")
            _safe_print(f"\n--- {fname} ---")
            if content:
                _safe_print(content)
            else:
                _safe_print("(файл пуст)")
            _safe_print("---------------------")

    if first_token in read_command_tokens:
        if len(parts) == 1:
            print("\nИспользование: :read <путь_к_файлу> или :cat <путь_к_файлу>")
            return True

        filename = parts[1].strip("'\"")
        if not filename:
            print("\nИспользование: :read <путь_к_файлу> или :cat <путь_к_файлу>")
            return True

        _display_file(filename)
        return True

    # Алиас "cat <filename>" (только если аргумент явно указан)
    if first_token == "cat" and len(parts) == 2:
        filename = parts[1].strip("'\"")
        if filename:
            _display_file(filename)
            return True

    # 5. Экспорт данных
    if first_token in (":export", ":экспорт", "export"):
        target_file = parts[1].strip("'\"") if len(parts) > 1 else None
        res = export_data(output_path=target_file)
        if res.get("success"):
            _safe_print(f"\n✓ {res.get('message')}")
            _safe_print(f"Путь: {res.get('path')}")
            stats = res.get("stats", {})
            _safe_print(
                f"Статистика: задач={stats.get('tasks_count')}, "
                f"напоминаний={stats.get('reminders_count')}, "
                f"заметок={stats.get('notes_count')}, "
                f"списков={stats.get('lists_count')}, "
                f"памяти={stats.get('memories_count')}"
            )
        else:
            _safe_print(f"\n✗ Ошибка экспорта: {res.get('error')}")
        return True

    # 6. Импорт данных
    if first_token in (":import", ":импорт"):
        if len(parts) == 1:
            _safe_print("\nИспользование: :import <путь_к_backup_файлу>")
            return True

        source_file = parts[1].strip("'\"")
        if not source_file:
            _safe_print("\nИспользование: :import <путь_к_backup_файлу>")
            return True

        res = import_data(input_path=source_file)
        if res.get("success"):
            _safe_print(f"\n✓ {res.get('message')}")
            stats = res.get("stats", {})
            _safe_print(
                f"Статистика: задач={stats.get('tasks_count')}, "
                f"напоминаний={stats.get('reminders_count')}, "
                f"заметок={stats.get('notes_count')}, "
                f"списков={stats.get('lists_count')}, "
                f"памяти={stats.get('memories_count')}"
            )
        else:
            _safe_print(f"\n✗ Ошибка импорта: {res.get('error')}")
        return True

    return False