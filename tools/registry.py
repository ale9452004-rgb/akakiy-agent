from tools.files import (
    list_files,
    read_file,
    write_file,
    edit_file
)

from tools.terminal import run_command
from tools.analysis import analyze_file
from tools.validation import validate_project
from tools.git import (
    git_status,
    git_diff,
    git_commit,
    git_log,
    git_push
)


TOOLS = {
    "list_files": {
        "function": list_files,
        "description": "Показывает список файлов проекта.",
        "requires_confirmation": False
    },

    "read_file": {
        "function": read_file,
        "description": "Читает содержимое указанного файла.",
        "requires_confirmation": False
    },

    "write_file": {
        "function": write_file,
        "description": "Создаёт или полностью перезаписывает файл.",
        "requires_confirmation": True
    },

    "edit_file": {
        "function": edit_file,
        "description": "Точечно изменяет существующий файл.",
        "requires_confirmation": False
    },

    "run_command": {
        "function": run_command,
        "description": "Выполняет PowerShell-команду в проекте.",
        "requires_confirmation": True
    },

    "analyze_file": {
        "function": analyze_file,
        "description": "Анализирует указанный файл без изменения кода.",
        "requires_confirmation": False
    },

    "validate_project": {
        "function": validate_project,
        "description": "Проверяет Python-файлы проекта на синтаксические ошибки.",
        "requires_confirmation": False
    },

    "git_status": {
        "function": git_status,
        "description": "Показывает текущее состояние Git-репозитория.",
        "requires_confirmation": False
    },

    "git_diff": {
        "function": git_diff,
        "description": "Показывает изменения в Git-репозитории.",
        "requires_confirmation": False
    },

    "git_commit": {
        "function": git_commit,
        "description": "Создаёт Git-коммит после показа изменений и подтверждения.",
        "requires_confirmation": False
    },

    "git_log": {
        "function": git_log,
        "description": "Показывает историю последних Git-коммитов.",
        "requires_confirmation": False
    },

    "git_push": {
        "function": git_push,
        "description": "Отправляет текущую ветку Git в удалённый репозиторий.",
        "requires_confirmation": False
    }
}


def get_tool(name):
    return TOOLS.get(name)


def get_tools_description():
    descriptions = []

    for name, tool in TOOLS.items():
        descriptions.append(
            f"- {name}: {tool['description']}"
        )

    return "\n".join(descriptions)