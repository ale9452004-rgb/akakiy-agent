"""
Тесты для модуля дневного брифинга Акакия (Daily Briefing).

Проверяет:
1. Пустой день (is_empty=True, детерминированный текст);
2. Активные задачи без просрочки;
3. Просроченные задачи (с различными окончаниями числительных);
4. Одноразовые напоминания на сегодня (игнорирование будущих и сработавших);
5. Повторяющиеся напоминания (daily, weekdays, weekly, interval);
6. Активные списки дел с подсчетом незавершенных пунктов;
7. Полный комплексный брифинг (точное соответствие эталонному формату ТЗ);
8. Маршрутизация естественных запросов в CommandRouter;
9. Быстрые CLI-команды (:brief, :today, :сводка) в handle_cli_command;
10. Регистрация инструмента daily_briefing в tools.registry;
11. Безопасный вызов ui_show_daily_briefing в HomeView.
"""

from datetime import date, datetime
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from commands import handle_cli_command
from tools.daily_briefing import (
    daily_briefing,
    does_recurring_apply_to_date,
    get_daily_briefing,
    is_task_overdue,
    pluralize_ru,
)
from tools.household import HouseholdManager
from tools.registry import get_tool, get_tools_schema
from tools.router import CommandRouter, get_router


class TestDailyBriefingCore(unittest.TestCase):
    """Тесты базовой логики и хелперов daily_briefing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_household.json"
        self.mgr = HouseholdManager(storage_path=self.storage_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pluralize_ru(self):
        forms = ("задача", "задачи", "задач")
        self.assertEqual(pluralize_ru(1, forms), "задача")
        self.assertEqual(pluralize_ru(2, forms), "задачи")
        self.assertEqual(pluralize_ru(4, forms), "задачи")
        self.assertEqual(pluralize_ru(5, forms), "задач")
        self.assertEqual(pluralize_ru(11, forms), "задач")
        self.assertEqual(pluralize_ru(21, forms), "задача")
        self.assertEqual(pluralize_ru(22, forms), "задачи")

    def test_empty_day_briefing(self):
        """Проверка сводки на пустой день."""
        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertTrue(res["success"])
        self.assertTrue(res["is_empty"])
        self.assertEqual(res["tasks"]["pending_count"], 0)
        self.assertEqual(res["reminders"]["total_count"], 0)
        self.assertEqual(res["lists"]["active_lists_count"], 0)
        self.assertEqual(
            res["text"],
            "На сегодня ничего не запланировано: нет активных задач, напоминаний и списков дел."
        )

    def test_pending_tasks_without_overdue(self):
        """Проверка активных задач без просрочки."""
        self.mgr.create_task("Купить хлеб", due_date="2026-09-25")
        self.mgr.create_task("Позвонить врачу", due_date="2026-09-21")
        self.mgr.create_task("Выполненная задача")
        self.mgr.complete_task(3)

        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertFalse(res["is_empty"])
        self.assertEqual(res["tasks"]["pending_count"], 2)
        self.assertEqual(res["tasks"]["overdue_count"], 0)
        self.assertIn("• 2 задачи.", res["text"])
        self.assertNotIn("просрочена", res["text"])

    def test_overdue_tasks_declensions(self):
        """Проверка различных склонений для просроченных задач."""
        # 1 просрочена из 3
        self.mgr.create_task("Задача 1", due_date="2026-09-19")  # просрочена
        self.mgr.create_task("Задача 2", due_date="2026-09-22")
        self.mgr.create_task("Задача 3")

        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertEqual(res["tasks"]["pending_count"], 3)
        self.assertEqual(res["tasks"]["overdue_count"], 1)
        self.assertIn("• 3 задачи, из них 1 просрочена.", res["text"])

        # 2 просрочены из 4
        self.mgr.create_task("Задача 4", due_date="2026-09-18")  # просрочена
        res2 = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertEqual(res2["tasks"]["pending_count"], 4)
        self.assertEqual(res2["tasks"]["overdue_count"], 2)
        self.assertIn("• 4 задачи, из них 2 просрочены.", res2["text"])

        # 5 просрочено из 6
        self.mgr.create_task("Задача 5", due_date="2026-09-17")
        self.mgr.create_task("Задача 6", due_date="2026-09-16")
        self.mgr.create_task("Задача 7", due_date="2026-09-15")
        res3 = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertEqual(res3["tasks"]["pending_count"], 7)
        self.assertEqual(res3["tasks"]["overdue_count"], 5)
        self.assertIn("• 7 задач, из них 5 просрочено.", res3["text"])

    def test_single_reminders(self):
        """Проверка одноразовых напоминаний на сегодня."""
        self.mgr.create_reminder("Принять витамины", "2026-09-21 09:00:00")
        self.mgr.create_reminder("Совещание", "2026-09-21 14:00:00")
        # Напоминание на завтра - не должно попасть
        self.mgr.create_reminder("Полить цветы", "2026-09-22 10:00:00")
        # Сработавшее напоминание - не должно попасть
        r4 = self.mgr.create_reminder("Старое напоминание", "2026-09-21 08:00:00")
        self.mgr.reminders[3]["triggered"] = True
        self.mgr._save()

        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertEqual(res["reminders"]["single_count"], 2)
        self.assertEqual(res["reminders"]["recurring_count"], 0)
        self.assertIn("• 2 напоминания.", res["text"])

    def test_recurring_reminders_rules(self):
        """Проверка повторяющихся напоминаний (daily, weekdays, weekly, hourly)."""
        target_mon = date(2026, 9, 21)  # Понедельник (weekday=0)
        target_sat = date(2026, 9, 26)  # Суббота (weekday=5)

        # 1. daily
        r_daily = {"repeat": "daily", "text": "Зарядка"}
        self.assertTrue(does_recurring_apply_to_date(r_daily, target_mon))
        self.assertTrue(does_recurring_apply_to_date(r_daily, target_sat))

        # 2. weekdays
        r_weekdays = {"repeat": "weekdays", "text": "Рабочий стендап"}
        self.assertTrue(does_recurring_apply_to_date(r_weekdays, target_mon))
        self.assertFalse(does_recurring_apply_to_date(r_weekdays, target_sat))

        # 3. weekly (по понедельникам)
        r_weekly_mon = {"repeat": "weekly", "remind_at": "2026-09-14 10:00:00", "text": "Еженедельный отчет"}
        self.assertTrue(does_recurring_apply_to_date(r_weekly_mon, target_mon))
        self.assertFalse(does_recurring_apply_to_date(r_weekly_mon, target_sat))

        # 4. every_2_hours
        r_hourly = {"repeat": "every_2_hours", "text": "Выпить воды"}
        self.assertTrue(does_recurring_apply_to_date(r_hourly, target_mon))
        self.assertTrue(does_recurring_apply_to_date(r_hourly, target_sat))

        # Добавим одно повторяющееся в менеджер
        self.mgr.create_reminder("Зарядка", "2026-09-21 08:00:00", repeat="daily")
        res = get_daily_briefing(household=self.mgr, target_date=target_mon)
        self.assertEqual(res["reminders"]["recurring_count"], 1)
        self.assertIn("• 1 повторяющееся напоминание.", res["text"])

    def test_active_lists(self):
        """Проверка активных списков с подсчетом незавершенных пунктов."""
        self.mgr.create_list("Покупки")
        self.mgr.add_list_item("Покупки", "Молоко")
        self.mgr.add_list_item("Покупки", "Хлеб")
        self.mgr.add_list_item("Покупки", "Сыр")
        self.mgr.add_list_item("Покупки", "Яблоки")
        self.mgr.add_list_item("Покупки", "Масло")
        # Отметим один пункт выполненным
        self.mgr.complete_list_item("Покупки", 1)

        # Пустой список не должен отображаться
        self.mgr.create_list("Фильмы")

        # Список, где все пункты выполнены, не должен отображаться
        self.mgr.create_list("Книги")
        self.mgr.add_list_item("Книги", "Война и мир")
        self.mgr.complete_list_item("Книги", 1)

        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        self.assertEqual(res["lists"]["active_lists_count"], 1)
        self.assertIn('• В списке "Покупки" осталось 4 пункта.', res["text"])
        self.assertNotIn("Фильмы", res["text"])
        self.assertNotIn("Книги", res["text"])

    def test_exact_specification_briefing(self):
        """
        Проверка эталонного примера из ТЗ:
        «На сегодня:
        • 3 задачи, из них 1 просрочена.
        • 2 напоминания.
        • 1 повторяющееся напоминание.
        • В списке "Покупки" осталось 4 пункта.»
        """
        # Задачи: 3 шт, 1 просрочена
        self.mgr.create_task("Задача 1", due_date="2026-09-15")  # просрочена
        self.mgr.create_task("Задача 2")
        self.mgr.create_task("Задача 3")

        # Напоминания: 2 одноразовых
        self.mgr.create_reminder("Напоминание 1", "2026-09-21 11:00:00")
        self.mgr.create_reminder("Напоминание 2", "2026-09-21 17:00:00")

        # Повторяющиеся: 1 шт
        self.mgr.create_reminder("Прием лекарств", "2026-09-21 12:00:00", repeat="daily")

        # Список: Покупки с 4 оставшимися пунктами
        self.mgr.create_list("Покупки")
        for i in range(1, 5):
            self.mgr.add_list_item("Покупки", f"Товар {i}")

        res = get_daily_briefing(household=self.mgr, target_date="2026-09-21")
        expected_text = (
            "На сегодня:\n"
            "• 3 задачи, из них 1 просрочена.\n"
            "• 2 напоминания.\n"
            "• 1 повторяющееся напоминание.\n"
            "• В списке \"Покупки\" осталось 4 пункта."
        )
        self.assertEqual(res["text"], expected_text)


class TestDailyBriefingRouting(unittest.TestCase):
    """Тесты распознавания и маршрутизации запросов дневного брифинга."""

    def setUp(self):
        self.router = CommandRouter()

    def test_router_natural_queries(self):
        queries = [
            "Что у меня сегодня?",
            "Что на сегодня?",
            "План на день",
            "Акакий, что запланировано на сегодня?",
            "дневной брифинг",
            "сводка дня",
            "план на сегодня",
            "какие планы на сегодня",
            "что по планам на сегодня?",
            "Что сегодня?",
        ]

        for q in queries:
            with self.subTest(query=q):
                res = self.router.choose_tool(q)
                self.assertEqual(res["tool"], "daily_briefing", f"Failed for query: {q}")
                route_res = self.router.route(q)
                self.assertEqual(route_res["type"], "tool")
                self.assertEqual(route_res["tool"], "daily_briefing")

    def test_router_does_not_break_other_commands(self):
        """Убеждаемся, что роутер не перехватывает чужие команды."""
        # Команды планов
        p1 = self.router.route("создай план: разработать модуль")
        self.assertEqual(p1["type"], "plan")
        self.assertEqual(p1["action"], "create")

        p2 = self.router.route("покажи план")
        self.assertEqual(p2["type"], "plan")
        self.assertEqual(p2["action"], "get")

        # Команды задач
        t1 = self.router.route("покажи задачи")
        self.assertEqual(t1["tool"], "list_tasks")

        # Команды файлов
        f1 = self.router.route("покажи список файлов")
        self.assertEqual(f1["tool"], "list_files")


class TestDailyBriefingIntegration(unittest.TestCase):
    """Интеграционные тесты CLI, Tools Registry и UI."""

    def test_tools_registry_registration(self):
        """Проверка регистрации в TOOLS и TOOL_PARAMETERS."""
        tool = get_tool("daily_briefing")
        self.assertIsNotNone(tool)
        self.assertFalse(tool["requires_confirmation"])
        self.assertTrue(callable(tool["function"]))

        schemas = get_tools_schema(["daily_briefing"])
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["function"]["name"], "daily_briefing")

    @patch("tools.daily_briefing.get_daily_briefing")
    def test_daily_briefing_tool_wrapper(self, mock_get_briefing):
        mock_get_briefing.return_value = {
            "success": True,
            "text": "На сегодня:\n• 1 задача.",
            "is_empty": False
        }
        res = daily_briefing()
        self.assertTrue(res["success"])
        self.assertEqual(res["message"], "На сегодня:\n• 1 задача.")
        self.assertIn("briefing", res)

    @patch("tools.daily_briefing.get_daily_briefing")
    def test_cli_handle_command(self, mock_get_briefing):
        """Проверка быстрых CLI команд :brief, :today, :сводка."""
        mock_get_briefing.return_value = {
            "success": True,
            "text": "На сегодня ничего не запланировано."
        }

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            handled1 = handle_cli_command(":brief")
            self.assertTrue(handled1)
            self.assertIn("На сегодня ничего не запланировано.", fake_out.getvalue())

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            handled2 = handle_cli_command(":today")
            self.assertTrue(handled2)
            self.assertIn("На сегодня ничего не запланировано.", fake_out.getvalue())

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            handled3 = handle_cli_command(":сводка")
            self.assertTrue(handled3)
            self.assertIn("На сегодня ничего не запланировано.", fake_out.getvalue())

    def test_home_view_briefing_ui_safe(self):
        """Проверка метода ui_show_daily_briefing в HomeView без падений при отключенном/включенном голосе."""
        import tkinter as tk
        from ui.views.home import HomeView

        root = tk.Tk()
        root.withdraw()
        try:
            # Создаем фиктивный shell без голоса
            fake_shell = MagicMock()
            fake_shell.voice = None
            fake_shell.household = None

            view = HomeView(root, shell=fake_shell)

            with patch("tkinter.messagebox.showinfo") as mock_box:
                view.ui_show_daily_briefing()
                mock_box.assert_called_once()
                args, _ = mock_box.call_args
                self.assertEqual(args[0], "⚡ Сводка дня")

            # Теперь с активным голосом
            mock_voice = MagicMock()
            mock_voice.is_running = True
            fake_shell.voice = mock_voice

            with patch("tkinter.messagebox.showinfo") as mock_box:
                view.ui_show_daily_briefing()
                mock_voice.speak_phrase.assert_called_once()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
