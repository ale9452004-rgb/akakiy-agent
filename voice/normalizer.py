"""
Модуль нормализации текста для синтеза речи (TTS).
Обеспечивает вербализацию чисел, вербализацию и фонетическую транслитерацию латиницы
(технических терминов, команд, имён файлов, расширений и путей) в кириллицу,
предотвращая потерю цифр, английских слов и окончаний в Silero TTS.
"""

import re
from typing import Optional

# Таблицы числительных русского языка
_UNITS_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_UNITS_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_UNITS_N = ["", "одно", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]

_TEENS = [
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"
]

_TENS = [
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто"
]

_HUNDREDS = [
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот"
]

_ORD_BASE = {
    1: ("перв", "ый"),
    2: ("втор", "ой"),
    3: ("трет", "ий"),
    4: ("четвёрт", "ый"),
    5: ("пят", "ый"),
    6: ("шест", "ой"),
    7: ("седьм", "ой"),
    8: ("восьм", "ой"),
    9: ("девят", "ый"),
    10: ("десят", "ый"),
    11: ("одиннадцат", "ый"),
    12: ("двенадцат", "ый"),
    13: ("тринадцат", "ый"),
    14: ("четырнадцат", "ый"),
    15: ("пятнадцат", "ый"),
    16: ("шестнадцат", "ый"),
    17: ("семнадцат", "ый"),
    18: ("восемнадцат", "ый"),
    19: ("девятнадцат", "ый"),
    20: ("двадцат", "ый"),
    30: ("тридцат", "ый"),
    40: ("сороков", "ой"),
    50: ("пятидесят", "ый"),
    60: ("шестидесят", "ый"),
    70: ("семидесят", "ый"),
    80: ("восьмидесят", "ый"),
    90: ("девяност", "ый"),
    100: ("сот", "ый"),
}


def _verbalize_triplet(n: int, gender: str = "m") -> str:
    """Преобразует число от 0 до 999 в строку русских слов."""
    words = []
    h = n // 100
    t = (n % 100) // 10
    u = n % 10
    if h:
        words.append(_HUNDREDS[h])
    if t == 1:
        words.append(_TEENS[u])
    else:
        if t > 1:
            words.append(_TENS[t])
        if u > 0:
            if gender == "f":
                words.append(_UNITS_F[u])
            elif gender == "n":
                words.append(_UNITS_N[u])
            else:
                words.append(_UNITS_M[u])
    return " ".join(words)


