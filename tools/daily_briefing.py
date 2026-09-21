"""
Модуль дневного брифинга Акакия (Daily Briefing).

Обеспечивает агрегацию актуальной сводки дня:
- активные незавершённые задачи (с выделением просроченных);
- напоминания, запланированные на сегодня;
- повторяющиеся напоминания, относящиеся к сегодняшнему дню (daily, weekdays, weekly, interval hours);
- активные списки с количеством незавершённых пунктов.

Модуль является строго read-only и не изменяет состояние хранилища.
"""

from datetime import date, datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.household import HouseholdManager, get_household_manager

logger = logging.getLogger(__name__)


def pluralize_ru(n: int, forms: Tuple[str, str, str]) -> str:
    """
    Склонение русских слов в зависимости от числительного.
    forms: ('задача', 'задачи', 'задач')
    """
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        return forms[0]
    elif 2 <= n_abs % 10 <= 4 and (n_abs % 100 < 10 or n_abs % 100 >= 20):
        return forms[1]
    else:
        return forms[2]


def is_task_overdue(task: Dict[str, Any], reference_date_str: str) -> bool:
    """
    Проверяет, является ли незавершённая задача просроченной относительно целевой даты (YYYY-MM-DD).
    Учитывает поля due_date, deadline, due_at.
    """
    if task.get("completed"):
        return False

    due = task.get("due_date") or task.get("deadline") or task.get("due_at")
    if not due or not isinstance(due, str):
        return False

    due_clean = due.strip()
    # Если указана дата YYYY-MM-DD[...]
    if len(due_clean) >= 10 and due_clean[:10] < reference_date_str:
        return True

    return False


def does_recurring_apply_to_date(reminder: Dict[str, Any], target_date: date) -> bool:
    """
    Определяет, относится ли повторяющееся напоминание к указанной дате.
    - daily: каждый день -> всегда относится;
    - weekdays: по будням -> только пн-пт (weekday < 5);
    - weekly: каждую неделю -> совпадение дня недели со временем напоминания;
    - every_N_hours: интервальное -> относится к любому дню;
    - или если remind_at явно попадает на target_date.
    """
    repeat = reminder.get("repeat")
    if not repeat:
        return False

    norm_rep = str(repeat).strip().lower()

    # 1. Ежедневно
    if norm_rep == "daily":
        return True

    # 2. По будням (пн-пт, weekday 0..4)
    if norm_rep == "weekdays":
        return target_date.weekday() < 5

    # 3. Еженедельно
    if norm_rep == "weekly":
        rem_at = reminder.get("remind_at", "")
        # Проверяем день недели исходной установки
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                base_dt = datetime.strptime(rem_at[:19].strip(), fmt)
                return base_dt.weekday() == target_date.weekday()
            except Exception:
                pass
        # Если дату не распарсить, проверяем по created_at
        created = reminder.get("created_at", "")
        try:
            c_dt = datetime.strptime(created[:19].strip(), "%Y-%m-%d %H:%M:%S")
            return c_dt.weekday() == target_date.weekday()
        except Exception:
            pass
        return True

    # 4. Интервальные часы
    if norm_rep.startswith("every_") and "hour" in norm_rep:
        return True

    # 5. Fallback: проверка совпадения даты в remind_at
    target_str = target_date.strftime("%Y-%m-%d")
    return reminder.get("remind_at", "").startswith(target_str)


