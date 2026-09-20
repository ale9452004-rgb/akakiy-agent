"""
Тестовый набор для модуля tools/datetime_utils.py (Task R4).
Проверяет разбор времени напоминаний parse_reminder_time во всех поддерживаемых форматах.
"""

from datetime import datetime
import os
import sys
import unittest

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.datetime_utils import parse_reminder_time
from tools.household import parse_reminder_time as household_parse_reminder_time


class TestDateTimeUtils(unittest.TestCase):
    """Тестирование функции parse_reminder_time."""

    def setUp(self):
        # Фиксированное контрольное время: 2026-09-21 12:00:00 (понедельник)
        self.ref = datetime(2026, 9, 21, 12, 0, 0)

    def test_reexport_backward_compatibility(self):
        """Проверка обратной совместимости импорта из tools.household."""
        self.assertIs(household_parse_reminder_time, parse_reminder_time)

    def test_empty_or_invalid_type(self):
        """Пустые или некорректные типы аргумента."""
        ok, msg, dt = parse_reminder_time("", reference_now=self.ref)
        self.assertFalse(ok)
        self.assertIn("не может быть пустым", msg)
        self.assertIsNone(dt)

        ok, msg, dt = parse_reminder_time(None, reference_now=self.ref)
        self.assertFalse(ok)
        self.assertIn("не может быть пустым", msg)
        self.assertIsNone(dt)

    def test_relative_minutes(self):
        """Относительное время в минутах."""
        ok, formatted, dt = parse_reminder_time("через 15 минут", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-21 12:15:00")
        self.assertEqual(dt, datetime(2026, 9, 21, 12, 15, 0))

        ok, formatted, dt = parse_reminder_time("через 5 мин", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-21 12:05:00")

    def test_relative_hours(self):
        """Относительное время в часах."""
        ok, formatted, dt = parse_reminder_time("через 2 часа", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-21 14:00:00")
        self.assertEqual(dt, datetime(2026, 9, 21, 14, 0, 0))

        ok, formatted, dt = parse_reminder_time("через 1 час", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-21 13:00:00")

    def test_relative_days(self):
        """Относительное время в днях."""
        ok, formatted, dt = parse_reminder_time("через 3 дня", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-24 12:00:00")
        self.assertEqual(dt, datetime(2026, 9, 24, 12, 0, 0))

        ok, formatted, dt = parse_reminder_time("через 1 день", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-22 12:00:00")

    def test_tomorrow_format(self):
        """Формат 'завтра [в] HH:MM'."""
        ok, formatted, dt = parse_reminder_time("завтра в 10:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-22 10:00:00")
        self.assertEqual(dt, datetime(2026, 9, 22, 10, 0, 0))

        ok, formatted, dt = parse_reminder_time("завтра 18:30", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-22 18:30:00")

    def test_time_only_format(self):
        """Формат 'HH:MM': сегодня (если время ещё не наступило) или завтра (если уже прошло)."""
        # Время ещё не наступило сегодня (15:00 > 12:00) -> сегодня
        ok, formatted, dt = parse_reminder_time("15:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-21 15:00:00")
        self.assertEqual(dt, datetime(2026, 9, 21, 15, 0, 0))

        # Время уже наступило/прошло сегодня (09:00 < 12:00) -> перенос на завтра
        ok, formatted, dt = parse_reminder_time("09:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-22 09:00:00")
        self.assertEqual(dt, datetime(2026, 9, 22, 9, 0, 0))

        # Время совпадает с текущим -> перенос на завтра
        ok, formatted, dt = parse_reminder_time("12:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-09-22 12:00:00")

    def test_iso_formats(self):
        """Полный ISO-формат даты и времени."""
        ok, formatted, dt = parse_reminder_time("2026-10-15 16:45:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-10-15 16:45:00")
        self.assertEqual(dt, datetime(2026, 10, 15, 16, 45, 0))

        ok, formatted, dt = parse_reminder_time("2026-10-15 16:45", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-10-15 16:45:00")

        ok, formatted, dt = parse_reminder_time("2026-10-15T16:45:00", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "2026-10-15 16:45:00")

    def test_fallback_unrecognized_text(self):
        """Нераспознанный текст сохраняется как fallback."""
        ok, formatted, dt = parse_reminder_time("когда-нибудь потом", reference_now=self.ref)
        self.assertTrue(ok)
        self.assertEqual(formatted, "когда-нибудь потом")
        self.assertIsNone(dt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