def verbalize_integer(n: int) -> str:
    """Преобразует целое число в русские слова."""
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + verbalize_integer(-n)

    parts = []

    # Миллиарды
    billions = (n // 1_000_000_000) % 1000
    if billions:
        w = _verbalize_triplet(billions, "m")
        last_d = billions % 10 if (billions % 100) not in (11, 12, 13, 14) else 0
        suf = "миллиард" if last_d == 1 else ("миллиарда" if last_d in (2, 3, 4) else "миллиардов")
        parts.append(f"{w} {suf}")

    # Миллионы
    millions = (n // 1_000_000) % 1000
    if millions:
        w = _verbalize_triplet(millions, "m")
        last_d = millions % 10 if (millions % 100) not in (11, 12, 13, 14) else 0
        suf = "миллион" if last_d == 1 else ("миллиона" if last_d in (2, 3, 4) else "миллионов")
        parts.append(f"{w} {suf}")

    # Тысячи
    thousands = (n // 1000) % 1000
    if thousands:
        w = _verbalize_triplet(thousands, "f")
        last_d = thousands % 10 if (thousands % 100) not in (11, 12, 13, 14) else 0
        suf = "тысяча" if last_d == 1 else ("тысячи" if last_d in (2, 3, 4) else "тысяч")
        parts.append(f"{w} {suf}")

    # Единицы (0..999)
    rem = n % 1000
    if rem:
        parts.append(_verbalize_triplet(rem, "m"))

    return " ".join(parts).strip()


def verbalize_ordinal(n: int, suffix: str = "й") -> str:
    """Преобразует порядковое число с суффиксом (например, 1-й, 2-я, 2-го, 2-му, 5-м)."""
    suf = suffix.lower().strip("-–—")

    def _inflect_base(stem: str, base_end: str, is_tretiy: bool = False) -> str:
        if is_tretiy:
            if suf in ("я", "ая", "яя"): return stem + "ья"
            if suf in ("е", "ое", "ее"): return stem + "ье"
            if suf in ("го", "ого", "его"): return stem + "ьего"
            if suf in ("му", "ому", "ему"): return stem + "ьему"
            if suf in ("м", "ом", "ем", "ым", "им"): return stem + "ьим"
            if suf in ("х", "ых", "их"): return stem + "ьих"
            return stem + "ий"

        if suf in ("я", "ая", "яя"): return stem + "ая"
        if suf in ("е", "ое", "ее"): return stem + "ое"
        if suf in ("го", "ого", "его"): return stem + "ого"
        if suf in ("му", "ому", "ему"): return stem + "ому"
        if suf in ("м", "ом", "ем", "ым", "им"): return stem + "ым"
        if suf in ("х", "ых", "их"): return stem + "ых"
        return stem + base_end

    if n in _ORD_BASE:
        stem, base_end = _ORD_BASE[n]
        return _inflect_base(stem, base_end, is_tretiy=(n == 3))

    # Для составных чисел: старшая часть как количественное, последняя как порядковое
    if n > 20:
        base = (n // 10) * 10
        rem = n % 10
        if rem == 0:
            if base in _ORD_BASE:
                stem, base_end = _ORD_BASE[base]
                return _inflect_base(stem, base_end)
            return verbalize_integer(n)
        return f"{verbalize_integer(base)} {verbalize_ordinal(rem, suffix)}"

    return verbalize_integer(n)


# Словарь терминов разработчика и часто встречающихся английских слов
DEV_TERMS = {
    # Git
    "git": "гит",
    "commit": "коммит",
    "push": "пуш",
    "pull": "пулл",
    "branch": "бранч",
    "diff": "дифф",
    "log": "лог",
    "clone": "клон",
    "merge": "мердж",
    "fetch": "фетч",
    "checkout": "чекаут",
    "rebase": "ребейз",
    "stash": "стэш",
    "status": "статус",
    "reset": "ресет",
    "init": "инит",
    "remote": "ремоут",
    "origin": "ориджин",
    "master": "мастер",
    "main": "мейн",
    "head": "хед",
    "repo": "репозиторий",
    "repository": "репозиторий",
    # Языки, библиотеки и стек
    "python": "пайтон",
    "pytorch": "пайторч",
    "torch": "торч",
    "silero": "силеро",
    "vosk": "воск",
    "ollama": "оллама",
    "qwen": "квен",
    "windows": "виндовс",
    "powershell": "пауэршелл",
    "linux": "линукс",
    "bash": "баш",
    "cmd": "цэ эм дэ",
    "terminal": "терминал",
    "console": "консоль",
    "agent": "агент",
    "planner": "планнер",
    "executor": "экзекьютор",
    "dispatcher": "диспетчер",
    "registry": "реджистри",
    "cleaner": "клинер",
    "service": "сервис",
    "sounddevice": "саунд-девайс",
    "pywin32": "пай-вин-32",
    "onecore": "ван-кор",
    "sapi": "сапи",
    "pip": "пип",
    "venv": "вэнв",
    "conda": "конда",
    # Оборудование и архитектура
    "cpu": "цэ пэ у",
    "gpu": "джи пи ю",
    "ram": "рам",
    "rtx": "эр тэ икс",
    "gtx": "джи тэ икс",
    "usb": "ю эс би",
    "ssd": "эс эс дэ",
    "hdd": "аш дэ дэ",
    "os": "о эс",
    # Веб, форматы и протоколы
    "api": "апи",
    "gui": "гуи",
    "ui": "ю ай",
    "cli": "кли",
    "repl": "репл",
    "ast": "аст",
    "json": "джейсон",
    "yaml": "ямл",
    "yml": "ямл",
    "xml": "икс эм эль",
    "html": "хтмл",
    "css": "кээсэс",
    "sql": "эскуэль",
    "http": "хттп",
    "https": "хттпс",
    "url": "урл",
    "uri": "юри",
    "ip": "ай пи",
    "tcp": "ти си пи",
    "udp": "ю ди пи",
    "dns": "ди эн эс",
    "ssh": "эс эс аш",
    "rest": "рест",
    "grpc": "джи эр пи си",
    "id": "айди",
    "token": "токен",
    "jwt": "джи ви ти",
    "sdk": "эс дэ ка",
    "dev": "дев",
    "pr": "пи ар",
    "ci": "си ай",
    "cd": "си ди",
    # Состояния, команды и частые слова
    "ok": "ок",
    "true": "тру",
    "false": "фолс",
    "none": "нан",
    "null": "нулл",
    "error": "эррор",
    "errors": "ошибки",
    "warning": "ворнинг",
    "warnings": "предупреждения",
    "info": "инфо",
    "debug": "дебаг",
    "todo": "туду",
    "fixme": "фиксми",
    "bug": "баг",
    "test": "тест",
    "tests": "тесты",
    "pass": "пасс",
    "passed": "пройдено",
    "fail": "фейл",
    "failed": "провалено",
    "skip": "скип",
    "skipped": "пропущено",
    "done": "готово",
    "success": "успешно",
    "successful": "успешно",
    "successfully": "успешно",
    "exit": "выход",
    "quit": "выход",
    "help": "помощь",
    "start": "старт",
    "stop": "стоп",
    "file": "файл",
    "files": "файлы",
    "code": "код",
    "user": "пользователь",
    "chat": "чат",
    "voice": "войс",
    "akakiy": "акакий",
    "ru": "ру",
    "en": "ен",
    "model": "модель",
    "models": "модели",
    "stream": "стрим",
    "timeout": "таймаут",
    "device": "девайс",
    "run": "запуск",
    "build": "билд",
    "task": "задача",
    "tasks": "задачи",
    "step": "шаг",
    "steps": "шаги",
    "version": "версия",
    "found": "найдено",
    "not": "нот",
    "desktop": "десктоп",
    "shell": "шелл",
    "mode": "режим",
    "app": "приложение",
    "root": "рут",
    "path": "путь",
    "directory": "директория",
    "dir": "дир",
    "read": "чтение",
    "write": "запись",
    "edit": "редактирование",
    "delete": "удаление",
    "create": "создание",
    "check": "проверка",
}

# Фонетические правила замены для произвольных английских слов
_PHONETIC_RULES = [
    (r"(?i)tion\b", "шн"),
    (r"(?i)sion\b", "жн"),
    (r"(?i)ght", "т"),
    (r"(?i)igh", "ай"),
    (r"(?i)sch", "ш"),
    (r"(?i)tch", "ч"),
    (r"(?i)sh", "ш"),
    (r"(?i)ch", "ч"),
    (r"(?i)ph", "ф"),
    (r"(?i)th", "т"),
    (r"(?i)wh", "в"),
    (r"(?i)ck", "к"),
    (r"(?i)qu", "кв"),
    (r"(?i)wr", "р"),
    (r"(?i)kn", "н"),
    (r"(?i)ee", "и"),
    (r"(?i)oo", "у"),
    (r"(?i)ea", "и"),
    (r"(?i)ai|ay", "эй"),
    (r"(?i)oi|oy", "ой"),
    (r"(?i)au|aw", "о"),
    (r"(?i)ou|ow", "ау"),
    (r"(?i)c(?=[eiy])", "с"),
    (r"(?i)g(?=[eiy])", "дж"),
    (r"(?i)x", "кс"),
]

_SINGLE_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "y": "и", "z": "з"
}

_ISOLATED_LETTERS = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф",
    "g": "джи", "h": "эйч", "i": "ай", "j": "джей", "k": "кей", "l": "эль",
    "m": "эм", "n": "эн", "o": "о", "p": "пи", "q": "кью", "r": "ар",
    "s": "эс", "t": "ти", "u": "ю", "v": "вэ", "w": "дабл-ю", "x": "икс",
    "y": "вай", "z": "зет"
}

# Распространённые расширения файлов
FILE_EXTENSIONS = {
    ".py": "точка пай",
    ".json": "точка джейсон",
    ".txt": "точка тэ икс тэ",
    ".md": "точка эм ди",
    ".pt": "точка пэ тэ",
    ".log": "точка лог",
    ".sh": "точка эс аш",
    ".bat": "точка бат",
    ".ps1": "точка пэ эс один",
    ".env": "точка енв",
    ".yaml": "точка ямл",
    ".yml": "точка ямл",
    ".wav": "точка вав",
    ".mp3": "точка эм пэ три",
    ".csv": "точка цэ эс вэ",
    ".html": "точка хтмл",
    ".css": "точка кээсэс",
    ".js": "точка джей эс",
    ".ts": "точка тэ эс",
}

DRIVE_MAP = {
    "c": "диск цэ:",
    "d": "диск дэ:",
    "e": "диск е:",
    "f": "диск эф:",
    "a": "диск а:",
    "b": "диск б:",
}


def transliterate_english_word(word: str) -> str:
    """Транслитерирует отдельное английское слово в читаемую кириллицу."""
    low = word.lower()
    if low in DEV_TERMS:
        return DEV_TERMS[low]

    # Изолированная буква
    if len(low) == 1 and low in _ISOLATED_LETTERS:
        return _ISOLATED_LETTERS[low]

    # Если слово короткое и только из согласных (аббревиатура, например 'pr', 'cfg', 'src')
    if len(low) <= 4 and not any(v in low for v in "aeiouy"):
        return " ".join(_ISOLATED_LETTERS.get(c, c) for c in low)

    res = low
    for pattern, repl in _PHONETIC_RULES:
        res = re.sub(pattern, repl, res)

    chars = []
    for c in res:
        chars.append(_SINGLE_LETTERS.get(c, c))
    return "".join(chars)


def verbalize_latin_and_symbols(text: str) -> str:
    """
    Преобразует английские слова, расширения файлов, пути и технические символы в кириллицу.
    """
    if not text:
        return ""

    res = text

    # 1. Расширения файлов (.py, .json, etc.)
    for ext, repl in FILE_EXTENSIONS.items():
        escaped_ext = re.escape(ext)
        res = re.sub(rf"(?<=\w){escaped_ext}(?=\b|\s|[.,!?:;]|$)", f" {repl}", res, flags=re.IGNORECASE)

    # 2. Диски Windows (например: C:\ или D:/)
    res = re.sub(r"(?i)\b([a-z]):[\\/]", lambda m: DRIVE_MAP.get(m.group(1).lower(), f"диск {m.group(1)}:") + " ", res)

    # 3. Слеши в путях файлов заменяем на пробелы
    res = re.sub(r"[\\/]+", " ", res)

    # 4. Обработка смешанных буквенно-цифровых токенов (например v4_ru, win32com, h264, utf-8)
    def _replace_mixed_token(match):
        token = match.group(0)
        # Если это просто чистое слово, пропускаем для общего словаря
        sub_parts = re.findall(r"[a-zA-Z]+|\d+", token)
        verbalized = []
        for p in sub_parts:
            if p.isdigit():
                verbalized.append(verbalize_integer(int(p)))
            else:
                verbalized.append(DEV_TERMS.get(p.lower(), transliterate_english_word(p)))
        return " ".join(verbalized)

    # Ищем токены, содержащие одновременно латиницу и цифры/дефисы/подчёркивания
    res = re.sub(r"\b(?=[a-zA-Z0-9_-]*[a-zA-Z])(?=[a-zA-Z0-9_-]*\d)[a-zA-Z0-9_-]+\b", _replace_mixed_token, res)

    # 5. Обработка чисто латинских слов
    def _replace_latin_word(match):
        w = match.group(0)
        return DEV_TERMS.get(w.lower(), transliterate_english_word(w))

    res = re.sub(r"\b[a-zA-Z]+\b", _replace_latin_word, res)

    return res


def verbalize_numbers(text: str) -> str:
    """
    Преобразует числа, проценты, диапазоны и коды в эквивалентные русские слова.
    """
    if not text:
        return ""

    res = text

    # 1. Проценты: 100% -> сто процентов
    def _replace_percent(m):
        n_str = m.group(1)
        val = int(n_str)
        w = verbalize_integer(val)
        last_d = val % 10 if (val % 100) not in (11, 12, 13, 14) else 0
        suf = "процент" if last_d == 1 else ("процента" if last_d in (2, 3, 4) else "процентов")
        return f"{w} {suf}"

    res = re.sub(r"\b(\d+)\s*%", _replace_percent, res)

    # 2. Порядковые числительные с дефисом: 1-й, 2-го, 15-я, 2026-й
    def _replace_ordinal(m):
        val = int(m.group(1))
        suffix = m.group(2)
        return verbalize_ordinal(val, suffix)

    res = re.sub(r"\b(\d+)[-–—]([а-яА-Я]+)\b", _replace_ordinal, res)

    # 3. Десятичные дроби и версии: 2.0, 3.13, 3.14
    def _replace_decimal(m):
        int_part = int(m.group(1))
        frac_part = int(m.group(2))
        return f"{verbalize_integer(int_part)} точка {verbalize_integer(frac_part)}"

    res = re.sub(r"\b(\d+)[.,](\d+)\b", _replace_decimal, res)

    # 4. Диапазоны чисел: 10-15 -> десять тире пятнадцать
    def _replace_range(m):
        v1 = int(m.group(1))
        v2 = int(m.group(2))
        return f"{verbalize_integer(v1)} тире {verbalize_integer(v2)}"

    res = re.sub(r"\b(\d+)\s*[-–—]\s*(\d+)\b", _replace_range, res)

    # 5. Отрицательные числа: -5 -> минус пять
    def _replace_negative(m):
        val = int(m.group(1))
        return f"минус {verbalize_integer(val)}"

    res = re.sub(r"(?:(?<=\s)|(?<=^))[-−](\d+)\b", _replace_negative, res)

    # 6. Обычные целые числа
    def _replace_integer(m):
        val = int(m.group(0))
        return verbalize_integer(val)

    res = re.sub(r"\b\d+\b", _replace_integer, res)

    # 7. Номера: #5 -> номер пять
    res = re.sub(r"#\s*(\d+)", r"номер \1", res)

    return res


def normalize_text_for_speech(text: str) -> str:
    """
    Полная нормализация текста перед подачей в Silero TTS:
    1. Вербализует числа, проценты, версии, порядковые числительные.
    2. Преобразует латиницу, расширения файлов, пути и термины в кириллицу.
    3. Нормализует пробелы и сохраняет пунктуацию для естественных пауз.
    """
    if not text or not isinstance(text, str):
        return ""

    # Сначала заменяем числа с расширениями и спецсимволами
    text = verbalize_numbers(text)

    # Затем заменяем латиницу и технические символы
    text = verbalize_latin_and_symbols(text)

    # Схлопываем лишние пробелы перед знаками препинания
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text
