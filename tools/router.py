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

CALL_PREFIX_REGEX = re.compile(
    r"^(?:(?:акакий|пожалуйста|плиз)[,\s:]*)+",
    re.IGNORECASE
)

NON_IMAGE_TARGET_PATTERN = re.compile(
    r"^(?:файл\w*|папк\w*|директори\w*|скрипт\w*|код\w*|класс\w*|функци\w*|модул\w*|тест\w*|коммит\w*|документ\w*|таблиц\w*|презентаци\w*|слайд\w*|задач\w*|заметк\w*|напоминан\w*|список\w*|списк\w*|план\w*|проект\w*)\b",
    re.IGNORECASE
)


def strip_call_prefixes(text: str) -> str:
    """Удаляет обращения и вводные слова вежливости в начале запроса."""
    stripped = CALL_PREFIX_REGEX.sub("", text).strip()
    return stripped if stripped else text


class CommandRouter:
    """
    Детерминированный маршрутизатор команд.

    Определяет намерение пользователя по формальным синтаксическим шаблонам
    и возвращает структурированное решение о маршрутизации.
    """

    def __init__(self):
        self._init_patterns()

    def strip_call_prefixes(self, text: str) -> str:
        """Удаляет обращения и вводные слова вежливости в начале запроса."""
        return strip_call_prefixes(text)

    def _init_patterns(self):
        # 1. Файлы проекта
        self.file_search_patterns = [
            re.compile(r"^(?:найди|найти)(?:\s+мне)?(?:\s+в\s+проекте)?\s+файл\s+([^\s,!?;:]+)$", re.IGNORECASE),
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
            "покажи мне список файлов проекта",
            "покажи мне файлы проекта",
            "покажи мне список файлов",
            "покажи мне файлы",
        }
        self.structure_exact = {
            "покажи структуру проекта",
            "покажи структуру проекта акакия",
            "структура проекта",
            "покажи мне структуру проекта",
            "покажи мне структуру проекта акакия",
        }
        self.func_pattern = re.compile(r"^(?:найди|найти)(?:\s+мне)?\s+функцию\s+([a-zA-Z_0-9]+)$", re.IGNORECASE)
        self.search_pattern = re.compile(r"^(?:поиск\s+по\s+проекту|(?:найди|найти)(?:\s+мне)?\s+в\s+проекте\s+текст)\s+(.+)$", re.IGNORECASE)

        # 2. Бытовые команды: Задачи
        self.task_create_p1 = re.compile(r"^(?:создай|добавь|новая)(?:\s+мне)?\s+задач[ауе]\s+(.+)$", re.IGNORECASE)
        self.task_create_p2 = re.compile(r"^задача:\s*(.+)$", re.IGNORECASE)
        self.task_list_all = {
            "покажи задачи", "покажи все задачи", "список задач", "мои задачи", "задачи", "показать задачи",
            "покажи мне задачи", "покажи мне все задачи", "показать мне задачи"
        }
        self.task_list_pending = {"активные задачи", "покажи активные задачи", "невыполненные задачи", "покажи мне активные задачи"}
        self.task_list_completed = {"выполненные задачи", "покажи выполненные задачи", "завершенные задачи", "покажи мне выполненные задачи"}
        self.task_done_p = re.compile(r"^(?:выполни|отметь\s+(?:выполненной|сделанной)|закрой|сделай)\s+задач[уе]\s+([#№]?\d+|.+)$", re.IGNORECASE)
        self.task_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+задач[уие]?\s+(.+)$", re.IGNORECASE)
        self.task_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:юю|ие|их|яя)(?:\s+(?:\d+|[а-яё]+))?)\s+задач[иа-я]*$", re.IGNORECASE)

        # 3. Бытовые команды: Заметки
        self.note_create_p1 = re.compile(r"^(?:создай|добавь|новая|запиши)(?:\s+мне)?\s+заметк[ауе]\s+([^:]+?)(?:\s*:\s*|\s+текст\s+)(.+)$", re.IGNORECASE)
        self.note_create_p2 = re.compile(r"^(?:создай|добавь|новая|запиши)(?:\s+мне)?\s+заметк[ауе]\s+(.+)$", re.IGNORECASE)
        self.note_list_exact = {
            "покажи заметки", "список заметок", "мои заметки", "заметки", "показать заметки", "все заметки",
            "покажи мне заметки", "показать мне заметки", "покажи мне все заметки"
        }
        self.note_search_p = re.compile(r"^(?:найди|поиск)(?:\s+в)?\s+заметк[а-я]*\s+(.+)$", re.IGNORECASE)
        self.note_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+заметк[уие]?\s+(.+)$", re.IGNORECASE)
        self.note_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:юю|ие|их|яя)(?:\s+(?:\d+|[а-яё]+))?)\s+заметк[иа-я]*$", re.IGNORECASE)

        # 4. Бытовые команды: Напоминания
        self.rem_create_p = re.compile(r"^(?:напомни(?:\s+мне)?|создай(?:\s+мне)?\s+напоминание|новое\s+напоминание)\s+(.+?)\s+((?:в|через|завтра|каждый|каждую|каждые|по\s+будням|ежедневно)\s+.+)$", re.IGNORECASE)
        self.rem_list_exact = {
            "покажи напоминания", "список напоминаний", "мои напоминания", "напоминания", "показать напоминания",
            "покажи мне напоминания", "показать мне напоминания"
        }
        self.rem_done_p = re.compile(r"^(?:выполни|отметь\s+(?:выполненным|сделанным)|закрой|сделай)\s+напоминани[ея]?\s+([#№]?\d+|.+)$", re.IGNORECASE)
        self.rem_del_p1 = re.compile(r"^(?:удали|удалить|сотри)\s+напоминани[ея]?\s+(.+)$", re.IGNORECASE)
        self.rem_del_p2 = re.compile(r"^(?:удали|удалить|сотри)\s+(?:все\s+)?(последн(?:ее|ие|их)(?:\s+(?:\d+|[а-яё]+))?)\s+напоминан[иеа-я]*$", re.IGNORECASE)

        # 5. Бытовые команды: Списки
        self.list_show_all = {
            "покажи списки", "список списков", "списки", "показать списки",
            "покажи мне списки", "показать мне списки"
        }
        self.list_show_p = re.compile(r"^(?:покажи|открой)(?:\s+мне)?\s+список\s+(.+)$", re.IGNORECASE)
        self.list_create_p = re.compile(r"^(?:создай|добавь|новый)(?:\s+мне)?\s+список\s+(.+)$", re.IGNORECASE)
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
            "покажи мне память",
            "показать мне память",
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
        self.plan_create_p = re.compile(r"^(?:создай|составь|сделай)(?:\s+мне)?\s+план(?:\s*:\s*|\s+)(.+)$", re.IGNORECASE)
        self.plan_create_exact = {"создай план", "создать план", "составь план", "составить план", "создай мне план", "составь мне план"}
        self.plan_execute_exact = {"выполни план", "выполнить план", "запусти план"}
        self.plan_get_exact = {"покажи план", "текущий план", "показать план", "покажи мне план"}
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

        # 10. Явный вызов субагента (Sub-Agent invocation)
        self.subagent_explicit_p = re.compile(
            r"^(?:(?:запусти|вызови|делегируй|передай)\s+(?:субагент[уа]?|агент[уа]?)|субагент|агент)\s+([a-zA-Z0-9_\-]+)(?:\s*:\s*|\s+)(.+)$",
            re.IGNORECASE
        )

    def match_memory(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос детерминированной командой памяти.
        Возвращает словарь с параметрами действия или None.
        """
        raw_trimmed = strip_call_prefixes(user_input.strip())
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
        raw_trimmed = strip_call_prefixes(user_input.strip())
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

    def match_subagent(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет явный вызов специализированного sub-agent'а.
        Например:
        - 'субагент echo: тестовое сообщение'
        - 'запусти субагента image: нарисуй кота'
        - 'вызови агента echo привет'
        """
        raw_trimmed = strip_call_prefixes(user_input.strip())
        if not raw_trimmed:
            return None

        m = self.subagent_explicit_p.match(raw_trimmed)
        if m:
            agent_name = m.group(1).strip().lower()
            task_text = m.group(2).strip()
            if agent_name and task_text:
                return {
                    "action": "run",
                    "agent": agent_name,
                    "task": task_text
                }
    def match_presentation(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос командой создания презентации.
        Распознает естественные шаблоны:
        - 'создай презентацию [по/на тему/про] ...'
        - 'сделай презентацию [по/на тему/про] ...'
        - 'сгенерируй презентацию [по/на тему/про] ...'
        - 'презентация [по/на тему/про]: ...'
        - 'создай слайды [по/на тему/про] ...'
        """
        raw_trimmed = user_input.strip()
        if not raw_trimmed:
            return None

        body = strip_call_prefixes(raw_trimmed)

        # 1. Шаблоны с управляющими глаголами
        verb_pattern = re.compile(
            r"^(?:создай|создайте|создать|сделай|сделайте|сделать|сгенерируй|сгенерируйте|сгенерировать|подготовь|подготовьте|подготовить)"
            r"(?:\s+мне)?\s+(?:презентаци\w*|слайд\w*)(?:\s*(?:на\s+тему|про|по|о|об))?(?:\s*:\s*|[,\s]+)",
            re.IGNORECASE
        )
        m = verb_pattern.match(body)
        if m:
            remainder = body[m.end():].strip().strip("\"'«»“”")
            if remainder:
                return {
                    "action": "create",
                    "prompt": remainder,
                    "title": remainder
                }

        # 2. Шаблоны прямого ввода темы: "презентация: <тема>" или "презентация на тему <тема>"
        intro_pattern = re.compile(
            r"^(?:презентаци\w*|слайд\w*)(?:\s*(?:на\s+тему|про|по|о|об))?(?:\s*:\s*|[,\s]+)",
            re.IGNORECASE
        )
        m2 = intro_pattern.match(body)
        if m2:
            remainder = body[m2.end():].strip().strip("\"'«»“”")
            if remainder:
                return {
                    "action": "create",
                    "prompt": remainder,
                    "title": remainder
                }

        return None

    def match_image(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет, является ли запрос командой генерации изображения,
        и извлекает параметры (prompt, aspect_ratio, width, height, count).
        """
        raw_trimmed = user_input.strip()
        if not raw_trimmed:
            return None

        # Нормализованная проверка обращения в начале: "Акакий, ...", "Пожалуйста, ..."
        body = strip_call_prefixes(raw_trimmed)

        # 1. Проверяем наличие управляющего глагола генерации/рисования в начале
        verb_pattern = re.compile(
            r"^(?:создай|создайте|создать|сгенерируй|сгенерируйте|сгенерировать|сделай|сделайте|сделать|нарисуй|нарисуйте|нарисовать|изобрази|изобразите|изобразить|отрисуй|отрисуйте|отрисовать)(?:\s+мне)?(?:[,\s]+пожалуйста)?(?:\s*:\s*|[,\s]+)",
            re.IGNORECASE
        )
        verb_match = verb_pattern.match(body)
        if not verb_match:
            return None

        is_pure_draw = bool(re.match(
            r"^(?:нарисуй|нарисуйте|нарисовать|изобрази|изобразите|изобразить|отрисуй|отрисуйте|отрисовать)\b",
            body,
            re.IGNORECASE
        ))

        remainder = body[verb_match.end():].strip()
        if not remainder:
            return None

        # Исключаем запросы к файловой системе, коду и бытовым сущностям
        if NON_IMAGE_TARGET_PATTERN.match(remainder):
            return None

        # Инициализация параметров по умолчанию
        aspect_ratio = "square"
        width = 1024
        height = 1024
        count = 1

        # 2.1. Поиск явного разрешения WxH (например: 1280x720, 1024х1024, 800*600)
        wxh_match = re.search(r"\b(\d{3,4})\s*[xхXХ*×]\s*(\d{3,4})\b", remainder)
        if wxh_match:
            rw, rh = int(wxh_match.group(1)), int(wxh_match.group(2))
            from tools.agents.image import safe_validate_resolution
            width, height = safe_validate_resolution(rw, rh)
            aspect_ratio = "custom"
            remainder = remainder[:wxh_match.start()] + " " + remainder[wxh_match.end():]

        # Общий паттерн служебных существительных (изображение, картинка, рисунок, арт, фото и т.д.)
        img_noun = r"(?:изображен\w*|картинк\w*|картинок|рисун\w*|иллюстрац\w*|арт\w*|фото\w*|постер\w*|штук\w*|шт)"

        # 2.2. Поиск количества изображений (цифры или словесные числительные 1..4)
        count_noun_pattern = re.compile(
            rf"\b(\d+|одно|один|одну|два|две|три|четыре|пару|пара)\s+(?:(?:квадратн\w*|широк\w*|горизонтальн\w*|альбомн\w*|пейзажн\w*|вертикальн\w*|портретн\w*|landscape|portrait|16:9|9:16|1:1)\s+)?{img_noun}\b",
            re.IGNORECASE
        )
        count_match = count_noun_pattern.search(remainder)
        if not count_match:
            count_match = re.match(
                rf"^(\d+|одно|один|одну|два|две|три|четыре|пару|пара)\s+{img_noun}\b",
                remainder,
                re.IGNORECASE
            )

        if count_match:
            raw_c = count_match.group(1).lower()
            word_map = {
                "один": 1, "одно": 1, "одну": 1,
                "два": 2, "две": 2, "три": 3, "четыре": 4,
                "пару": 2, "пара": 2
            }
            if raw_c in word_map:
                count = word_map[raw_c]
            else:
                try:
                    count = int(raw_c)
                except ValueError:
                    count = 1
            from tools.agents.image import safe_validate_count
            count = safe_validate_count(count)
            c_start = count_match.start(1)
            c_end = count_match.end(1)
            remainder = remainder[:c_start] + " " + remainder[c_end:]

        # 2.3. Поиск ориентации / пресета (если не было явного WxH)
        has_aspect_preset = False
        if aspect_ratio != "custom":
            # Landscape
            m_land = re.search(
                rf"\b(широк\w*|горизонтальн\w*|альбомн\w*|пейзажн\w*|landscape|16:9)\s+{img_noun}\b"
                rf"|\b{img_noun}\s+(широк\w*|горизонтальн\w*|альбомн\w*|пейзажн\w*)\b"
                r"|,\s*(широк\w*|горизонтальн\w*|landscape|16:9)\s*$"
                r"|\b(landscape|16:9)\b",
                remainder,
                re.IGNORECASE
            )
            if m_land:
                aspect_ratio = "landscape"
                has_aspect_preset = True
                width = 1216
                height = 832
                for g_idx in range(1, 5):
                    if m_land.group(g_idx):
                        remainder = remainder[:m_land.start(g_idx)] + " " + remainder[m_land.end(g_idx):]
                        break
            else:
                # Portrait
                m_port = re.search(
                    rf"\b(вертикальн\w*|портретн\w*|portrait|9:16)\s+{img_noun}\b"
                    rf"|\b{img_noun}\s+(вертикальн\w*|портретн\w*)\b"
                    r"|,\s*(вертикальн\w*|портретн\w*|portrait|9:16)\s*$"
                    r"|\b(portrait|9:16)\b",
                    remainder,
                    re.IGNORECASE
                )
                if m_port:
                    aspect_ratio = "portrait"
                    has_aspect_preset = True
                    width = 832
                    height = 1216
                    for g_idx in range(1, 5):
                        if m_port.group(g_idx):
                            remainder = remainder[:m_port.start(g_idx)] + " " + remainder[m_port.end(g_idx):]
                            break
                else:
                    # Square
                    m_sq = re.search(
                        rf"\b(квадратн\w*|квадрат|1:1)\s+{img_noun}\b"
                        rf"|\b{img_noun}\s+(квадратн\w*|квадрат|1:1)\b"
                        r"|,\s*(квадратн\w*|квадрат|1:1)\s*$"
                        r"|\b(1:1)\b",
                        remainder,
                        re.IGNORECASE
                    )
                    if m_sq:
                        aspect_ratio = "square"
                        has_aspect_preset = True
                        width = 1024
                        height = 1024
                        for g_idx in range(1, 5):
                            if m_sq.group(g_idx):
                                remainder = remainder[:m_sq.start(g_idx)] + " " + remainder[m_sq.end(g_idx):]
                                break

        # 2.4. Удаление ведущих служебных существительных (изображение, картинка и т.д.)
        noun_pattern = re.compile(
            rf"^\s*{img_noun}(?:\s*:\s*|[,\s]+|$)",
            re.IGNORECASE
        )
        has_leading_img_noun = bool(noun_pattern.search(remainder))
        remainder = noun_pattern.sub(" ", remainder)

        # 2.5. Очистка предлогов и концевой пунктуации
        clean_prompt = remainder.strip().lstrip(":").strip()
        clean_prompt = re.sub(r"^(?:мне|пожалуйста)[,\s]+", "", clean_prompt, flags=re.IGNORECASE).strip()
        clean_prompt = clean_prompt.strip(".,;:!? ")

        if len(clean_prompt) < 2:
            return None

        # Для не-рисовальных глаголов (создай, сгенерируй, сделай)
        # цель должна быть явно визуальной:
        # либо служебное существительное (изображение, фото, картинка, арт и т.д.),
        # либо явное разрешение / пресет ориентации / количество изображений.
        if not is_pure_draw:
            if not has_leading_img_noun and not count_match and not has_aspect_preset and aspect_ratio != "custom":
                return None

        return {
            "action": "generate",
            "prompt": clean_prompt,
            "aspect_ratio": aspect_ratio,
            "width": width,
            "height": height,
            "count": count
        }

    def choose_tool(self, user_input: str) -> Dict[str, Any]:
        """
        Определяет инструмент для детерминированных fast-path команд (CLI, Household, Memory).
        Возвращает словарь вида {"tool": str | None, "arguments": dict}.
        """
        raw_trimmed = strip_call_prefixes(user_input.strip())
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
        4. {"type": "subagent", "agent": ..., "task": ...}
        5. {"type": "image", "action": "generate", "prompt": ..., ...}
        6. {"type": None, "tool": None, "arguments": {}}
        """
        raw_trimmed = user_input.strip()
        if not raw_trimmed:
            return {"type": None, "tool": None, "arguments": {}}

        cleaned = strip_call_prefixes(raw_trimmed)

        # 1. Проверяем команды памяти
        mem = self.match_memory(cleaned)
        if mem:
            return {
                "type": "memory",
                **mem
            }

        # 2. Проверяем команды планирования
        plan = self.match_plan(cleaned)
        if plan:
            return {
                "type": "plan",
                **plan
            }

        # 3. Проверяем детерминированные инструменты (Fast-Path)
        tool_res = self.choose_tool(cleaned)
        if tool_res.get("tool"):
            return {
                "type": "tool",
                "tool": tool_res["tool"],
                "arguments": tool_res.get("arguments", {})
            }

        # 4. Проверяем явный вызов субагента (Sub-Agent Fast-Path)
        subagent_route = self.match_subagent(cleaned)
        if subagent_route:
            if subagent_route.get("agent") == "image":
                task_txt = subagent_route.get("task", "")
                img_data = self.match_image(task_txt) or self.match_image(f"нарисуй {task_txt}")
                if img_data:
                    return {
                        "type": "image",
                        **img_data
                    }
            elif subagent_route.get("agent") == "presentation":
                task_txt = subagent_route.get("task", "")
                return {
                    "type": "presentation",
                    "action": "create",
                    "prompt": task_txt,
                    "title": task_txt
                }
            return {
                "type": "subagent",
                **subagent_route
            }

        # 5. Проверяем создание презентаций (Presentation Sub-Agent Fast-Path)
        pres_route = self.match_presentation(cleaned)
        if pres_route:
            return {
                "type": "presentation",
                **pres_route
            }

        # 6. Проверяем генерацию изображений (Image Sub-Agent Fast-Path)
        image_route = self.match_image(cleaned)
        if image_route:
            return {
                "type": "image",
                **image_route
            }

        # 7. Естественный язык / сложные запросы -> Native Tool Calling
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