def get_daily_briefing(
    household: Optional[HouseholdManager] = None,
    target_date: Optional[Union[date, datetime, str]] = None
) -> Dict[str, Any]:
    """
    Формирует структурированную сводку дня и готовый текст брифинга.

    Параметры:
        household: Экземпляр HouseholdManager (по умолчанию синглтон).
        target_date: Целевая дата (date, datetime или 'YYYY-MM-DD'). По умолчанию сегодня.

    Возвращает:
        Словарь с разделами:
        - success: bool
        - date: str ('YYYY-MM-DD')
        - is_empty: bool
        - tasks: dict (pending_count, overdue_count, items)
        - reminders: dict (total_count, single_count, recurring_count, single_items, recurring_items)
        - lists: dict (active_lists_count, items)
        - text: str (готовый детерминированный текст брифинга)
    """
    mgr = household or get_household_manager()

    # 1. Нормализация даты
    if target_date is None:
        ref_date = datetime.now().date()
    elif isinstance(target_date, datetime):
        ref_date = target_date.date()
    elif isinstance(target_date, date):
        ref_date = target_date
    elif isinstance(target_date, str):
        try:
            ref_date = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except Exception:
            ref_date = datetime.now().date()
    else:
        ref_date = datetime.now().date()

    ref_date_str = ref_date.strftime("%Y-%m-%d")

    # 2. Анализ задач (Tasks)
    all_tasks = list(getattr(mgr, "tasks", []))
    pending_tasks = [t for t in all_tasks if not t.get("completed")]
    total_pending_tasks = len(pending_tasks)

    overdue_tasks = [t for t in pending_tasks if is_task_overdue(t, ref_date_str)]
    overdue_count = len(overdue_tasks)

    # 3. Анализ напоминаний (Reminders)
    all_reminders = list(getattr(mgr, "reminders", []))

    # Одноразовые напоминания на сегодня
    single_reminders = [
        r for r in all_reminders
        if not r.get("repeat")
        and not r.get("triggered")
        and r.get("remind_at", "").startswith(ref_date_str)
    ]

    # Повторяющиеся напоминания, относящиеся к сегодняшнему дню
    recurring_reminders = [
        r for r in all_reminders
        if r.get("repeat")
        and does_recurring_apply_to_date(r, ref_date)
    ]

    # 4. Анализ списков (Lists)
    lists_data = dict(getattr(mgr, "lists", {}))
    active_lists: List[Dict[str, Any]] = []

    for name, items in lists_data.items():
        if not isinstance(items, list):
            continue
        p_items = [it for it in items if not it.get("completed")]
        if p_items:
            display_name = name.capitalize() if isinstance(name, str) else str(name)
            active_lists.append({
                "name": display_name,
                "raw_name": name,
                "pending_count": len(p_items),
                "total_count": len(items)
            })

    # Сортируем списки по алфавиту для детерминированности
    active_lists.sort(key=lambda x: str(x["name"]).lower())

    # 5. Проверка на пустой день
    is_empty = (
        total_pending_tasks == 0
        and len(single_reminders) == 0
        and len(recurring_reminders) == 0
        and len(active_lists) == 0
    )

    # 6. Формирование читаемого детерминированного текста
    lines: List[str] = []

    if is_empty:
        text = "На сегодня ничего не запланировано: нет активных задач, напоминаний и списков дел."
    else:
        lines.append("На сегодня:")

        # Блок задач
        if total_pending_tasks > 0:
            task_word = pluralize_ru(total_pending_tasks, ("задача", "задачи", "задач"))
            if overdue_count > 0:
                overdue_word = "просрочена" if (overdue_count % 10 == 1 and overdue_count % 100 != 11) else ("просрочено" if overdue_count >= 5 else "просрочены")
                lines.append(f"• {total_pending_tasks} {task_word}, из них {overdue_count} {overdue_word}.")
            else:
                lines.append(f"• {total_pending_tasks} {task_word}.")

        # Блок одноразовых напоминаний
        single_cnt = len(single_reminders)
        if single_cnt > 0:
            rem_word = pluralize_ru(single_cnt, ("напоминание", "напоминания", "напоминаний"))
            lines.append(f"• {single_cnt} {rem_word}.")

        # Блок повторяющихся напоминаний
        rec_cnt = len(recurring_reminders)
        if rec_cnt > 0:
            rec_word = pluralize_ru(rec_cnt, ("повторяющееся напоминание", "повторяющихся напоминания", "повторяющихся напоминаний"))
            lines.append(f"• {rec_cnt} {rec_word}.")

        # Блок списков
        for al in active_lists:
            p_cnt = al["pending_count"]
            item_word = pluralize_ru(p_cnt, ("пункт", "пункта", "пунктов"))
            verb = "остался" if (p_cnt % 10 == 1 and p_cnt % 100 != 11) else "осталось"
            lines.append(f"• В списке \"{al['name']}\" {verb} {p_cnt} {item_word}.")

        text = "\n".join(lines)

    return {
        "success": True,
        "date": ref_date_str,
        "is_empty": is_empty,
        "tasks": {
            "pending_count": total_pending_tasks,
            "overdue_count": overdue_count,
            "items": pending_tasks
        },
        "reminders": {
            "total_count": len(single_reminders) + len(recurring_reminders),
            "single_count": len(single_reminders),
            "recurring_count": len(recurring_reminders),
            "single_items": single_reminders,
            "recurring_items": recurring_reminders
        },
        "lists": {
            "active_lists_count": len(active_lists),
            "items": active_lists
        },
        "text": text
    }


def daily_briefing() -> Dict[str, Any]:
    """Функция-обёртка инструмента для tools.registry."""
    res = get_daily_briefing()
    return {
        "success": True,
        "message": res["text"],
        "briefing": res
    }
