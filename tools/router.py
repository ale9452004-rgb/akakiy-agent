"""
Модуль детерминированной маршрутизации команд Акакия (CommandRouter).

Отвечает за:
- быстрый детерминированный роутинг CLI-команд проекта (find_file, list_files, search_files);
- быстрый роутинг бытовых команд (household: tasks, notes, reminders, lists);
- распознавание команд долговременной памяти (remember, recall, forget, search, clear);
- распознавание команд управления планами (create, execute, get, clear);
- предоставление единой точки входа для fast-path без лишних LLM-вызовов.
"""

from typing import Any, Dict, Optional
import re


class CommandRouter:
    """
    Детерминированный маршрутизатор команд.

    Определяет намерение пользователя по формальным синтаксическим шаблонам
    и возвращает структурированное решение о маршрутизации.
    """

    def __init__(self):
        self._init_patterns()

    def _init_patterns(self):
        # 1. Файлы проекта
        self.file_search_patterns = [
            re.compile(r"^(?:найди|найти)(?:\s+в\s+проекте)?\s+файл\s+([^\s,!?;:]+)$", re.IGNORECASE),
        ]
        self.list_files_exact = {
            "покажи список файлов проекта",
            "покажи файлы проекта",
            "список файлов проекта",
            "перечисли файлы проекта",
            "покажи список файлов",
            "покажи файлы",
            "список файлов",
            "перечисли файлы",
            "файлы проекта",
        }
        self.structure_exact = {
            "покажи структуру проекта",
            "покажи структуру проекта акакия",
            "структура проекта",
        }
        self.func_pattern = re.compile(r"^(?:найди|найти)\s+функцию\s+([a-zA-Z_0-9]+)$", re.IGNORECASE)
        self.search_pattern = re.compile(r"^(?:поиск\s+по\s+проекту|(?:найди|найти)\s+в\s+проекте\s+текст)\s+(.+)$", re.IGNORECASE)

        # 2. Бытовые команды: Задачи
        self.task_create_p1 = re.compile(r"^(?:создай|добавь|новая)\s+задач[ауе]\s+(.+)$", re.IGNORECASE)
        self.task_create_p2 = re.compile(r"^задача:\s*(.+)$", re.IGNORECASE)
        self.task_list_all = {"покажи задачи", "покажи все задачи", "список задач", "мои задачи", "задачи", "показать задачи"}
        self.task_list_pending = {"активные задачи", "покажи активные задачи", "невыполненные задачи"}
        self.task_list_completed = {"выполненные задачи", "покажи выполненные задачи", "завершенные задачи"}
        self.task_done_p = re.compile(r"^(?:выполни|отметь\s+(?:выполненной|сделанной)|закрой|сделай)\s+задач[уе]\s+([#№]?\d+|.+)$", re.IGNORECASE)
        self.task_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+задач[уие]?\s+(.+)$", re.IGNORECASE)
        self.task_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:юю|ие|их|яя)(?:\s+(?:\d+|[а-яё]+))?)\s+задач[иа-я]*$", re.IGNORECASE)

        # 3. Бытовые команды: Заметки
        self.note_create_p1 = re.compile(r"^(?:создай|добавь|новая|запиши)\s+заметк[ауе]\s+([^:]+?)(?:\s*:\s*|\s+текст\s+)(.+)$", re.IGNORECASE)
        self.note_create_p2 = re.compile(r"^(?:создай|добавь|новая|запиши)\s+заметк[ауе]\s+(.+)$", re.IGNORECASE)
        self.note_list_exact = {"покажи заметки", "список заметок", "мои заметки", "заметки", "показать заметки", "все заметки"}
        self.note_search_p = re.compile(r"^(?:найди|поиск)(?:\s+в)?\s+заметк[а-я]*\s+(.+)$", re.IGNORECASE)
        self.note_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+заметк[уие]?\s+(.+)$", re.IGNORECASE)
        self.note_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:юю|ие|их|яя)(?:\s+(?:\d+|[а-яё]+))?)\s+заметк[иа-я]*$", re.IGNORECASE)

        # 4. Бытовые команды: Напоминания
        self.rem_create_p = re.compile(r"^(?:напомни|создай\s+напоминание|новое\s+напоминание)\s+(.+?)\s+((?:в|через|завтра|каждый|каждую|каждые|по\s+будням|ежедневно)\s+.+)$", re.IGNORECASE)
        self.rem_list_exact = {"покажи напоминания", "список напоминаний", "мои напоминания", "напоминания", "показать напоминания"}
        self.rem_done_p = re.compile(r"^(?:выполни|отметь\s+(?:выполненным|сделанным)|закрой|сделай)\s+напоминани[ея]?\s+([#№]?\d+|.+)$", re.IGNORECASE)
        self.rem_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+напоминани[ея]?\s+(.+)$", re.IGNORECASE)
        self.rem_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:ее|ие|их)(?:\s+(?:\d+|[а-яё]+))?)\s+напоминан[иеа-я]*$", re.IGNORECASE)

        # 5. Бытовые команды: Списки
        self.list_show_all = {"покажи списки", "список списков", "списки", "показать списки"}
        self.list_show_p = re.compile(r"^(?:покажи|открой)\s+список\s+(.+)$", re.IGNORECASE)
        self.list_create_p = re.compile(r"^(?:создай|добавь|новый)\s+список\s+(.+)$", re.IGNORECASE)
        self.list_add_p = re.compile(r"^добавь\s+в\s+список\s+([^\s]+)\s+(.+)$", re.IGNORECASE)

        # 6. Команды памяти (Memory)
        self.mem_rem_p = re.compile(r"^(?:запомни|сохрани\s+в\s+память)[:\s]+(.+)$", re.IGNORECASE)
        self.mem_recall_exact = {
            "что ты помнишь",
            "что помнишь",
            "покажи память",
            "список памяти",
            "что в памяти",
            "память",
            "показать память",
        }
        self.mem_forg_p = re.compile(r"^(?:забудь|удали\s+из\s+памяти)[:\s]+(.+)$", re.IGNORECASE)
        self.mem_search_p = re.compile(r"^(?:найди\s+в\s+памяти|вспомни)[:\s]+(.+)$", re.IGNORECASE)
        self.mem_clear_exact = {
            "очисти память",
            "очистить память",
            "забудь всё",
            "забудь все",
            "сбрось память",
            "сбросить память",
        }

        # 7. Команды управления планами (Planning)
        self.plan_create_p = re.compile(r"^(?:создай|составь|сделай)\s+план(?:\s*:\s*|\s+)(.+)$", re.IGNORECASE)
        self.plan_create_exact = {"создай план", "создать план", "составь план", "составить план"}
        self.plan_execute_exact = {"выполни план", "выполнить план", "запусти план"}
        self.plan_get_exact = {"покажи план", "текущий план", "показать план"}
        self.plan_clear_exact = {"очисти план", "удали план", "сбрось план"}

        # 8. Дневной брифинг (Daily Briefing)
        self.briefing_exact = {
            "что у меня сегодня",
            "что на сегодня",
            "план на день",
            "план на сегодня",
            "сводка дня",
            "сводка на сегодня",
            "дневной брифинг",
            "брифинг на сегодня",
            "что сегодня",
        }
        self.briefing_pattern = re.compile(
            r"^(?:акакий[,\s]+)?(?:что\s+(?:у\s+меня\s+)?(?:запланировано\s+)?на\s+сегодня|какие\s+планы\s+на\s+сегодня|что\s+по\s+планам\s+на\s+сегодня)\??$",
            re.IGNORECASE
        )

        # 9. Генерация изображений (Image Generation)
        self.image_with_noun_p = re.compile(
            r"^(?:акакий[,\s]+)?(?:пожалуйста[,\s]+)?(?:создай|создайте|создать|сгенерируй|сгенерируйте|сгенерировать|сделай|сделайте|сделать|нарисуй|нарисуйте|нарисовать|изобрази|изобразите|изобразить|отрисуй|отрисуйте|отрисовать)(?:\s+мне)?(?:[,\s]+пожалуйста)?\s+(?:изображение|изображения|картинку|картинки|рисунок|рисунки|иллюстрацию|иллюстрации|арт|арты|фото|фотографию|фотографии)(?:\s*:\s*|[,\s]+)(.+)$",
            re.IGNORECASE
        )
        self.image_draw_verb_p = re.compile(
            r"^(?:акакий[,\s]+)?(?:пожалуйста[,\s]+)?(?:нарисуй|нарисуйте|нарисовать|изобрази|изобразите|изобразить|отрисуй|отрисуйте|отрисовать)(?:\s+мне)?(?:[,\s]+пожалуйста)?(?:\s*:\s*|[,\s]+)(.+)$",
            re.IGNORECASE
        )

    def match_memory(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос детерминированной командой памяти.
        Возвращает словарь с параметрами действия или None.
        """
        raw_trimmed = user_input.strip()
        normalized = raw_trimmed.lower().rstrip(".,!?;:")

        # 1. Очистить память (проверяем перед forget, чтобы "забудь всё" трактовалось как clear)
        if normalized in self.mem_clear_exact:
            return {
                "action": "clear"
            }

        # 2. Вспомнить всё / список памяти
        if normalized in self.mem_recall_exact:
            return {
                "action": "recall"
            }

        # 3. Запомнить
        m = self.mem_rem_p.match(raw_trimmed)
        if m:
            return {
                "action": "remember",
                "text": m.group(1).strip()
            }

        # 4. Забыть
        m = self.mem_forg_p.match(raw_trimmed)
        if m:
            return {
                "action": "forget",
                "target": m.group(1).strip()
            }

        # 5. Поиск в памяти
        m = self.mem_search_p.match(raw_trimmed)
        if m:
            return {
                "action": "search",
                "query": m.group(1).strip()
            }

        return None

    def match_plan(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос командой создания или управления планом.
        Возвращает словарь с параметрами действия или None.
        """
        raw_trimmed = user_input.strip()
        u_lower = raw_trimmed.lower()

        if u_lower.startswith("план:"):
            return {
                "action": "create",
                "request": raw_trimmed[5:].strip()
            }

        create_m = self.plan_create_p.match(raw_trimmed)
        if create_m:
            return {
                "action": "create",
                "request": create_m.group(1).strip()
            }

        normalized = u_lower.rstrip(".,!?;:")

        if normalized in self.plan_create_exact:
            return {
                "action": "create",
                "request": ""
            }

        if normalized in self.plan_execute_exact:
            return {
                "action": "execute"
            }

        if normalized in self.plan_get_exact:
            return {
                "action": "get"
            }

        if normalized in self.plan_clear_exact:
            return {
                "action": "clear"
            }

        return None

    def match_image(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос командой генерации изображения.
        Возвращает dict с action='generate' и извлечённым чистым prompt, либо None.
        """
        raw_trimmed = user_input.strip()
        if not raw_trimmed:
            return None

        # 1. Паттерн с глаголом создания и объектом (изображение, картинка, арт и т.д.)
        m = self.image_with_noun_p.match(raw_trimmed)
        if m:
            clean_prompt = m.group(1).strip().lstrip(":").strip().strip(".,;:!?")
            if len(clean_prompt) >= 2:
                return {
                    "action": "generate",
                    "prompt": clean_prompt
                }

        # 2. Паттерн с глаголом рисования без явного существительного (нарисуй ..., изобрази ...)
        m = self.image_draw_verb_p.match(raw_trimmed)
        if m:
            clean_prompt = m.group(1).strip().lstrip(":").strip().strip(".,;:!?")
            if len(clean_prompt) >= 2:
                return {
                    "action": "generate",
                    "prompt": clean_prompt
                }

        return None

    def choose_tool(self, user_input: str) -> Dict[str, Any]:
        """
        Определяет инструмент для детерминированных fast-path команд (CLI, Household, Memory).
        Возвращает словарь вида {"tool": str | None, "arguments": dict}.
        """
        raw_trimmed = user_input.strip()
        raw_clean = raw_trimmed.rstrip(".,!?;:")
        normalized = raw_clean.lower()

        # =================================================
        # 0. Дневной брифинг (Daily Briefing)
        # =================================================
        if normalized in self.briefing_exact or self.briefing_pattern.match(raw_clean):
            return {
                "tool": "daily_briefing",
                "arguments": {}
            }

        # =================================================
        # 1. Поиск конкретного файла
        # =================================================
        for pattern in self.file_search_patterns:
            match = pattern.match(raw_clean)
            if match:
                filename = match.group(1).strip().rstrip(".,!?;:")
                return {
                    "tool": "find_file",
                    "arguments": {"filename": filename}
                }

        # =================================================
        # 2. Просмотр списка файлов проекта
        # =================================================
        if normalized in self.list_files_exact:
            return {
                "tool": "list_files",
                "arguments": {}
            }

        # =================================================
        # 3. Анализ структуры проекта
        # =================================================
        if normalized in self.structure_exact:
            return {
                "tool": "list_files",
                "arguments": {}
            }

        # =================================================
        # 4. Поиск функции
        # =================================================
        func_match = self.func_pattern.match(raw_clean)
        if func_match:
            search_query = f"def {func_match.group(1).strip()}"
            return {
                "tool": "search_files",
                "arguments": {"query": search_query}
            }

        # =================================================
        # 5. Поиск по проекту
        # =================================================
        search_match = self.search_pattern.match(raw_clean)
        if search_match:
            search_query = search_match.group(1).strip()
            return {
                "tool": "search_files",
                "arguments": {"query": search_query}
            }

        # =================================================
        # 6. Бытовые команды (Household)
        # =================================================

        # --- Задачи (Tasks) ---
        task_create_m = self.task_create_p1.match(raw_clean) or self.task_create_p2.match(raw_clean)
        if task_create_m:
            return {"tool": "create_task", "arguments": {"title": task_create_m.group(1).strip()}}

        if normalized in self.task_list_all:
            return {"tool": "list_tasks", "arguments": {"status": "all"}}
        if normalized in self.task_list_pending:
            return {"tool": "list_tasks", "arguments": {"status": "pending"}}
        if normalized in self.task_list_completed:
            return {"tool": "list_tasks", "arguments": {"status": "completed"}}

        task_done_m = self.task_done_p.match(raw_clean)
        if task_done_m:
            return {"tool": "complete_task", "arguments": {"task_id": task_done_m.group(1).strip()}}

        task_del_m = self.task_del_p1.match(raw_clean) or self.task_del_p2.match(raw_clean)
        if task_del_m:
            return {"tool": "delete_task", "arguments": {"task_id": task_del_m.group(1).strip()}}

        # --- Заметки (Notes) ---
        note_create_m = self.note_create_p1.match(raw_clean)
        if note_create_m:
            return {"tool": "create_note", "arguments": {"title": note_create_m.group(1).strip(), "content": note_create_m.group(2).strip()}}
        note_create_m2 = self.note_create_p2.match(raw_clean)
        if note_create_m2:
            n_text = note_create_m2.group(1).strip()
            return {"tool": "create_note", "arguments": {"title": n_text, "content": n_text}}

        if normalized in self.note_list_exact:
            return {"tool": "list_notes", "arguments": {}}

        note_search_m = self.note_search_p.match(raw_clean)
        if note_search_m:
            return {"tool": "search_notes", "arguments": {"query": note_search_m.group(1).strip()}}

        note_del_m = self.note_del_p1.match(raw_clean) or self.note_del_p2.match(raw_clean)
        if note_del_m:
            return {"tool": "delete_note", "arguments": {"note_id": note_del_m.group(1).strip()}}

        # --- Напоминания (Reminders) ---
        rem_create_m = self.rem_create_p.match(raw_clean)
        if rem_create_m:
            return {"tool": "create_reminder", "arguments": {"text": rem_create_m.group(1).strip(), "remind_at": rem_create_m.group(2).strip()}}

        if normalized in self.rem_list_exact:
            return {"tool": "list_reminders", "arguments": {}}

        rem_done_m = self.rem_done_p.match(raw_clean)
        if rem_done_m:
            return {"tool": "complete_reminder", "arguments": {"reminder_id": rem_done_m.group(1).strip()}}

        rem_del_m = self.rem_del_p1.match(raw_clean) or self.rem_del_p2.match(raw_clean)
        if rem_del_m:
            return {"tool": "delete_reminder", "arguments": {"reminder_id": rem_del_m.group(1).strip()}}

        # --- Списки (Lists) ---
        if normalized in self.list_show_all:
            return {"tool": "show_list", "arguments": {}}

        list_show_m = self.list_show_p.match(raw_clean)
        if list_show_m:
            return {"tool": "show_list", "arguments": {"name": list_show_m.group(1).strip()}}

        list_create_m = self.list_create_p.match(raw_clean)
        if list_create_m:
            return {"tool": "create_list", "arguments": {"name": list_create_m.group(1).strip()}}

        list_add_m = self.list_add_p.match(raw_clean)
        if list_add_m:
            return {"tool": "add_list_item", "arguments": {"list_name": list_add_m.group(1).strip(), "text": list_add_m.group(2).strip()}}

        # =================================================
        # 7. Память (Memory) - интеграция с match_memory
        # =================================================
        mem = self.match_memory(raw_trimmed)
        if mem:
            action = mem.get("action")
            if action == "remember":
                return {"tool": "remember", "arguments": {"text": mem.get("text", "")}}
            elif action == "recall":
                return {"tool": "recall_memory", "arguments": {}}
            elif action == "forget":
                return {"tool": "forget_memory", "arguments": {"target": mem.get("target", "")}}
            elif action == "search":
                return {"tool": "recall_memory", "arguments": {"query": mem.get("query", "")}}

        # По умолчанию детерминированный инструмент не выбран
        return {
            "tool": None,
            "arguments": {}
        }

    def route(self, user_input: str) -> Dict[str, Any]:
        """
        Главная точка маршрутизации для Agent.process().

        Классифицирует входной запрос на одну из категорий:
        1. {"type": "memory", "action": ..., ...}
        2. {"type": "plan", "action": ..., ...}
        3. {"type": "tool", "tool": ..., "arguments": ...}
        4. {"type": None, "tool": None, "arguments": {}}
        """
        raw_trimmed = user_input.strip()
        if not raw_trimmed:
            return {"type": None, "tool": None, "arguments": {}}

        # 1. Проверяем команды памяти
        mem = self.match_memory(raw_trimmed)
        if mem:
            return {
                "type": "memory",
                **mem
            }

        # 2. Проверяем команды планирования
        plan = self.match_plan(raw_trimmed)
        if plan:
            return {
                "type": "plan",
                **plan
            }

        # 3. Проверяем детерминированные инструменты (Fast-Path)
        tool_res = self.choose_tool(raw_trimmed)
        if tool_res.get("tool"):
            return {
                "type": "tool",
                "tool": tool_res["tool"],
                "arguments": tool_res.get("arguments", {})
            }

        # 4. Проверяем генерацию изображений (Image Sub-Agent Fast-Path)
        image_route = self.match_image(raw_trimmed)
        if image_route:
            return {
                "type": "image",
                **image_route
            }

        # 5. Естественный язык / сложные запросы -> Native Tool Calling
        return {
            "type": None,
            "tool": None,
            "arguments": {}
        }


_router_instance: Optional[CommandRouter] = None


def get_router() -> CommandRouter:
    """Возвращает глобальный экземпляр CommandRouter."""
    global _router_instance
    if _router_instance is None:
        _router_instance = CommandRouter()
    return _router_instance
