"""
Тесты для модуля переиспользуемой фильтрации и пагинации ui/pagination.py,
а также интеграции с TasksView и NotesView.
"""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from tools.household import HouseholdManager
from ui.pagination import PagedListController, PaginationBar, PaginationModel
from ui.views import NotesView, TasksView


class TestPaginationModel(unittest.TestCase):
    """Тестирование чистой модели PaginationModel."""

    def test_basic_pagination_calculations(self):
        items = [f"item_{i}" for i in range(25)]
        model = PaginationModel[str](items=items, page_size=10)

        self.assertEqual(model.total_items, 25)
        self.assertEqual(model.total_pages, 3)
        self.assertEqual(model.current_page, 1)
        self.assertFalse(model.has_prev)
        self.assertTrue(model.has_next)

        page1 = model.page_items
        self.assertEqual(len(page1), 10)
        self.assertEqual(page1[0], "item_0")
        self.assertEqual(page1[-1], "item_9")

    def test_navigation_next_prev_bounds(self):
        items = [1, 2, 3, 4, 5]
        model = PaginationModel[int](items=items, page_size=2)
        # Страниц: 3 (1-2, 3-4, 5)

        self.assertEqual(model.current_page, 1)
        self.assertFalse(model.prev_page())
        self.assertEqual(model.current_page, 1)

        self.assertTrue(model.next_page())
        self.assertEqual(model.current_page, 2)
        self.assertEqual(model.page_items, [3, 4])

        self.assertTrue(model.next_page())
        self.assertEqual(model.current_page, 3)
        self.assertEqual(model.page_items, [5])
        self.assertFalse(model.has_next)

        # Попытка уйти за границу
        self.assertFalse(model.next_page())
        self.assertEqual(model.current_page, 3)

        # Возврат назад
        self.assertTrue(model.prev_page())
        self.assertEqual(model.current_page, 2)
        self.assertTrue(model.prev_page())
        self.assertEqual(model.current_page, 1)

    def test_go_to_page(self):
        items = list(range(30))
        model = PaginationModel[int](items=items, page_size=10)

        self.assertTrue(model.go_to_page(3))
        self.assertEqual(model.current_page, 3)

        # Клик по той же странице не меняет состояние
        self.assertFalse(model.go_to_page(3))

        # Ограничения min/max
        model.go_to_page(999)
        self.assertEqual(model.current_page, 3)
        model.go_to_page(-5)
        self.assertEqual(model.current_page, 1)

    def test_filtering_and_original_data_preservation(self):
        items = [
            {"id": 1, "title": "Купить яблоки"},
            {"id": 2, "title": "Купить груши"},
            {"id": 3, "title": "Позвонить врачу"},
            {"id": 4, "title": "Купить бананы"},
        ]
        model = PaginationModel[dict](
            items=items,
            page_size=2,
            filter_fn=lambda it, q: q in it["title"].lower()
        )

        self.assertEqual(model.total_items, 4)
        self.assertEqual(model.total_pages, 2)

        # Применяем фильтр "купить"
        model.set_filter("купить")
        self.assertEqual(model.total_items, 3)
        self.assertEqual(model.total_pages, 2)
        self.assertEqual(len(model.page_items), 2)

        # Исходный список не мутирован!
        self.assertEqual(len(model._raw_items), 4)

        # Сброс фильтра
        model.set_filter("")
        self.assertEqual(model.total_items, 4)
        self.assertEqual(model.total_pages, 2)

    def test_filter_resets_page_to_first(self):
        items = [f"task_{i}" for i in range(20)]
        model = PaginationModel[str](items=items, page_size=5)

        # Переходим на 3 страницу
        model.go_to_page(3)
        self.assertEqual(model.current_page, 3)

        # Ввод фильтра должен вернуть на страницу 1
        model.set_filter("task_1")
        self.assertEqual(model.current_page, 1)

    def test_filter_no_results(self):
        items = [{"name": "Альфа"}, {"name": "Бета"}]
        model = PaginationModel[dict](
            items=items,
            page_size=2,
            filter_fn=lambda it, q: q in it["name"].lower()
        )

        model.set_filter("несуществующее_слово")
        self.assertEqual(model.total_items, 0)
        self.assertEqual(model.total_pages, 1)
        self.assertEqual(model.page_items, [])
        self.assertFalse(model.has_prev)
        self.assertFalse(model.has_next)

    def test_item_deletion_fallback_to_previous_page(self):
        # 3 элемента, page_size=2 -> 2 страницы: [0, 1] и [2]
        items = ["A", "B", "C"]
        model = PaginationModel[str](items=items, page_size=2)
        model.go_to_page(2)
        self.assertEqual(model.current_page, 2)
        self.assertEqual(model.page_items, ["C"])

        # Удаляем C -> остается 2 элемента -> 1 страница
        model.set_items(["A", "B"])
        self.assertEqual(model.total_pages, 1)
        # Должен автоматически откатиться на страницу 1
        self.assertEqual(model.current_page, 1)
        self.assertEqual(model.page_items, ["A", "B"])

    def test_reusability_with_arbitrary_objects(self):
        class CustomReport:
            def __init__(self, code: str, val: int):
                self.code = code
                self.val = val

        reports = [CustomReport(f"REP_{i}", i * 10) for i in range(12)]
        model = PaginationModel[CustomReport](
            items=reports,
            page_size=5,
            filter_fn=lambda r, q: q in r.code.lower()
        )

        self.assertEqual(model.total_pages, 3)
        self.assertEqual(len(model.page_items), 5)
        model.set_filter("rep_1")
        # REP_1, REP_10, REP_11 -> 3 элемента
        self.assertEqual(model.total_items, 3)
        self.assertEqual(model.total_pages, 1)


