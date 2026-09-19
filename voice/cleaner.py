"""
Модуль очистки и подготовки текста для синтеза речи (TTS).
Удаляет разметку Markdown, технические блоки кода, таблицы, служебные символы
и любые emoji / декоративные знаки. Обеспечивает естественные паузы по пунктуации.
"""

import re

# Регулярное выражение для всех диапазонов emoji, пиктограмм и декоративных символов
EMOJI_AND_DECORATIVE_PATTERN = re.compile(
    r"["
    r"\U0001F1E0-\U0001F1FF"  # Flags
    r"\U0001F300-\U0001F5FF"  # Symbols & Pictographs (🎙, 📁, 📊, etc.)
    r"\U0001F600-\U0001F64F"  # Emoticons (😊, 😀, etc.)
    r"\U0001F680-\U0001F6FF"  # Transport
    r"\U0001F700-\U0001F77F"  # Alchemical
    r"\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
    r"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols (🧠, 🤖, 🧹, 🫂, etc.)
    r"\U0001FA00-\U0001FAFF"  # Symbols Extended
    r"\U00002600-\U000026FF"  # Misc symbols (⚠️, ⚡, ☕, etc.)
    r"\U00002700-\U000027BF"  # Dingbats (✅, ✉, ✂, ➜, etc.)
    r"\U00002300-\U000023FF"  # Misc Technical (⏻, ⏱, ⌛, etc.)
    r"\U00002B00-\U00002BFF"  # Misc Symbols and Arrows (⭐, ⭕, etc.)
    r"\U000025A0-\U000025FF"  # Geometric Shapes (●, ■, ▲, ◆, etc.)
    r"\U00002190-\U000021FF"  # Arrows (↵, ←, →, ↔, etc.)
    r"\U0000FE00-\U0000FE0F"  # Variation Selectors
    r"\U0000200D"              # Zero Width Joiner
    r"\U00002022"              # Bullet •
    r"\U00002015"              # Horizontal bar ―
    r"]+",
    flags=re.UNICODE
)


def clean_for_speech(text: str, max_chars: int = 400) -> str:
    """
    Преобразует текстовый ответ Акакия в естественную фразу для озвучивания:
    - убирает markdown-заголовки, списки, ссылки, жирный шрифт, таблицы;
    - вырезает блоки программного кода (заменяя их на краткое уведомление);
    - полностью удаляет emoji и декоративные символы (🎙, ✅, ⚠️, 📁, ● и т.п.);
    - формирует естественные речевые паузы по знакам препинания;
    - если ответ содержит структурированную сводку (## Результат), берёт ключевой результат;
    - обрезает слишком длинные сообщения до комфортной для слуха длины.
    """
    if not text or not isinstance(text, str):
        return ""

    raw = text.strip()

    # 1. Если текст содержит структурированную сводку Акакия (## Результат)
    if "## Результат" in raw:
        parts = raw.split("## Результат", 1)
        res_part = parts[1].strip()
        # Если после Результата есть другие секции, берём до них
        if "## " in res_part:
            res_part = res_part.split("## ", 1)[0].strip()
        if res_part:
            raw = res_part

    # 2. Вырезаем многострочные блоки кода ```...```
    raw = re.sub(r"```[\s\S]*?```", " фрагмент кода. ", raw)

    # 3. Вырезаем инлайн-код `...`
    raw = re.sub(r"`([^`]+)`", r"\1", raw)

    # 4. Убираем markdown-ссылки [текст](url) -> текст
    raw = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw)

    # 5. Убираем разделительные линии (---, ===, ───)
    raw = re.sub(r"^[-=_─—]{2,}\s*$", "", raw, flags=re.MULTILINE)

    # 6. Убираем цитаты и блоки типа > [!NOTE]
    raw = re.sub(r"^>\s*(\[![\w\s]+\])?\s*", "", raw, flags=re.MULTILINE)

    # 7. Убираем markdown-заголовки (###, ##, #)
    raw = re.sub(r"^#{1,6}\s+", "", raw, flags=re.MULTILINE)

    # 8. Заменяем маркеры списков и нумерацию
    raw = re.sub(r"^\s*[-*•●]\s+", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^\s*\d+\.\s+", "", raw, flags=re.MULTILINE)

    # 9. Убираем таблицы (вертикальные разделители колонок)
    raw = raw.replace("|", ", ")

    # 10. Убираем жирный и курсивный шрифт (*text*, **text**, _text_)
    raw = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw)
    raw = re.sub(r"\*([^*]+)\*", r"\1", raw)
    raw = re.sub(r"__([^_]+)__", r"\1", raw)
    raw = re.sub(r"_([^_]+)_", r"\1", raw)

    # 11. Убираем технические маркеры и стрелки
    raw = raw.replace("✓", "Успешно: ").replace("✗", "Ошибка: ")
    raw = raw.replace("->", " в ").replace("=>", " в ")

    # 12. Полное удаление emoji и декоративных знаков
    raw = EMOJI_AND_DECORATIVE_PATTERN.sub("", raw)

    # 13. Формирование естественных пауз: между строками добавляем точку, если её нет
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    processed_lines = []
    for i, s in enumerate(lines):
        if i < len(lines) - 1 and s[-1] not in ".!?:;,-":
            s += "."
        processed_lines.append(s)

    cleaned = " ".join(processed_lines)

    # 14. Схлопываем множественные знаки препинания и пробелы
    cleaned = re.sub(r"\s+([,.:;!?])", r"\1", cleaned)
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 15. Ограничение длины: если фраза слишком длинная, обрезаем по предложению
    if len(cleaned) > max_chars:
        truncated = cleaned[:max_chars]
        last_punct = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last_punct > 100:
            cleaned = truncated[:last_punct + 1]
        else:
            cleaned = truncated.rstrip() + "..."

    return cleaned
