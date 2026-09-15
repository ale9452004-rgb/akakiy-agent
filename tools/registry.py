from tools.files import (
    list_files,
    read_file,
    write_file,
    edit_file
)

from tools.terminal import run_command
from tools.analysis import analyze_file
from tools.validation import validate_project
from tools.git import git_status, git_diff

TOOLS = {
    "list_files": {
        "description": "Показывает список файлов и папок проекта.",
        "function": list_files,
        "requires_confirmation": False,
    },

    "read_file": {
        "description": "Читает содержимое указанного файла проекта.",
        "function": read_file,
        "requires_confirmation": False,
    },

    "write_file": {
        "description": "Записывает содержимое в файл проекта. Может создать новый файл или полностью заменить существующий.",
        "function": write_file,
        "requires_confirmation": True,
    },

    "edit_file": {
        "description": "Точечно изменяет существующий файл через old_text и new_text с показом diff.",
        "function": edit_file,
        "requires_confirmation": False,
    },

    "run_command": {
        "description": "Выполняет PowerShell-команду в проекте.",
        "function": run_command,
        "requires_confirmation": True,
    },

    "analyze_file": {
        "description": "Анализирует указанный файл и ищет проблемы и улучшения.",
        "function": analyze_file,
        "requires_confirmation": False,
    },

    "validate_project": {
        "description": "Проверяет все Python-файлы проекта на синтаксические ошибки.",
        "function": validate_project,
        "requires_confirmation": False,
    },

    "git_status": {
        "description": "Показывает изменённые и новые файлы Git-репозитория проекта.",
        "function": git_status,
        "requires_confirmation": False,
    },

    "git_diff": {
        "description": "Показывает подробные изменения файлов Git-репозитория.",
        "function": git_diff,
        "requires_confirmation": False,
    },
}


def get_tool(name):
    return TOOLS.get(name)


def get_tools_description():
    result = []

    for name, tool in TOOLS.items():
        confirmation = (
            "требует подтверждения"
            if tool["requires_confirmation"]
            else "без подтверждения"
        )

        result.append(
            f"- {name}: {tool['description']} ({confirmation})"
        )

    return "\n".join(result)