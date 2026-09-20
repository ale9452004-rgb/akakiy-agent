"""
Набор автоматизированных тестов для Household Assistant 1.0 (Task 36).

Проверяет:
1. CRUD для Tasks (создание, просмотр, выполнение, удаление, фильтрация).
2. CRUD для Reminders (создание, просмотр, наступление, удаление).
3. CRUD для Notes (создание, просмотр, поиск по ключевым словам, удаление).
4. CRUD для Lists (создание списка, добавление/выполнение/удаление пунктов, удаление списка целиком).
5. Persistence после перезапуска HouseholdManager на том же файле.
6. Уникальные идентификаторы (ID) сущностей.
7. Логику наступления напоминаний (check_due_reminders).
8. Работу с несколькими независимыми списками.
9. Присутствие 'project', 'memory', 'household' в SkillRegistry.
10. Отсутствие дублирования инструментов (все 18 инструментов из TOOLS).
11. Изоляцию и единый ContextManager (отсутствие собственного клиента и истории).
12. Подтверждение и отмену операций удаления через Dispatcher (confirmation/cancellation).
13. Пропуск обычного чата (обычный разговор не активирует household skill).
14. Native Tool Calling в Agent при выборе household skill.
15. Совместимость с GUI и Voice импортами.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Обеспечиваем импорт из корня проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.household import (
    HouseholdManager,
    get_household_manager,
    reset_household_manager,
    parse_reminder_time
)
from tools.registry import TOOLS, get_tools_schema
from tools.dispatcher import set_confirmation_handler, get_confirmation_handler, dispatch
from tools.context import ContextManager
from tools.memory import MemoryManager
from tools.agent import Agent

from skills.base import BaseSkill
from skills.registry import SkillRegistry, get_skill_registry, reset_skill_registry
from skills.household import HouseholdSkill


class TestHouseholdManagerTasks(unittest.TestCase):
    """1. CRUD для Tasks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        self.hm = HouseholdManager(storage_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_list_tasks(self):
        res1 = self.hm.create_task("Купить кофе")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["task"]["id"], 1)
        self.assertEqual(res1["task"]["title"], "Купить кофе")
        self.assertFalse(res1["task"]["completed"])

        res2 = self.hm.create_task("Полить цветы")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["task"]["id"], 2)

        # Просмотр всех задач
        list_res = self.hm.list_tasks(status="all")
        self.assertTrue(list_res["success"])
        self.assertEqual(len(list_res["tasks"]), 2)

    def test_complete_and_filter_tasks(self):
        self.hm.create_task("Задача 1")
        self.hm.create_task("Задача 2")

        # Выполняем задачу #1
        comp_res = self.hm.complete_task(1)
        self.assertTrue(comp_res["success"])
        self.assertTrue(comp_res["task"]["completed"])

        # Фильтр по активным (pending)
        pending = self.hm.list_tasks(status="pending")
        self.assertEqual(len(pending["tasks"]), 1)
        self.assertEqual(pending["tasks"][0]["id"], 2)

        # Фильтр по выполненным (completed)
        completed = self.hm.list_tasks(status="completed")
        self.assertEqual(len(completed["tasks"]), 1)
        self.assertEqual(completed["tasks"][0]["id"], 1)

    def test_delete_task(self):
        self.hm.create_task("Удаляемая задача")
        del_res = self.hm.delete_task(1)
        self.assertTrue(del_res["success"])
        self.assertEqual(len(self.hm.tasks), 0)

        # Повторное удаление возвращает ошибку
        del_again = self.hm.delete_task(1)
        self.assertFalse(del_again["success"])


