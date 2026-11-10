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
from tools.household import (
    create_task,
    list_tasks,
    complete_task,
    delete_task,
    create_reminder,
    list_reminders,
    complete_reminder,
    delete_reminder,
    check_due_reminders,
    create_note,
    list_notes,
    search_notes,
    delete_note,
    create_list,
    show_list,
    add_list_item,
    complete_list_item,
    delete_list_item,
    delete_list
)
from tools.daily_briefing import daily_briefing
from tools.image_tools import (
    inspect_image,
    generate_image,
    edit_image,
    get_active_image,
    select_image,
)


TOOLS = {
    "inspect_image": {
        "function": inspect_image,
        "description": (
            "Анализирует содержимое активного или указанного PNG-изображения с помощью Vision-модели "
            "(отвечает на вопросы о деталях, подсчитывает объекты и при return_bbox=True возвращает mask_bbox [x1, y1, x2, y2])."
        ),
        "requires_confirmation": False
    },
    "generate_image": {
        "function": generate_image,
        "description": (
            "Генерирует новое изображение (PNG) через ComfyUI SDXL-Lightning. "
            "Передавай детальный prompt на английском языке (объект, поза, фон, освещение, стиль), "
            "чтобы генерация точно соответствовала запросу пользователя."
        ),
        "requires_confirmation": False
    },

    "edit_image": {
        "function": edit_image,
        "description": (
            "Редактирует активное или указанное PNG-изображение с сохранением неизменяемых деталей. "
            "Поддерживает точечный inpainting по mask_bbox/mask_path, ControlNet и img2img: "
            "поза, цвет, фон, добавление или удаление объекта, освещение, стиль."
        ),
        "requires_confirmation": False
    },

    "get_active_image": {
        "function": get_active_image,
        "description": "Возвращает путь, описание (промпт), размеры и историю правок текущего активного изображения в сессии.",
        "requires_confirmation": False
    },

    "select_image": {
        "function": select_image,
        "description": "Выбирает конкретный существующий файл PNG как текущее активное изображение для последующего редактирования.",
        "requires_confirmation": False
    },
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
    },

    "create_task": {
        "function": create_task,
        "description": "Создаёт новую бытовую задачу.",
        "requires_confirmation": False
    },
    "list_tasks": {
        "function": list_tasks,
        "description": "Показывает список бытовых задач (можно фильтровать: all, pending, completed).",
        "requires_confirmation": False
    },
    "complete_task": {
        "function": complete_task,
        "description": "Отмечает задачу выполненной по её номеру (ID) или названию.",
        "requires_confirmation": False
    },
    "delete_task": {
        "function": delete_task,
        "description": "Удаляет задачу по её номеру (ID) или названию.",
        "requires_confirmation": True
    },
    "create_reminder": {
        "function": create_reminder,
        "description": "Создаёт напоминание на указанное время (например, '19:00', 'завтра в 10:00', 'через 15 минут').",
        "requires_confirmation": False
    },
    "list_reminders": {
        "function": list_reminders,
        "description": "Показывает список активных или всех напоминаний.",
        "requires_confirmation": False
    },
    "complete_reminder": {
        "function": complete_reminder,
        "description": "Отмечает напоминание выполненным по номеру (ID). Для повторяющихся напоминаний переносит время на следующий интервал.",
        "requires_confirmation": False
    },
    "delete_reminder": {
        "function": delete_reminder,
        "description": "Удаляет напоминание по его номеру (ID) или тексту.",
        "requires_confirmation": True
    },
    "check_due_reminders": {
        "function": check_due_reminders,
        "description": "Проверяет и возвращает наступившие напоминания.",
        "requires_confirmation": False
    },
    "create_note": {
        "function": create_note,
        "description": "Создаёт новую текстовую заметку с заголовком и текстом.",
        "requires_confirmation": False
    },
    "list_notes": {
        "function": list_notes,
        "description": "Показывает список всех сохранённых заметок.",
        "requires_confirmation": False
    },
    "search_notes": {
        "function": search_notes,
        "description": "Ищет заметки по ключевым словам в заголовке или тексте.",
        "requires_confirmation": False
    },
    "delete_note": {
        "function": delete_note,
        "description": "Удаляет заметку по её номеру (ID) или заголовку.",
        "requires_confirmation": True
    },
    "create_list": {
        "function": create_list,
        "description": "Создаёт новый именованный список (например, 'покупки', 'фильмы').",
        "requires_confirmation": False
    },
    "show_list": {
        "function": show_list,
        "description": "Показывает пункты конкретного списка или перечень всех имеющихся списков.",
        "requires_confirmation": False
    },
    "add_list_item": {
        "function": add_list_item,
        "description": "Добавляет новый пункт в указанный список.",
        "requires_confirmation": False
    },
    "complete_list_item": {
        "function": complete_list_item,
        "description": "Отмечает пункт списка выполненным по номеру (ID) или тексту.",
        "requires_confirmation": False
    },
    "delete_list_item": {
        "function": delete_list_item,
        "description": "Удаляет пункт из указанного списка по номеру (ID) или тексту.",
        "requires_confirmation": False
    },
    "delete_list": {
        "function": delete_list,
        "description": "Удаляет указанный список целиком со всеми пунктами.",
        "requires_confirmation": True
    },
    "daily_briefing": {
        "function": daily_briefing,
        "description": "Формирует структурированную сводку дня (задачи, напоминания, повторяющиеся напоминания, списки).",
        "requires_confirmation": False
    }
}


