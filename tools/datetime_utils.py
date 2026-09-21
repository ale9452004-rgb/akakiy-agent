"""
Модуль утилит работы со временем и датами для ассистента Акакия.

Содержит чистые функции разбора пользовательских строк времени (напоминаний, событий)
в стандартизированный ISO-формат.
"""

from datetime import datetime, timedelta
import re
from typing import Optional, Tuple


def parse_repeat_rule(time_str: str) -> Tuple[Optional[str], str]:
    """
    Определяет правило повторения из строки времени и возвращает (repeat_rule, clean_time_str).
    Если правило повторения не найдено, возвращает (None, time_str).

    Поддерживаемые форматы:
    - 'каждый день [в HH:MM]', 'ежедневно [в HH:MM]' -> 'daily'
    - 'по будням [в HH:MM]', 'каждый будний день [в HH:MM]', 'по рабочим дням [в HH:MM]' -> 'weekdays'
    - 'каждую неделю [в HH:MM]', 'еженедельно [в HH:MM]', 'раз в неделю [в HH:MM]' -> 'weekly'
    - 'каждые N часов / часа / час / ч', 'каждый час' -> 'every_N_hours'
    """
    if not time_str or not isinstance(time_str, str):
        return None, ""

    raw = time_str.strip().lower().rstrip(".,!?;:")

    # 1. 'каждые N часов / часа / час / ч' или 'каждый час'
    every_h_match = re.match(
        r"^каждые\s+(\d+)\s*(?:часов|часа|час|ч)$",
        raw,
        re.IGNORECASE
    )
    if every_h_match:
        val = int(every_h_match.group(1))
        return f"every_{val}_hours", f"через {val} ч"

    if re.match(r"^каждый\s+час$", raw, re.IGNORECASE):
        return "every_1_hours", "через 1 час"

    # 2. 'по будням', 'каждый будний день', 'по рабочим дням' [в HH:MM]
    weekdays_match = re.match(
        r"^(?:по\s+будням|каждый\s+будний\s+день|по\s+рабочим\s+дням)(?:\s+(?:в\s+)?(\d{1,2}:\d{2}))?$",
        raw,
        re.IGNORECASE
    )
    if weekdays_match:
        sub_time = weekdays_match.group(1) or "09:00"
        return "weekdays", sub_time

    # 3. 'каждый день', 'ежедневно' [в HH:MM]
    daily_match = re.match(
        r"^(?:каждый\s+день|ежедневно)(?:\s+(?:в\s+)?(\d{1,2}:\d{2}))?$",
        raw,
        re.IGNORECASE
    )
    if daily_match:
        sub_time = daily_match.group(1) or "09:00"
        return "daily", sub_time

    # 4. 'каждую неделю', 'еженедельно', 'раз в неделю' [в HH:MM]
    weekly_match = re.match(
        r"^(?:каждую\s+неделю|еженедельно|раз\s+в\s+неделю)(?:\s+(?:в\s+)?(\d{1,2}:\d{2}))?$",
        raw,
        re.IGNORECASE
    )
    if weekly_match:
        sub_time = weekly_match.group(1) or "10:00"
        return "weekly", sub_time

    return None, time_str.strip()


def compute_next_reminder_time(
    current_time_str: str,
    repeat: str,
    reference_dt: Optional[datetime] = None
) -> Tuple[str, datetime]:
    """
    Вычисляет следующее стандартизированное время (ISO) и datetime для повторяющегося напоминания.

    Поддерживаемые правила:
    - 'daily': следующий день в то же время суток.
    - 'weekdays': следующий рабочий день (пн-пт, weekday < 5) в то же время.
    - 'weekly': следующая неделя (+7 дней).
    - 'every_N_hours': через N часов.
    """
    now = reference_dt or datetime.now()

    # Пытаемся распарсить current_time_str
    base_dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            base_dt = datetime.strptime(current_time_str.strip(), fmt)
            break
        except Exception:
            pass

    if base_dt is None:
        time_m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", current_time_str.strip())
        if time_m:
            h, m = int(time_m.group(1)), int(time_m.group(2))
            s = int(time_m.group(3)) if time_m.group(3) else 0
            base_dt = datetime(now.year, now.month, now.day, h, m, s)
        else:
            base_dt = now

    norm_repeat = (repeat or "").strip().lower()
    dt = base_dt

    if norm_repeat == "daily":
        dt = dt + timedelta(days=1)
        while dt <= now:
            dt += timedelta(days=1)
    elif norm_repeat == "weekdays":
        dt = dt + timedelta(days=1)
        while dt <= now or dt.weekday() >= 5:  # 5=Sat, 6=Sun
            dt += timedelta(days=1)
    elif norm_repeat == "weekly":
        dt = dt + timedelta(weeks=1)
        while dt <= now:
            dt += timedelta(weeks=1)
    elif norm_repeat.startswith("every_") and "hour" in norm_repeat:
        h_match = re.match(r"^every_(\d+)_hours?$", norm_repeat)
        hours = int(h_match.group(1)) if h_match else 1
        dt = dt + timedelta(hours=hours)
        while dt <= now:
            dt += timedelta(hours=hours)
    else:
        dt = dt + timedelta(days=1)
        while dt <= now:
            dt += timedelta(days=1)

    formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
    return formatted, dt