class TestHouseholdManagerReminders(unittest.TestCase):
    """2. CRUD для Reminders и наступление напоминаний."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        self.hm = HouseholdManager(storage_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_list_reminders(self):
        res = self.hm.create_reminder("Позвонить врачу", "2026-09-20 19:00:00")
        self.assertTrue(res["success"])
        self.assertEqual(res["reminder"]["id"], 1)
        self.assertEqual(res["reminder"]["text"], "Позвонить врачу")
        self.assertFalse(res["reminder"]["triggered"])

        list_res = self.hm.list_reminders()
        self.assertEqual(len(list_res["reminders"]), 1)

    def test_check_due_reminders(self):
        now = datetime(2026, 9, 20, 15, 0, 0)
        past_time = "2026-09-20 14:00:00"
        future_time = "2026-09-20 16:00:00"

        self.hm.create_reminder("Прошедшее напоминание", past_time)
        self.hm.create_reminder("Будущее напоминание", future_time)

        # Проверяем наступившие к 15:00
        due_res = self.hm.check_due_reminders(current_time=now.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertTrue(due_res["success"])
        self.assertEqual(due_res["due_count"], 1)
        self.assertEqual(due_res["reminders"][0]["text"], "Прошедшее напоминание")
        self.assertTrue(due_res["reminders"][0]["triggered"])

        # Повторная проверка не возвращает уже сработавшие
        due_res_2 = self.hm.check_due_reminders(current_time=now.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(due_res_2["due_count"], 0)

        # Будущее напоминание остаётся в активном списке
        active = self.hm.list_reminders(include_triggered=False)
        self.assertEqual(len(active["reminders"]), 1)
        self.assertEqual(active["reminders"][0]["text"], "Будущее напоминание")

    def test_delete_reminder(self):
        self.hm.create_reminder("Напомнить", "19:00")
        del_res = self.hm.delete_reminder(1)
        self.assertTrue(del_res["success"])
        self.assertEqual(len(self.hm.reminders), 0)


class TestHouseholdManagerNotes(unittest.TestCase):
    """3. CRUD для Notes и поиск."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        self.hm = HouseholdManager(storage_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_search_notes(self):
        self.hm.create_note("Пароль Wi-Fi", "Secret123Pass")
        self.hm.create_note("Список книг", "Мартин Фаулер Рефакторинг")

        list_res = self.hm.list_notes()
        self.assertEqual(len(list_res["notes"]), 2)

        # Поиск по слову 'Фаулер'
        search_res = self.hm.search_notes("Фаулер")
        self.assertTrue(search_res["success"])
        self.assertEqual(len(search_res["notes"]), 1)
        self.assertEqual(search_res["notes"][0]["title"], "Список книг")

        # Поиск по несуществующему слову
        not_found = self.hm.search_notes("Космос")
        self.assertEqual(len(not_found["notes"]), 0)

    def test_delete_note(self):
        self.hm.create_note("Удалить", "Текст")
        del_res = self.hm.delete_note(1)
        self.assertTrue(del_res["success"])
        self.assertEqual(len(self.hm.notes), 0)


