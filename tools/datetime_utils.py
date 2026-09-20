"""
Модуль утилит работы со временем и датами для ассистента Акакия.

Содержит чистые функции разбора пользовательских строк времени (напоминаний, событий)
в стандартизированный ISO-формат.
"""

from datetime import datetime, timedelta
import re
from typing import Optional, Tuple


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
    """
    if not time_str or not isinstance(time_str, str):
        return False, "Время напоминания не может быть пустым.", None

    now = reference_now or datetime.now()
    raw = time_str.strip().lower()

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
