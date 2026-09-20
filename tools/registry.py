from tools.files import (
    list_files,
    find_file,
    read_file,
    write_file,
    edit_file,
    search_files
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
from tools.memory import (
    remember,
    recall_memory,
    forget_memory
)


TOOLS = {
    "list_files": {
        "function": list_files,
        "description": "Показывает список файлов проекта.",
        "requires_confirmation": False
    },

    "find_file": {
        "function": find_file,
        "description": "Ищет файл по имени или относительному пути в проекте.",
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
        "requires_confirmation": True
    },

    "search_files": {
        "function": search_files,
        "description": "Ищет указанный текст во всех файлах проекта и показывает файлы, номера строк и найденные строки.",
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
        "requires_confirmation": True
    },

    "git_log": {
        "function": git_log,
        "description": "Показывает историю последних Git-коммитов.",
        "requires_confirmation": False
    },

    "git_push": {
        "function": git_push,
        "description": "Отправляет текущую ветку Git в удалённый репозиторий.",
        "requires_confirmation": True
    },

    "remember": {
        "function": remember,
        "description": "Сохраняет важный факт, предпочтение или заметку в долговременную память.",
        "requires_confirmation": False
    },

    "recall_memory": {
        "function": recall_memory,
        "description": "Ищет или возвращает список фактов из долговременной памяти.",
        "requires_confirmation": False
    },

    "forget_memory": {
        "function": forget_memory,
        "description": "Удаляет запись из долговременной памяти по номеру (ID) или тексту.",
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


TOOL_PARAMETERS = {
    "list_files": {
        "properties": {},
        "required": []
    },
    "find_file": {
        "properties": {
            "filename": {
                "type": "string",
                "description": "Имя или относительный путь к файлу в проекте"
            }
        },
        "required": ["filename"]
    },
    "read_file": {
        "properties": {
            "filename": {
                "type": "string",
                "description": "Имя или путь к файлу для чтения"
            }
        },
        "required": ["filename"]
    },
    "write_file": {
        "properties": {
            "filename": {
                "type": "string",
                "description": "Имя или путь к создаваемому/перезаписываемому файлу"
            },
            "content": {
                "type": "string",
                "description": "Полное текстовое содержимое файла"
            }
        },
        "required": ["filename", "content"]
    },
    "edit_file": {
        "properties": {
            "filename": {
                "type": "string",
                "description": "Имя или путь к редактируемому файлу"
            },
            "old_text": {
                "type": "string",
                "description": "Точный фрагмент существующего текста для замены"
            },
            "new_text": {
                "type": "string",
                "description": "Новый текст, который должен заменить old_text"
            }
        },
        "required": ["filename", "old_text", "new_text"]
    },
    "search_files": {
        "properties": {
            "query": {
                "type": "string",
                "description": "Текст, имя функции или фрагмент для поиска во всех файлах проекта"
            }
        },
        "required": ["query"]
    },
    "run_command": {
        "properties": {
            "command": {
                "type": "string",
                "description": "Команда PowerShell для выполнения в проекте"
            }
        },
        "required": ["command"]
    },
    "analyze_file": {
        "properties": {
            "filename": {
                "type": "string",
                "description": "Имя файла для анализа структуры и кода"
            },
            "task": {
                "type": "string",
                "description": "Дополнительное описание задачи или вопроса по анализу (опционально)"
            }
        },
        "required": ["filename"]
    },
    "validate_project": {
        "properties": {},
        "required": []
    },
    "git_status": {
        "properties": {},
        "required": []
    },
    "git_diff": {
        "properties": {},
        "required": []
    },
    "git_commit": {
        "properties": {
            "message": {
                "type": "string",
                "description": "Сообщение для Git-коммита"
            }
        },
        "required": ["message"]
    },
    "git_log": {
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Количество последних коммитов (по умолчанию 10)"
            }
        },
        "required": []
    },
    "git_push": {
        "properties": {},
        "required": []
    },
    "remember": {
        "properties": {
            "text": {
                "type": "string",
                "description": "Факт, знание или предпочтение для сохранения в память"
            }
        },
        "required": ["text"]
    },
    "recall_memory": {
        "properties": {
            "query": {
                "type": "string",
                "description": "Поисковый запрос по памяти (если пустой — вернёт все сохранённые записи)"
            }
        },
        "required": []
    },
    "forget_memory": {
        "properties": {
            "target": {
                "type": "string",
                "description": "Номер записи (например, '1' или '#1') или фрагмент текста для удаления"
            }
        },
        "required": ["target"]
    }
}


def get_tools_schema(tool_names=None):
    """
    Преобразует реестр TOOLS в спецификацию tools для Ollama /api/chat.
    Если передан список tool_names, возвращает схемы только для указанных инструментов.
    """
    schemas = []
    target_names = tool_names if tool_names is not None else TOOLS.keys()

    for name in target_names:
        if name not in TOOLS:
            continue
        tool = TOOLS[name]
        params = TOOL_PARAMETERS.get(
            name,
            {"properties": {}, "required": []}
        )

        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "properties": params.get("properties", {}),
                    "required": params.get("required", [])
                }
            }
        })

    return schemas