class TestHouseholdManagerLists(unittest.TestCase):
    """4. CRUD для Lists и независимость нескольких списков."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        self.hm = HouseholdManager(storage_path=self.file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_populate_list(self):
        res = self.hm.create_list("покупки")
        self.assertTrue(res["success"])

        # Добавляем элементы
        item1 = self.hm.add_list_item("покупки", "Хлеб")
        self.assertTrue(item1["success"])
        self.assertEqual(item1["item"]["id"], 1)

        item2 = self.hm.add_list_item("покупки", "Сыр")
        self.assertTrue(item2["success"])
        self.assertEqual(item2["item"]["id"], 2)

        # Просмотр содержимого
        show_res = self.hm.show_list("покупки")
        self.assertEqual(len(show_res["items"]), 2)

    def test_complete_and_delete_item(self):
        self.hm.add_list_item("дела", "Сдать отчёт")
        self.hm.add_list_item("дела", "Позвонить маме")

        # Отмечаем выполнение первого пункта
        comp_res = self.hm.complete_list_item("дела", 1)
        self.assertTrue(comp_res["success"])
        self.assertTrue(comp_res["item"]["completed"])

        # Удаляем второй пункт
        del_res = self.hm.delete_list_item("дела", 2)
        self.assertTrue(del_res["success"])

        show_res = self.hm.show_list("дела")
        self.assertEqual(len(show_res["items"]), 1)
        self.assertEqual(show_res["items"][0]["text"], "Сдать отчёт")

    def test_multiple_independent_lists(self):
        self.hm.add_list_item("продукты", "Яблоки")
        self.hm.add_list_item("фильмы", "Интерстеллар")

        # Удаление пункта в фильмах не трогает продукты
        self.hm.delete_list_item("фильмы", 1)
        self.assertEqual(len(self.hm.show_list("фильмы")["items"]), 0)
        self.assertEqual(len(self.hm.show_list("продукты")["items"]), 1)

        # Удаление списка целиком
        del_list = self.hm.delete_list("фильмы")
        self.assertTrue(del_list["success"])
        self.assertNotIn("фильмы", self.hm.lists)
        self.assertIn("продукты", self.hm.lists)


class TestPersistenceAndIsolation(unittest.TestCase):
    """5. Persistence после перезапуска и уникальные ID."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persistence_across_restarts(self):
        # 1-й запуск: создаём данные
        hm1 = HouseholdManager(storage_path=self.file_path)
        hm1.create_task("Повторяющаяся задача")
        hm1.create_reminder("Напоминание 1", "18:00")
        hm1.create_note("Заметка 1", "Секретный текст")
        hm1.add_list_item("планы", "Пункт 1")

        # 2-й запуск: создаём новый экземпляр HouseholdManager на том же файле
        hm2 = HouseholdManager(storage_path=self.file_path)
        self.assertEqual(len(hm2.tasks), 1)
        self.assertEqual(hm2.tasks[0]["title"], "Повторяющаяся задача")
        self.assertEqual(len(hm2.reminders), 1)
        self.assertEqual(len(hm2.notes), 1)
        self.assertEqual(hm2.notes[0]["content"], "Секретный текст")
        self.assertEqual(len(hm2.lists.get("планы", [])), 1)

    def test_id_auto_increment_no_collision(self):
        hm = HouseholdManager(storage_path=self.file_path)
        t1 = hm.create_task("Задача 1")["task"]["id"]
        t2 = hm.create_task("Задача 2")["task"]["id"]
        self.assertEqual(t1, 1)
        self.assertEqual(t2, 2)

        # Удаляем задачу #2 и создаём новую — ID должен быть 3, без коллизии
        hm.delete_task(2)
        t3 = hm.create_task("Задача 3")["task"]["id"]
        self.assertEqual(t3, 3)


class TestSkillRegistryAndHouseholdTools(unittest.TestCase):
    """6. Проверка SkillRegistry и отсутствие дублирования инструментов."""

    def setUp(self):
        reset_skill_registry()

    def tearDown(self):
        reset_skill_registry()

    def test_skill_registry_contains_three_builtin_skills(self):
        registry = get_skill_registry()
        skills = registry.get_all()
        names = {s.name for s in skills}

        self.assertIn("project", names)
        self.assertIn("memory", names)
        self.assertIn("household", names)
        self.assertEqual(len(names), 3)

    def test_household_tools_exist_in_registry(self):
        h_skill = HouseholdSkill()
        self.assertEqual(len(h_skill.tools), 18)

        # Все 18 инструментов должны быть зарегистрированы в tools.registry.TOOLS
        for t in h_skill.tools:
            self.assertIn(t, TOOLS, f"Инструмент '{t}' отсутствует в TOOLS")

        # Проверяем получение OpenAPI схем
        schemas = h_skill.get_tools_schema()
        self.assertEqual(len(schemas), 18)
        schema_names = {s["function"]["name"] for s in schemas}
        self.assertEqual(schema_names, set(h_skill.tools))

    def test_household_skill_has_no_client_or_history(self):
        h_skill = HouseholdSkill()
        self.assertFalse(hasattr(h_skill, "ai"))
        self.assertFalse(hasattr(h_skill, "client"))
        self.assertFalse(hasattr(h_skill, "history"))
        self.assertFalse(hasattr(h_skill, "messages"))