class TestPaginationBar(unittest.TestCase):
    """Тестирование визуального компонента PaginationBar."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_pagination_bar_state_updates(self):
        bar = PaginationBar(self.root)
        bar.pack()
        self.root.update_idletasks()

        model = PaginationModel[int](items=list(range(25)), page_size=10)
        # Стр 1 из 3
        bar.update_state(model)
        self.assertIn("Страница 1 из 3", bar.lbl_info.cget("text"))
        self.assertIn("Всего: 25", bar.lbl_info.cget("text"))
        self.assertEqual(bar.btn_prev.cget("state"), "disabled")
        self.assertEqual(bar.btn_next.cget("state"), "normal")

        # Переход на страницу 2
        model.go_to_page(2)
        bar.update_state(model)
        self.assertIn("Страница 2 из 3", bar.lbl_info.cget("text"))
        self.assertEqual(bar.btn_prev.cget("state"), "normal")
        self.assertEqual(bar.btn_next.cget("state"), "normal")

        # Переход на страницу 3
        model.go_to_page(3)
        bar.update_state(model)
        self.assertIn("Страница 3 из 3", bar.lbl_info.cget("text"))
        self.assertEqual(bar.btn_prev.cget("state"), "normal")
        self.assertEqual(bar.btn_next.cget("state"), "disabled")


class TestTasksViewIntegration(unittest.TestCase):
    """Интеграционное тестирование TasksView с поиском и пагинацией."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_tasks_pagination.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household

        # Создаем 15 задач
        for i in range(1, 16):
            self.household.create_task(f"Задача номер {i:02d}")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_tasks_pagination_and_search(self):
        view = TasksView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # При page_size=8 и 15 задачах: 2 страницы (8 на первой, 7 на второй)
        self.assertIsNotNone(view.entry_task_search)
        self.assertIsNotNone(view.pagination_bar)
        self.assertEqual(view.paged_controller.model.total_pages, 2)
        self.assertEqual(view.paged_controller.model.current_page, 1)

        # Проверяем отрисованные элементы первой страницы
        rows_page1 = view.tasks_list_frame.winfo_children()
        self.assertEqual(len(rows_page1), 8)

        # Переход на страницу 2
        view.paged_controller._on_next_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 2)
        rows_page2 = view.tasks_list_frame.winfo_children()
        self.assertEqual(len(rows_page2), 7)

        # Поиск по подстроке "05"
        view.entry_task_search.insert(0, "05")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        rows_filtered = view.tasks_list_frame.winfo_children()
        self.assertEqual(len(rows_filtered), 1)

        # Поиск без результатов
        view.entry_task_search.delete(0, tk.END)
        view.entry_task_search.insert(0, "абсолютно_несуществующая_задача")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 0)
        self.assertIn("не найдено", view.tasks_list_frame.winfo_children()[0].cget("text"))


class TestNotesViewIntegration(unittest.TestCase):
    """Интеграционное тестирование NotesView с поиском и пагинацией."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_notes_pagination.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household

        # Создаем 10 заметок
        for i in range(1, 11):
            self.household.create_note(f"Заметка {i:02d}", f"Секретный контент {i:02d}")

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

    def test_notes_pagination_and_search(self):
        view = NotesView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # При page_size=6 и 10 заметках: 2 страницы (6 на первой, 4 на второй)
        self.assertIsNotNone(view.entry_note_search)
        self.assertIsNotNone(view.pagination_bar)
        self.assertEqual(view.paged_controller.model.total_pages, 2)
        self.assertEqual(view.paged_controller.model.current_page, 1)

        # Первая страница: 6 карточек
        cards_page1 = view.notes_list_frame.winfo_children()
        self.assertEqual(len(cards_page1), 6)

        # Перелистываем на вторую
        view.paged_controller._on_next_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 2)
        cards_page2 = view.notes_list_frame.winfo_children()
        self.assertEqual(len(cards_page2), 4)

        # Поиск по содержимому: "контент 07"
        view.entry_note_search.insert(0, "контент 07")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        cards_filtered = view.notes_list_frame.winfo_children()
        self.assertEqual(len(cards_filtered), 1)

        # Удаление заметки на второй странице
        view.entry_note_search.delete(0, tk.END)
        view._on_search_changed()
        view.paged_controller.go_to_page(2)
        self.assertEqual(view.paged_controller.model.current_page, 2)


if __name__ == "__main__":
    unittest.main()
