"""
Тестовый набор для повторяющихся напоминаний и задач (Recurring Reminders & Tasks).

Проверяет:
1. Разбор правил повторения и расчет дат (datetime_utils):
   - каждый день (daily)
   - по будням (weekdays)
   - каждую неделю (weekly)
   - каждые N часов (every_N_hours)
   - пропуск выходных дней для рабочих будней
   - компенсация пропущенных интервалов (если компьютер был выключен)
2. Жизненный цикл в HouseholdManager:
   - обратная совместимость со старыми записями (repeat=None)
   - создание через текст ("каждый день в 10:00", "по будням в 9:30", "каждые 2 часа")
   - создание через явный аргумент repeat
   - срабатывание в check_due_reminders (расчёт следующего времени вместо triggered=True)
   - ручное выполнение complete_reminder (досрочное и после срабатывания)
   - удаление delete_reminder
3. Интеграция с ReminderMonitor (дедупликация и повторные срабатывания).
4. Совместимость с экспортом/импортом (backup).
5. Маршрутизация в CommandRouter.
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.datetime_utils import (
    parse_repeat_rule,
    compute_next_reminder_time,
    format_repeat_rule,
    parse_reminder_time
)
from tools.household import HouseholdManager
from notifications.monitor import ReminderMonitor
from tools.backup import export_data, import_data, validate_backup
from tools.router import CommandRouter


class TestRecurrenceParsingAndCalculation(unittest.TestCase):
    """Тестирование чистых функций разбора и расчёта повторений."""

    def test_parse_repeat_rule_daily(self):
        rule, sub = parse_repeat_rule("каждый день в 10:00")
        self.assertEqual(rule, "daily")
        self.assertEqual(sub, "10:00")

        rule, sub = parse_repeat_rule("ежедневно в 14:30")
        self.assertEqual(rule, "daily")
        self.assertEqual(sub, "14:30")

        rule, sub = parse_repeat_rule("каждый день")
        self.assertEqual(rule, "daily")
        self.assertEqual(sub, "09:00")

    def test_parse_repeat_rule_weekdays(self):
        rule, sub = parse_repeat_rule("по будням в 9:30")
        self.assertEqual(rule, "weekdays")
        self.assertEqual(sub, "9:30")

        rule, sub = parse_repeat_rule("каждый будний день в 11:00")
        self.assertEqual(rule, "weekdays")
        self.assertEqual(sub, "11:00")

        rule, sub = parse_repeat_rule("по рабочим дням в 18:00")
        self.assertEqual(rule, "weekdays")
        self.assertEqual(sub, "18:00")

        rule, sub = parse_repeat_rule("по будням")
        self.assertEqual(rule, "weekdays")
        self.assertEqual(sub, "09:00")

    def test_parse_repeat_rule_weekly(self):
        rule, sub = parse_repeat_rule("каждую неделю в 12:00")
        self.assertEqual(rule, "weekly")
        self.assertEqual(sub, "12:00")

        rule, sub = parse_repeat_rule("раз в неделю в 15:00")
        self.assertEqual(rule, "weekly")
        self.assertEqual(sub, "15:00")

        rule, sub = parse_repeat_rule("еженедельно в 10:00")
        self.assertEqual(rule, "weekly")
        self.assertEqual(sub, "10:00")

    def test_parse_repeat_rule_interval_hours(self):
        rule, sub = parse_repeat_rule("каждые 2 часа")
        self.assertEqual(rule, "every_2_hours")
        self.assertEqual(sub, "через 2 ч")

        rule, sub = parse_repeat_rule("каждые 4 часов")
        self.assertEqual(rule, "every_4_hours")
        self.assertEqual(sub, "через 4 ч")

        rule, sub = parse_repeat_rule("каждый час")
        self.assertEqual(rule, "every_1_hours")
        self.assertEqual(sub, "через 1 час")

    def test_parse_repeat_rule_one_time_fallback(self):
        rule, sub = parse_repeat_rule("завтра в 10:00")
        self.assertIsNone(rule)
        self.assertEqual(sub, "завтра в 10:00")

        rule, sub = parse_repeat_rule("через 15 минут")
        self.assertIsNone(rule)
        self.assertEqual(sub, "через 15 минут")

    def test_format_repeat_rule(self):
        self.assertEqual(format_repeat_rule("daily"), "каждый день")
        self.assertEqual(format_repeat_rule("weekdays"), "по будням")
        self.assertEqual(format_repeat_rule("weekly"), "каждую неделю")
        self.assertEqual(format_repeat_rule("every_1_hours"), "каждый час")
        self.assertEqual(format_repeat_rule("every_2_hours"), "каждые 2 часа")
        self.assertEqual(format_repeat_rule("every_5_hours"), "каждые 5 часов")
        self.assertEqual(format_repeat_rule(None), "")

    def test_compute_next_daily(self):
        # Понедельник 10:00, текущее время 10:00
        ref_now = datetime(2026, 9, 21, 10, 0, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-21 10:00:00", "daily", reference_dt=ref_now)
        self.assertEqual(next_str, "2026-09-22 10:00:00")
        self.assertEqual(next_dt, datetime(2026, 9, 22, 10, 0, 0))

    def test_compute_next_weekdays_from_friday(self):
        # Пятница 2026-09-25 09:30
        ref_now = datetime(2026, 9, 25, 9, 30, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-25 09:30:00", "weekdays", reference_dt=ref_now)
        # Следующий рабочий день — понедельник 2026-09-28
        self.assertEqual(next_str, "2026-09-28 09:30:00")
        self.assertEqual(next_dt.weekday(), 0)  # Monday

    def test_compute_next_weekdays_from_monday(self):
        # Понедельник 2026-09-21 09:30
        ref_now = datetime(2026, 9, 21, 9, 30, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-21 09:30:00", "weekdays", reference_dt=ref_now)
        # Следующий рабочий день — вторник 2026-09-22
        self.assertEqual(next_str, "2026-09-22 09:30:00")
        self.assertEqual(next_dt.weekday(), 1)  # Tuesday

    def test_compute_next_weekly(self):
        ref_now = datetime(2026, 9, 21, 12, 0, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-21 12:00:00", "weekly", reference_dt=ref_now)
        self.assertEqual(next_str, "2026-09-28 12:00:00")

    def test_compute_next_every_n_hours(self):
        ref_now = datetime(2026, 9, 21, 10, 0, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-21 10:00:00", "every_2_hours", reference_dt=ref_now)
        self.assertEqual(next_str, "2026-09-21 12:00:00")

    def test_compute_next_with_missed_interval(self):
        # Напоминание было на 2026-09-18 10:00, но компьютер включили 2026-09-21 14:00 (прошло 3 дня)
        ref_now = datetime(2026, 9, 21, 14, 0, 0)
        next_str, next_dt = compute_next_reminder_time("2026-09-18 10:00:00", "daily", reference_dt=ref_now)
        # Должно рассчитать следующий день после ref_now в 10:00
        self.assertEqual(next_str, "2026-09-22 10:00:00")
        self.assertGreater(next_dt, ref_now)


class TestHouseholdManagerRecurrence(unittest.TestCase):
    """Тестирование повторяющихся напоминаний в HouseholdManager."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_household.json"
        self.household = HouseholdManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backward_compatibility_old_records(self):
        # Создаём структуру household.json без поля 'repeat' (формат до внедрения)
        old_data = {
            "version": 1,
            "tasks": [],
            "reminders": [
                {
                    "id": 1,
                    "text": "Старое одноразовое напоминание",
                    "remind_at": "2026-09-20 10:00:00",
                    "created_at": "2026-09-19 10:00:00",
                    "triggered": False
                }
            ],
            "notes": [],
            "lists": {},
            "counters": {"task": 0, "reminder": 1, "note": 0}
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        # Перезагружаем менеджер
        self.household.reload()
        rem = self.household.reminders[0]
        self.assertIsNone(rem.get("repeat"))

        # Проверяем, что оно работает как обычное одноразовое
        due_res = self.household.check_due_reminders(current_time="2026-09-21 10:00:00")
        self.assertEqual(due_res["due_count"], 1)
        self.assertTrue(self.household.reminders[0]["triggered"])

    def test_create_recurring_reminder_natural_language(self):
        # 1. Каждый день
        res1 = self.household.create_reminder("Принять витамины", "каждый день в 10:00")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["reminder"]["repeat"], "daily")
        self.assertIn("10:00:00", res1["reminder"]["remind_at"])
        self.assertIn("каждый день", res1["message"])

        # 2. По будням
        res2 = self.household.create_reminder("Подключиться к дейли", "по будням в 9:30")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["reminder"]["repeat"], "weekdays")
        self.assertIn("09:30:00", res2["reminder"]["remind_at"])

        # 3. Каждые 2 часа
        res3 = self.household.create_reminder("Пить воду", "каждые 2 часа")
        self.assertTrue(res3["success"])
        self.assertEqual(res3["reminder"]["repeat"], "every_2_hours")

    def test_create_recurring_reminder_explicit_repeat(self):
        res = self.household.create_reminder("Синхронизация", "15:00", repeat="weekly")
        self.assertTrue(res["success"])
        self.assertEqual(res["reminder"]["repeat"], "weekly")
        self.assertIn("каждую неделю", res["message"])

    def test_check_due_recurring_reminder_advances_time(self):
        # Устанавливаем напоминание на прошедшее время
        past_time = "2026-09-21 10:00:00"
        res = self.household.create_reminder("Разминка", past_time, repeat="daily")
        rem_id = res["reminder"]["id"]

        # Первая проверка наступивших в 10:05
        due_res = self.household.check_due_reminders(current_time="2026-09-21 10:05:00")
        self.assertEqual(due_res["due_count"], 1)
        due_rem = due_res["reminders"][0]
        self.assertEqual(due_rem["id"], rem_id)

        # Проверяем, что напоминание в хранилище НЕ завершено навсегда (triggered=False),
        # а перенесено на следующий день в 10:00
        stored_rem = next(r for r in self.household.reminders if r["id"] == rem_id)
        self.assertFalse(stored_rem["triggered"])
        self.assertEqual(stored_rem["remind_at"], "2026-09-22 10:00:00")

        # Вторая проверка сразу же в 10:06 не должна считать его наступившим
        due_res_2 = self.household.check_due_reminders(current_time="2026-09-21 10:06:00")
        self.assertEqual(due_res_2["due_count"], 0)

    def test_complete_reminder_recurring_vs_one_time(self):
        # 1. Одноразовое напоминание: complete_reminder удаляет его из списка
        res_once = self.household.create_reminder("Одноразовое дело", "2026-09-21 11:00:00")
        id_once = res_once["reminder"]["id"]

        comp_once = self.household.complete_reminder(id_once)
        self.assertTrue(comp_once["success"])
        self.assertFalse(comp_once["rescheduled"])
        self.assertNotIn(id_once, [r["id"] for r in self.household.reminders])

        # 2. Повторяющееся напоминание: complete_reminder переносит на следующий интервал
        res_rep = self.household.create_reminder("Повторяющееся дело", "2026-09-21 11:00:00", repeat="daily")
        id_rep = res_rep["reminder"]["id"]

        comp_rep = self.household.complete_reminder(id_rep)
        self.assertTrue(comp_rep["success"])
        self.assertTrue(comp_rep["rescheduled"])
        # Напоминание осталось в списке
        self.assertIn(id_rep, [r["id"] for r in self.household.reminders])
        stored_rep = next(r for r in self.household.reminders if r["id"] == id_rep)
        self.assertIn("11:00:00", stored_rep["remind_at"])
        self.assertFalse(stored_rep["triggered"])

    def test_delete_reminder_removes_recurring(self):
        # Пользователь имеет возможность удалить повторяющееся напоминание целиком
        res = self.household.create_reminder("Удаляемое регулярное", "10:00", repeat="daily")
        rem_id = res["reminder"]["id"]

        del_res = self.household.delete_reminder(rem_id)
        self.assertTrue(del_res["success"])
        self.assertEqual(len(self.household.reminders), 0)

    def test_list_reminders_shows_repeat_badge(self):
        self.household.create_reminder("Таблетки", "10:00", repeat="daily")
        self.household.create_reminder("Встреча", "12:00")

        list_res = self.household.list_reminders()
        msg = list_res["message"]
        self.assertIn("[повтор: каждый день]", msg)
        self.assertIn("Таблетки", msg)
        self.assertIn("Встреча", msg)