class TestHouseholdSkillMatching(unittest.TestCase):
    """7. Детерминированный выбор household и пропуск обычного чата."""

    def setUp(self):
        reset_skill_registry()
        self.registry = get_skill_registry()

    def tearDown(self):
        reset_skill_registry()

    def test_matching_household_queries(self):
        household_queries = [
            "Добавь задачу купить молоко",
            "Покажи список задач",
            "Выполни задачу номер 2",
            "Напомни мне позвонить маме в 19:00",
            "Покажи напоминания",
            "Создай заметку рецепт борща",
            "Найди заметку про пароли",
            "Добавь в список покупок яблоки",
            "Покажи список покупок",
            "Создай новый список подарки",
            "Удали список фильмы"
        ]

        for q in household_queries:
            matched = self.registry.find_matching_skill(q)
            self.assertIsNotNone(matched, f"Запрос '{q}' должен был сопоставиться с household")
            self.assertEqual(matched.name, "household", f"Запрос '{q}' сопоставился с '{matched.name}'")

    def test_casual_chat_does_not_match_household(self):
        casual_queries = [
            "Привет, как дела?",
            "Что нового в мире?",
            "Расскажи анекдот",
            "Кто такой Аристотель?",
            "Спасибо за ответ!"
        ]

        for q in casual_queries:
            matched = self.registry.find_matching_skill(q)
            self.assertIsNone(matched, f"Обычный диалог '{q}' не должен сопоставляться с навыком")


class TestConfirmationAndCancellation(unittest.TestCase):
    """8. Подтверждение и отмена операций удаления через Dispatcher."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        reset_household_manager()
        self.hm = get_household_manager(storage_path=self.file_path)
        self.hm.create_task("Важная задача")

    def tearDown(self):
        reset_household_manager()
        self.temp_dir.cleanup()

    def test_delete_requires_confirmation_rejected(self):
        # Пользователь отклоняет удаление
        old_handler = get_confirmation_handler()
        set_confirmation_handler(lambda tool, kwargs: False)

        try:
            res = dispatch("delete_task", task_id=1)
            self.assertFalse(res["success"])
            self.assertIn("отменил", res["error"])
            # Задача НЕ должна быть удалена
            self.assertEqual(len(self.hm.tasks), 1)
        finally:
            set_confirmation_handler(old_handler)

    def test_delete_requires_confirmation_approved(self):
        # Пользователь подтверждает удаление
        old_handler = get_confirmation_handler()
        set_confirmation_handler(lambda tool, kwargs: True)

        try:
            res = dispatch("delete_task", task_id=1)
            self.assertTrue(res["success"])
            # Задача успешно удалена
            self.assertEqual(len(self.hm.tasks), 0)
        finally:
            set_confirmation_handler(old_handler)


class TestAgentNativeToolCallingHousehold(unittest.TestCase):
    """9. Native Tool Calling в Agent при выборе household."""

    def setUp(self):
        reset_skill_registry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "test_household.json"
        reset_household_manager()
        self.hm = get_household_manager(storage_path=self.file_path)
        self.mem_mgr = MemoryManager(storage_path=None)
        self.ctx = ContextManager(memory_manager=self.mem_mgr)

    def tearDown(self):
        reset_household_manager()
        reset_skill_registry()
        self.temp_dir.cleanup()

    def test_agent_scopes_tools_to_household(self):
        mock_ai = MagicMock()
        mock_ai.send_chat.return_value = {
            "content": "Задача успешно добавлена.",
            "tool_calls": []
        }

        agent = Agent(memory_manager=self.mem_mgr, context_manager=self.ctx, ai_client=mock_ai)

        resp = agent.process("Нужно купить в магазине продукты к ужину")
        self.assertEqual(resp["type"], "chat")

        self.assertTrue(mock_ai.send_chat.called)
        call_args = mock_ai.send_chat.call_args
        passed_tools = call_args[1]["tools"]
        passed_messages = call_args[0][0]

        passed_names = {t["function"]["name"] for t in passed_tools}
        self.assertEqual(passed_names, set(HouseholdSkill().tools))
        self.assertNotIn("git_commit", passed_names)
        self.assertNotIn("search_files", passed_names)
        self.assertIn("create_task", passed_names)

        # Системное сообщение содержит инструкции household
        self.assertIn("household", passed_messages[0]["content"])


class TestGUIAndVoiceImports(unittest.TestCase):
    """10. Совместимость с GUI и Voice."""

    def test_imports(self):
        import gui
        from voice.service import VoiceService
        from tools.agent import Agent

        agent = Agent()
        # Проверяем, что VoiceService инициализируется с агентом без ошибок
        voice = VoiceService(agent=agent)
        self.assertIsNotNone(voice)
        self.assertIsNotNone(agent.skill_registry.get("household"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