def get_tool(name):
    return TOOLS.get(name)


def get_tool_risk_level(name):
    """
    Возвращает строковый уровень риска инструмента через PermissionManager.
    """
    from tools.permissions import get_permission_manager
    assessment = get_permission_manager().assess_tool(name, {})
    return assessment.risk_level.value


def get_tools_description():
    descriptions = []

    for name, tool in TOOLS.items():
        descriptions.append(
            f"- {name}: {tool['description']}"
        )

    return "\n".join(descriptions)


TOOL_PARAMETERS = {
    "inspect_image": {
        "properties": {
            "question": {
                "type": "string",
                "description": "Вопрос к изображению (что проверить, какие объекты найти или какую область выделить)"
            },
            "image_path": {
                "type": "string",
                "description": "Путь к PNG-файлу (опционально; по умолчанию используется текущее активное изображение)"
            },
            "return_bbox": {
                "type": "boolean",
                "description": "Если True — вернуть нормализованные координаты mask_bbox [x1, y1, x2, y2] (0..1) для точечного редактирования"
            }
        },
        "required": ["question"]
    },
    "generate_image": {
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Детальное описание изображения (предпочтительно на английском для SDXL, например: "
                    "'a lone ginger cat sitting on a sandy beach at sunset, waves, photorealistic, sharp focus')"
                )
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Соотношение сторон: 'square' (1024x1024), 'landscape' (1216x832), 'portrait' (832x1216) или 'custom'"
            },
            "count": {
                "type": "integer",
                "description": "Количество изображений для генерации (от 1 до 4, по умолчанию 1)"
            },
            "negative_prompt": {
                "type": "string",
                "description": "Что нужно исключить из изображения (на английском, опционально)"
            },
            "width": {
                "type": "integer",
                "description": "Ширина изображения в пикселях (кратна 64, опционально)"
            },
            "height": {
                "type": "integer",
                "description": "Высота изображения в пикселях (кратна 64, опционально)"
            }
        },
        "required": ["prompt"]
    },
    "edit_image": {
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Инструкция: что именно изменить, добавить или убрать на изображении"
            },
            "target_image_path": {
                "type": "string",
                "description": "Путь к PNG файлу для редактирования (опционально; если не указан, используется активное изображение)"
            },
            "edit_type": {
                "type": "string",
                "description": "Тип правки: 'replace', 'remove', 'add', 'color', 'pose', 'background', 'style', 'proportions', 'lighting', 'general' (опционально)"
            },
            "positive_prompt": {
                "type": "string",
                "description": (
                    "Полный обновлённый английский промпт итоговой сцены с сохранением неизменяемых деталей "
                    "(опционально, существенно повышает точность img2img)"
                )
            },
            "negative_prompt": {
                "type": "string",
                "description": "Нежелательные детали или удаляемые объекты на английском (опционально)"
            },
            "denoise": {
                "type": "number",
                "description": "Сила изменения от 0.15 до 0.90 для img2img или до 0.98 для inpainting по маске (опционально, подбирается автоматически)"
            },
            "mask_bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Нормализованные координаты [x1, y1, x2, y2] от 0.0 до 1.0 (из inspect_image) "
                    "для точечного inpainting с сохранением остального фона"
                )
            },
            "protect_bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Нормализованные координаты [x1, y1, x2, y2] главного объекта, который нужно ЗАЩИТИТЬ (сохранить), "
                    "когда требуется заменить или перерисовать фон вокруг него"
                )
            },
            "invert_mask": {
                "type": "boolean",
                "description": "Инвертировать ли маску (True — защитить область внутри bbox и перерисовать весь фон вокруг)"
            },
            "mask_path": {
                "type": "string",
                "description": "Путь к готовому PNG-файлу маски (белый — область правки, чёрный — сохраняется, опционально)"
            },
            "feather": {
                "type": "integer",
                "description": "Радиус размытия краёв маски в пикселях для плавного перехода (по умолчанию 12)"
            },
            "control_type": {
                "type": "string",
                "description": "Тип структурного контроля ControlNet: 'canny', 'openpose', 'depth' (опционально, требует модель ControlNet)"
            },
            "control_strength": {
                "type": "number",
                "description": "Сила влияния ControlNet от 0.0 до 2.0 (по умолчанию 0.8)"
            }
        },
        "required": ["instruction"]
    },
    "get_active_image": {
        "properties": {},
        "required": []
    },
    "select_image": {
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Путь к существующему PNG-файлу, который нужно сделать активным для редактирования"
            },
            "prompt": {
                "type": "string",
                "description": "Краткое текстовое описание выбранного изображения (опционально)"
            }
        },
        "required": ["file_path"]
    },
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
    },
    "create_task": {
        "properties": {
            "title": {
                "type": "string",
                "description": "Название или краткое описание задачи"
            }
        },
        "required": ["title"]
    },
    "list_tasks": {
        "properties": {
            "status": {
                "type": "string",
                "description": "Фильтр статуса: 'all' (все), 'pending' (невыполненные), 'completed' (выполненные)"
            }
        },
        "required": []
    },
    "complete_task": {
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Номер (ID) или название задачи для завершения"
            }
        },
        "required": ["task_id"]
    },
    "delete_task": {
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Номер (ID) или название задачи для удаления"
            }
        },
        "required": ["task_id"]
    },
    "create_reminder": {
        "properties": {
            "text": {
                "type": "string",
                "description": "О чём напомнить"
            },
            "remind_at": {
                "type": "string",
                "description": "Время напоминания (например, '19:00', 'завтра в 10:00', 'через 15 минут', '2026-09-20 19:00')"
            }
        },
        "required": ["text", "remind_at"]
    },
    "list_reminders": {
        "properties": {
            "include_triggered": {
                "type": "boolean",
                "description": "Включать ли уже сработавшие напоминания (по умолчанию False)"
            }
        },
        "required": []
    },
    "delete_reminder": {
        "properties": {
            "reminder_id": {
                "type": "string",
                "description": "Номер (ID) или текст напоминания для удаления"
            }
        },
        "required": ["reminder_id"]
    },
    "check_due_reminders": {
        "properties": {
            "current_time": {
                "type": "string",
                "description": "Текущее время в формате ISO (опционально, по умолчанию текущий момент)"
            }
        },
        "required": []
    },
    "create_note": {
        "properties": {
            "title": {
                "type": "string",
                "description": "Заголовок заметки"
            },
            "content": {
                "type": "string",
                "description": "Текст заметки"
            }
        },
        "required": ["content"]
    },
    "list_notes": {
        "properties": {},
        "required": []
    },
    "search_notes": {
        "properties": {
            "query": {
                "type": "string",
                "description": "Поисковый запрос по заголовку или тексту заметок"
            }
        },
        "required": ["query"]
    },
    "delete_note": {
        "properties": {
            "note_id": {
                "type": "string",
                "description": "Номер (ID) или заголовок заметки для удаления"
            }
        },
        "required": ["note_id"]
    },
    "create_list": {
        "properties": {
            "name": {
                "type": "string",
                "description": "Имя нового списка (например, 'покупки', 'книги')"
            }
        },
        "required": ["name"]
    },
    "show_list": {
        "properties": {
            "name": {
                "type": "string",
                "description": "Имя списка для отображения (если не указано, выведет перечень всех списков)"
            }
        },
        "required": []
    },
    "add_list_item": {
        "properties": {
            "list_name": {
                "type": "string",
                "description": "Имя списка"
            },
            "text": {
                "type": "string",
                "description": "Текст нового пункта списка"
            }
        },
        "required": ["list_name", "text"]
    },
    "complete_list_item": {
        "properties": {
            "list_name": {
                "type": "string",
                "description": "Имя списка"
            },
            "item_id": {
                "type": "string",
                "description": "Номер (ID) или текст пункта для отметки выполнения"
            }
        },
        "required": ["list_name", "item_id"]
    },
    "delete_list_item": {
        "properties": {
            "list_name": {
                "type": "string",
                "description": "Имя списка"
            },
            "item_id": {
                "type": "string",
                "description": "Номер (ID) или текст пункта для удаления"
            }
        },
        "required": ["list_name", "item_id"]
    },
    "delete_list": {
        "properties": {
            "name": {
                "type": "string",
                "description": "Имя списка для полного удаления"
            }
        },
        "required": ["name"]
    },
    "daily_briefing": {
        "properties": {},
        "required": []
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