class TestReminderMonitorRecurring(unittest.TestCase):
    """Тестирование ReminderMonitor с повторяющимися напоминаниями."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_household_monitor.json"
        self.household = HouseholdManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_monitor_triggers_and_allows_subsequent_occurrence(self):
        callback = MagicMock()
        monitor = ReminderMonitor(
            household=self.household,
            on_reminder=callback,
            interval_sec=5.0
        )

        # Создаем повторяющееся напоминание на 10:00
        self.household.create_reminder("Вода", "2026-09-21 10:00:00", repeat="every_2_hours")

        # 1. Первый запуск в 10:01 — срабатывает
        due1 = monitor.check_now(current_time="2026-09-21 10:01:00")
        self.assertEqual(len(due1), 1)
        self.assertEqual(callback.call_count, 1)

        # 2. Повторная проверка через 10 секунд — дедуплицируется (не вызывается снова)
        due_repeat_check = monitor.check_now(current_time="2026-09-21 10:01:10")
        self.assertEqual(len(due_repeat_check), 0)
        self.assertEqual(callback.call_count, 1)

        # 3. Наступило время следующего интервала (12:01) — напоминание наступает снова
        due2 = monitor.check_now(current_time="2026-09-21 12:01:00")
        self.assertEqual(len(due2), 1)
        self.assertEqual(callback.call_count, 2)


class TestBackupAndRouterRecurrence(unittest.TestCase):
    """Тестирование взаимодействия повторяющихся напоминаний с бэкапом и роутером."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_household_backup.json"
        self.household = HouseholdManager(storage_path=self.storage_path)
        self.router = CommandRouter()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_preserves_recurrence(self):
        self.household.create_reminder("Ежедневный отчет", "18:00", repeat="daily")
        self.household.create_reminder("Дейли по будням", "09:30", repeat="weekdays")

        backup_file = Path(self.temp_dir.name) / "backup.json"
        exp_res = export_data(output_path=backup_file, household=self.household)
        self.assertTrue(exp_res["success"])

        val_ok, val_msg, parsed = validate_backup(backup_file)
        self.assertTrue(val_ok)

        # Создаем новый чистый household и восстанавливаем
        new_storage = Path(self.temp_dir.name) / "new_household.json"
        new_household = HouseholdManager(storage_path=new_storage)
        imp_res = import_data(backup_file, household=new_household)
        self.assertTrue(imp_res["success"])

        # Проверяем, что правила повторения сохранились
        rems = new_household.reminders
        self.assertEqual(len(rems), 2)
        r_daily = next(r for r in rems if r["text"] == "Ежедневный отчет")
        r_weekdays = next(r for r in rems if r["text"] == "Дейли по будням")
        self.assertEqual(r_daily.get("repeat"), "daily")
        self.assertEqual(r_weekdays.get("repeat"), "weekdays")

    def test_router_recurring_reminder(self):
        # 1. 'каждый день в 10:00'
        m1 = self.router.choose_tool("напомни разминка каждый день в 10:00")
        self.assertEqual(m1["tool"], "create_reminder")
        self.assertEqual(m1["arguments"]["text"], "разминка")
        self.assertEqual(m1["arguments"]["remind_at"], "каждый день в 10:00")

        # 2. 'по будням в 9:30'
        m2 = self.router.choose_tool("напомни дейли по будням в 9:30")
        self.assertEqual(m2["tool"], "create_reminder")
        self.assertEqual(m2["arguments"]["text"], "дейли")
        self.assertEqual(m2["arguments"]["remind_at"], "по будням в 9:30")

        # 3. 'каждые 2 часа'
        m3 = self.router.choose_tool("напомни пить воду каждые 2 часа")
        self.assertEqual(m3["tool"], "create_reminder")
        self.assertEqual(m3["arguments"]["text"], "пить воду")
        self.assertEqual(m3["arguments"]["remind_at"], "каждые 2 часа")

        # 4. 'выполни напоминание 1'
        m4 = self.router.choose_tool("выполни напоминание 1")
        self.assertEqual(m4["tool"], "complete_reminder")
        self.assertEqual(m4["arguments"]["reminder_id"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
