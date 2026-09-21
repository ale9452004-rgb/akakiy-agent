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
from tools.memory import MemoryManager
from ui.pagination import PagedListController, PaginationBar, PaginationModel
from ui.views import ListsView, MemoryView, NotesView, TasksView


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


class TestMemoryViewPaginationIntegration(unittest.TestCase):
    """Интеграционное тестирование MemoryView с поиском и пагинацией."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_memory_pagination.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.memory = MemoryManager(storage_path=self.storage_path)
        self.mock_shell = MagicMock()
        self.mock_shell.memory = self.memory

        # Создаем 15 фактов памяти
        self.memory.memories = [
            {
                "id": i,
                "text": f"Факт номер {i:02d} для проверки памяти",
                "category": "general",
                "created_at": f"2026-09-21 12:{i:02d}:00"
            }
            for i in range(1, 16)
        ]
        self.memory._save_memories()

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

    def test_memory_pagination_and_navigation(self):
        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # При page_size=8 и 15 фактах: 2 страницы (8 на 1-й, 7 на 2-й)
        self.assertIsNotNone(view.entry_mem_search)
        self.assertIsNotNone(view.pagination_bar)
        self.assertEqual(view.paged_controller.model.total_pages, 2)
        self.assertEqual(view.paged_controller.model.current_page, 1)

        # 1-я страница: 8 строк
        rows_page1 = view.mem_list_frame.winfo_children()
        self.assertEqual(len(rows_page1), 8)

        # Переход на 2-ю страницу
        view.paged_controller._on_next_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 2)
        rows_page2 = view.mem_list_frame.winfo_children()
        self.assertEqual(len(rows_page2), 7)

        # Возврат на 1-ю страницу
        view.paged_controller._on_prev_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 1)

    def test_memory_filtering_by_text_and_id(self):
        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # Поиск по тексту: "номер 05"
        view.entry_mem_search.insert(0, "номер 05")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        self.assertEqual(len(view.mem_list_frame.winfo_children()), 1)

        # Поиск по ID с префиксом #
        view.entry_mem_search.delete(0, tk.END)
        view.entry_mem_search.insert(0, "#3")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)

        # Поиск по числовому ID без префикса #
        view.entry_mem_search.delete(0, tk.END)
        view.entry_mem_search.insert(0, "7")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)

    def test_memory_search_empty_result(self):
        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        view.entry_mem_search.insert(0, "абсолютно_несуществующий_факт_xyz")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 0)
        children = view.mem_list_frame.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIn("не найдено", children[0].cget("text"))

    def test_memory_deletion_on_last_page_fallback(self):
        # 9 элементов (при page_size=8: 8 на стр 1, 1 на стр 2)
        self.memory.memories = [
            {
                "id": i,
                "text": f"Короткий факт {i:02d}",
                "category": "general",
                "created_at": f"2026-09-21 12:{i:02d}:00"
            }
            for i in range(1, 10)
        ]
        self.memory._save_memories()

        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_pages, 2)
        view.paged_controller.go_to_page(2)
        self.assertEqual(view.paged_controller.model.current_page, 2)
        self.assertEqual(len(view.mem_list_frame.winfo_children()), 1)

        # Удаляем самый старый факт (который на 2-й странице, так как список отображается reversed)
        all_mems = self.memory.get_all()
        # all_mems[0] имеет id=1 и находится на странице 2
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_forget(all_mems[0]["id"])
        self.root.update_idletasks()

        # Пагинация должна автоматически откатиться на страницу 1
        self.assertEqual(view.paged_controller.model.total_pages, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        self.assertEqual(len(view.mem_list_frame.winfo_children()), 8)

    def test_memory_crud_preservation(self):
        view = MemoryView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        initial_count = len(self.memory.get_all())

        # Добавление через UI
        view.entry_mem.insert(0, "Новый уникальный факт для проверки CRUD")
        view.ui_remember()
        self.root.update_idletasks()

        self.assertEqual(len(self.memory.get_all()), initial_count + 1)
        new_m = [m for m in self.memory.get_all() if "Новый уникальный факт" in m["text"]][0]

        # Удаление через UI
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_forget(new_m["id"])
        self.root.update_idletasks()

        self.assertEqual(len(self.memory.get_all()), initial_count)


class TestListsViewPaginationIntegration(unittest.TestCase):
    """Интеграционное тестирование ListsView с поиском и пагинацией списков."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.storage_path = os.path.join(WORKSPACE, "scratch", "test_lists_pagination.json")
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except Exception:
                pass

        self.household = HouseholdManager(storage_path=self.storage_path)
        self.mock_shell = MagicMock()
        self.mock_shell.household = self.household

        # Создаем 15 списков
        self.household.lists = {
            f"список_{i:02d}": [
                {"id": 1, "text": f"Пункт 1 в список_{i:02d}", "completed": False, "created_at": "2026-09-21 12:00:00"},
                {"id": 2, "text": f"Пункт 2 в список_{i:02d}", "completed": False, "created_at": "2026-09-21 12:00:00"}
            ]
            for i in range(1, 16)
        }
        self.household._save()

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

    def test_lists_pagination_and_navigation(self):
        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # При page_size=8 и 15 списках: 2 страницы (8 на 1-й, 7 на 2-й)
        self.assertIsNotNone(view.entry_list_search)
        self.assertIsNotNone(view.pagination_bar)
        self.assertEqual(view.paged_controller.model.total_pages, 2)
        self.assertEqual(view.paged_controller.model.current_page, 1)

        # 1-я страница: 8 кнопок списков
        btns_page1 = view.list_names_box.winfo_children()
        self.assertEqual(len(btns_page1), 8)

        # Переход на 2-ю страницу
        view.paged_controller._on_next_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 2)
        btns_page2 = view.list_names_box.winfo_children()
        self.assertEqual(len(btns_page2), 7)

        # Проверяем, что элементы выбранного списка в правой панели не сломаны
        self.assertIn("список_", view.current_selected_list)
        items_frame = view.right_items_pane.winfo_children()
        self.assertGreater(len(items_frame), 0)

        # Возврат на 1-ю страницу
        view.paged_controller._on_prev_page()
        self.root.update_idletasks()
        self.assertEqual(view.paged_controller.model.current_page, 1)

    def test_lists_filtering_by_name_and_id(self):
        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # Поиск по названию: "список_07"
        view.entry_list_search.insert(0, "список_07")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        self.assertEqual(len(view.list_names_box.winfo_children()), 1)

        # Поиск по ID с префиксом #
        view.entry_list_search.delete(0, tk.END)
        view.entry_list_search.insert(0, "#4")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)

        # Поиск по числовому ID
        view.entry_list_search.delete(0, tk.END)
        view.entry_list_search.insert(0, "14")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 1)

    def test_lists_search_empty_result(self):
        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        view.entry_list_search.insert(0, "абсолютно_несуществующий_список_abc")
        view._on_search_changed()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_items, 0)
        children = view.list_names_box.winfo_children()
        self.assertEqual(len(children), 1)
        self.assertIn("не найдено", children[0].cget("text"))

    def test_lists_deletion_on_last_page_fallback(self):
        # Ровно 9 списков (8 на стр 1, 1 на стр 2)
        self.household.lists = {f"папка_{i:02d}": [] for i in range(1, 10)}
        self.household._save()

        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        self.assertEqual(view.paged_controller.model.total_pages, 2)
        view.paged_controller.go_to_page(2)
        self.assertEqual(view.paged_controller.model.current_page, 2)
        self.assertEqual(len(view.list_names_box.winfo_children()), 1)

        # Удаляем единственный список на стр 2 ("папка_09")
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_entire_list("папка_09")
        self.root.update_idletasks()

        # Автоматический откат на страницу 1
        self.assertEqual(view.paged_controller.model.total_pages, 1)
        self.assertEqual(view.paged_controller.model.current_page, 1)
        self.assertEqual(len(view.list_names_box.winfo_children()), 8)

    def test_lists_crud_and_item_checkboxes_preservation(self):
        view = ListsView(self.root, shell=self.mock_shell)
        view.pack()
        self.root.update_idletasks()

        # Создание нового списка через UI
        view.entry_new_list.insert(0, "список_тест_круд")
        view.ui_create_list()
        self.root.update_idletasks()
        self.assertIn("список_тест_круд", self.household.lists)

        # Выбор списка и добавление пункта
        view.select_list("список_тест_круд")
        self.assertIsNotNone(view.entry_item_text)
        view.entry_item_text.insert(0, "Купить отвертку")
        view.ui_add_item("список_тест_круд")
        self.root.update_idletasks()

        items = self.household.lists["список_тест_круд"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["completed"])
        item_id = items[0]["id"]

        # Переключение чекбокса (complete)
        view.ui_toggle_item("список_тест_круд", item_id)
        self.assertTrue(self.household.lists["список_тест_круд"][0]["completed"])

        # Удаление пункта
        view.ui_delete_item("список_тест_круд", item_id)
        self.assertEqual(len(self.household.lists["список_тест_круд"]), 0)

        # Удаление списка целиком
        with patch("tkinter.messagebox.askyesno", return_value=True):
            view.ui_delete_entire_list("список_тест_круд")
        self.assertNotIn("список_тест_круд", self.household.lists)


if __name__ == "__main__":
    unittest.main()
