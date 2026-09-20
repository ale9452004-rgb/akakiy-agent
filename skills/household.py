"""
Навык 'household' для управления бытовыми задачами, напоминаниями, заметками и списками.
"""

import re
from typing import Optional

from skills.base import BaseSkill


HOUSEHOLD_SYSTEM_PROMPT = """Ты используешь специализированный бытовой навык 'household' Акакия.
В твоём распоряжении проверенные инструменты управления бытовыми делами:
1. Задачи (Tasks):
   - create_task: создать новую задачу;
   - list_tasks: посмотреть список задач (параметр status: 'all', 'pending', 'completed');
   - complete_task: отметить задачу выполненной (по номеру или названию);
   - delete_task: удалить задачу.
2. Напоминания (Reminders):
   - create_reminder: установить напоминание на определённое время (текст и время);
   - list_reminders: показать активные напоминания;
   - delete_reminder: удалить напоминание;
   - check_due_reminders: проверить наступившие к текущему моменту напоминания.
3. Заметки (Notes):
   - create_note: сохранить новую текстовую заметку с заголовком и текстом;
   - list_notes: посмотреть список всех заметок;
   - search_notes: найти заметки по ключевым словам;
   - delete_note: удалить заметку по номеру или заголовку.
4. Списки (Lists):
   - create_list: создать именованный список (например, 'покупки', 'фильмы');
   - show_list: показать содержимое списка или перечень всех списков;
   - add_list_item: добавить пункт в список;
   - complete_list_item: отметить пункт списка выполненным;
   - delete_list_item: удалить пункт из списка;
   - delete_list: удалить список целиком.

Правила работы:
- Точно определяй нужный инструмент и вызывай его с корректными аргументами.
- При удалении предупреждай пользователя о том, что удаление требует подтверждения.
- Отвечай вежливо, кратко и информативно на русском языке.
"""


class HouseholdSkill(BaseSkill):
    """
    Бытовой навык (Household Assistant).
    """

    name = "household"
    description = "Управление бытовыми задачами, напоминаниями, заметками и списками."
    tools = [
        "create_task",
        "list_tasks",
        "complete_task",
        "delete_task",
        "create_reminder",
        "list_reminders",
        "delete_reminder",
        "check_due_reminders",
        "create_note",
        "list_notes",
        "search_notes",
        "delete_note",
        "create_list",
        "show_list",
        "add_list_item",
        "complete_list_item",
        "delete_list_item",
        "delete_list"
    ]
    system_prompt = HOUSEHOLD_SYSTEM_PROMPT

    def __init__(self, enabled: bool = True):
        super().__init__(
            name=self.name,
            description=self.description,
            tools=self.tools,
            system_prompt=self.system_prompt,
            enabled=enabled
        )

    def matches(self, user_input: str) -> bool:
        """
        Детерминированно определяет, относится ли запрос к бытовым делам
        (задачи, напоминания, заметки, списки).
        """
        if not user_input or not isinstance(user_input, str):
            return False

        norm = user_input.strip().lower()

        # Исключение: память пользователя обрабатывается MemorySkill
        if re.search(r"\b(?:запомни|памят[ьие]|вспомни|забудь)\b", norm):
            return False

        # Исключение: кодовая база и файлы проекта обрабатываются ProjectSkill
        if re.search(r"\b(?:в\s+проекте|файл[ыа]?\s+проекта|структур[а-я]\s+проекта|функци[яию]|класс|ast|py_compile|validate_project)\b", norm):
            return False

        # Исключение: служебные команды планировщика
        if norm.startswith("план:") or norm in {"выполни план", "выполнить план", "покажи план", "очисти план"}:
            return False

        household_patterns = [
            # 1. Задачи и списки дел
            r"\b(?:задач[аеуыи]|список\s+дел|дела\s+на\s+сегодня|туду|todo)\b",
            r"\b(?:добавь|создай|поставь|новая)\s+задач[аеуи]\b",
            r"\b(?:выполни|закрой|отметь)\s+задач[аеуи]\b",
            r"\b(?:удали|стереть)\s+задач[аеуи]\b",
            r"\b(?:покажи|список)\s+задач\b",

            # 2. Напоминания
            r"\b(?:напомни|напоминани[еяи]|напомнить|будильник)\b",

            # 3. Заметки
            r"\b(?:заметк[аеуыи]|запиши\s+(?:в\s+)?заметки|создай\s+заметку|список\s+заметок|найди\s+заметку|покажи\s+заметки)\b",

            # 4. Списки (покупки, дела, произвольные именованные списки)
            r"\b(?:список\s+покупок|список\s+продуктов|купить\s+в\s+магазине)\b",
            r"\b(?:создай|сделай|новый)\s+список\b",
            r"\b(?:добавь|запиши|внеси)\s+(?:пункт\s+)?в\s+список\b",
            r"\b(?:покажи|открой|выведи)\s+список\s+[а-яa-z0-9_-]+\b",
            r"\b(?:вычеркни|удали|отметь)\s+(?:из\s+списка|в\s+списке)\b",
            r"\b(?:удали|сотри|очисти)\s+список\b",
            r"\bсписки\b",
        ]

        for p in household_patterns:
            if re.search(p, norm):
                return True

        return False