def format_repeat_rule(repeat: Optional[str]) -> str:
    """Возвращает читаемое русскоязычное описание правила повторения."""
    if not repeat:
        return ""
    norm = str(repeat).strip().lower()
    if norm == "daily":
        return "каждый день"
    if norm == "weekdays":
        return "по будням"
    if norm == "weekly":
        return "каждую неделю"
    h_m = re.match(r"^every_(\d+)_hours?$", norm)
    if h_m:
        val = int(h_m.group(1))
        if val == 1:
            return "каждый час"
        if 2 <= val <= 4:
            return f"каждые {val} часа"
        return f"каждые {val} часов"
    return norm


def parse_reminder_time(
    time_str: str,
    reference_now: Optional[datetime] = None
) -> Tuple[bool, str, Optional[datetime]]:
    """
    Разбирает строку времени напоминания в стандартизированный ISO-формат.
    Поддерживает:
    - '2026-09-20 19:00[:00]'
    - '19:00' (сегодня или завтра, если время уже прошло)
    - 'завтра в 10:00'
    - 'через N минут / часов / дней'
    - повторяющиеся выражения: 'каждый день в 10:00', 'по будням в 9:30', 'каждые 2 часа'
    """
    if not time_str or not isinstance(time_str, str):
        return False, "Время напоминания не может быть пустым.", None

    now = reference_now or datetime.now()
    raw = time_str.strip().lower()

    # 0. Проверка правил повторения ('каждый день в 10:00', 'по будням в 9:30', 'каждые 2 часа')
    rep_rule, sub_time = parse_repeat_rule(raw)
    if rep_rule:
        ok, formatted, dt = parse_reminder_time(sub_time, reference_now=now)
        if ok and dt:
            if rep_rule == "weekdays":
                # Если целевое время попало на выходной день, сдвигаем на ближайший понедельник
                while dt.weekday() >= 5 or dt <= now:
                    dt += timedelta(days=1)
                formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
            return True, formatted, dt

    # 1. Формат 'через N минут / часов / дней'
    rel_match = re.match(
        r"^через\s+(\d+)\s*(минут[уыа]?|мин|часов|часа|час|ч|дней|дня|день|д)$",
        raw,
        re.IGNORECASE
    )
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if unit.startswith("мин") or unit == "м":
            target_dt = now + timedelta(minutes=val)
        elif unit.startswith("час") or unit == "ч":
            target_dt = now + timedelta(hours=val)
        elif unit.startswith("д"):
            target_dt = now + timedelta(days=val)
        else:
            target_dt = now + timedelta(minutes=val)
        formatted = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        return True, formatted, target_dt

    # 2. Формат 'завтра [в] HH:MM'
    tomorrow_match = re.match(
        r"^завтра(?:\s+в)?\s+(\d{1,2}):(\d{2})$",
        raw,
        re.IGNORECASE
    )
    if tomorrow_match:
        h, m = int(tomorrow_match.group(1)), int(tomorrow_match.group(2))
        tomorrow = now + timedelta(days=1)
        target_dt = datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, 0)
        formatted = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        return True, formatted, target_dt

    # 3. Формат 'HH:MM'
    time_only_match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if time_only_match:
        h, m = int(time_only_match.group(1)), int(time_only_match.group(2))
        target_dt = datetime(now.year, now.month, now.day, h, m, 0)
        # Если время уже прошло сегодня, переносим на завтра
        if target_dt <= now:
            target_dt += timedelta(days=1)
        formatted = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        return True, formatted, target_dt

    # 4. Полный ISO-формат 'YYYY-MM-DD [HH:MM[:SS]]'
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            target_dt = datetime.strptime(time_str.strip(), fmt)
            formatted = target_dt.strftime("%Y-%m-%d %H:%M:%S")
            return True, formatted, target_dt
        except ValueError:
            pass

    # Fallback: сохраняем как текст, если распарсить не удалось
    return True, time_str.strip(), None
