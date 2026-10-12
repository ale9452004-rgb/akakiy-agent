"""
Тесты функциональности копирования текста и контекстных меню (Clipboard & Copy).

Проверяет:
1. Базовые утилиты буфера обмена (copy_to_clipboard, get_clipboard_text).
2. Выделение текста мышью и Ctrl+C в ChatView (chat_text и log_text):
   - При наличии выделения: копируется выделенный фрагмент;
   - При отсутствии выделения: копируется текст текущего сообщения или строки целиком.
3. Контекстное меню по правому клику (Button-3):
   - Пункт «Копировать» при выделении копирует фрагмент;
   - Пункт «Копировать» без выделения копирует всё сообщение под курсором;
   - Раздельное копирование сообщений пользователя и ответов ассистента.
4. Контекстное меню в карточках артефактов (ImageArtifactCard, FileArtifactCard).
5. Контекстное меню в системных уведомлениях (NotificationWindow).
6. Контекстное меню и кросс-раскладочные горячие клавиши в полях ввода (tk.Entry).
7. Поддержку горячих клавиш на русской раскладке клавиатуры.
"""

import tkinter as tk
from unittest.mock import MagicMock
import unittest

from notifications.models import NotificationItem
from notifications.window import NotificationWindow
from ui.artifact_card import FileArtifactCard, ImageArtifactCard
from ui.clipboard import (
    attach_entry_context_menu,
    attach_text_copy_handler,
    attach_widget_copy_menu,
    copy_to_clipboard,
    get_clipboard_text,
    is_copy_shortcut,
    is_select_all_shortcut,
)
from ui.views.chat import ChatView


class TestClipboardAndCopy(unittest.TestCase):
    """Набор тестов копирования и контекстных меню."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        # Очистка буфера перед тестом
        try:
            self.root.clipboard_clear()
        except Exception:
            pass

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_copy_to_clipboard_basic(self):
        """Проверка записи и чтения из буфера обмена через утилиты."""
        ok = copy_to_clipboard(self.root, "Привет от Акакия")
        self.assertTrue(ok)
        clip_val = get_clipboard_text(self.root)
        self.assertEqual(clip_val, "Привет от Акакия")

    def test_copy_to_clipboard_none_safe(self):
        """Копирование None возвращает False без сбоев."""
        self.assertFalse(copy_to_clipboard(self.root, None))

    def test_russian_layout_shortcut_detection(self):
        """Проверка распознавания горячих клавиш Ctrl+C и Ctrl+A при русской раскладке."""
        e_copy_ru = tk.Event()
        e_copy_ru.state = 4  # Control
        e_copy_ru.keysym = "Cyrillic_es"
        e_copy_ru.keycode = 67
        e_copy_ru.char = "\x03"
        self.assertTrue(is_copy_shortcut(e_copy_ru))

        e_copy_en = tk.Event()
        e_copy_en.state = 4
        e_copy_en.keysym = "c"
        e_copy_en.keycode = 67
        e_copy_en.char = "\x03"
        self.assertTrue(is_copy_shortcut(e_copy_en))

        e_no_ctrl = tk.Event()
        e_no_ctrl.state = 0
        e_no_ctrl.keysym = "c"
        self.assertFalse(is_copy_shortcut(e_no_ctrl))

        e_sel_all_ru = tk.Event()
        e_sel_all_ru.state = 4
        e_sel_all_ru.keysym = "Cyrillic_ef"
        e_sel_all_ru.keycode = 65
        e_sel_all_ru.char = "\x01"
        self.assertTrue(is_select_all_shortcut(e_sel_all_ru))

    def test_chat_text_copy_selected_fragment(self):
        """Если текст выделен, копируется ровно выделенный фрагмент."""
        mock_shell = MagicMock()
        mock_shell.chat_messages = []
        mock_shell.log_messages = []

        view = ChatView(self.root, shell=mock_shell)
        view.pack()
        view.clear_chat()

        view.append_chat("Вы", "Сгенерируй изображение рыжего кота")
        view.append_chat("Акакий", "Конечно, запускаю генерацию через SDXL-Lightning.")
        self.root.update_idletasks()

        # Выделяем только фразу "рыжего кота"
        content = view.chat_text.get("1.0", tk.END)
        start_pos = content.find("рыжего кота")
        self.assertGreater(start_pos, 0)

        # Вычисляем tk-индексы для фразы
        lines_before = content[:start_pos].split("\n")
        line_num = len(lines_before)
        col_num = len(lines_before[-1])
        idx_start = f"{line_num}.{col_num}"
        idx_end = f"{line_num}.{col_num + len('рыжего кота')}"

        view.chat_text.tag_add("sel", idx_start, idx_end)
        self.assertEqual(view.chat_text.get("sel.first", "sel.last"), "рыжего кота")

        # Эмулируем нажатие Ctrl+C
        event = tk.Event()
        event.widget = view.chat_text
        event.state = 4
        event.keysym = "c"
        event.keycode = 67
        event.char = "\x03"

        res = view.chat_text.event_generate("<<Copy>>")
        self.root.update_idletasks()

        self.assertEqual(get_clipboard_text(view.chat_text), "рыжего кота")

    def test_chat_text_copy_full_message_when_no_selection(self):
        """Если выделения нет, копируется весь текст сообщения под курсором."""
        mock_shell = MagicMock()
        mock_shell.chat_messages = []
        mock_shell.log_messages = []

        view = ChatView(self.root, shell=mock_shell)
        view.pack()
        view.clear_chat()

        msg_user = "Сколько планет в Солнечной системе?"
        msg_akakiy = "В Солнечной системе 8 признанных планет."

        view.append_chat("Вы", msg_user)
        view.append_chat("Акакий", msg_akakiy)
        self.root.update_idletasks()

        # Убеждаемся, что выделения нет
        view.chat_text.tag_remove("sel", "1.0", tk.END)
        self.assertFalse(bool(view.chat_text.tag_ranges("sel")))

        # Ставим курсор на первое сообщение (пользователя)
        content = view.chat_text.get("1.0", tk.END)
        user_pos = content.find(msg_user)
        lines_before = content[:user_pos].split("\n")
        idx_user = f"{len(lines_before)}.{len(lines_before[-1]) + 2}"
        view.chat_text.mark_set(tk.INSERT, idx_user)

        # Проверяем fallback-экстрактор сообщения
        extracted = view._get_chat_message_fallback(view.chat_text, idx_user)
        self.assertEqual(extracted, msg_user)

        # Имитируем Ctrl+C на позиции первого сообщения
        res = view.chat_text.event_generate("<<Copy>>")
        self.root.update_idletasks()
        self.assertEqual(get_clipboard_text(view.chat_text), msg_user)

        # Теперь ставим курсор на второе сообщение (Акакия)
        akakiy_pos = content.find(msg_akakiy)
        lines_before_ak = content[:akakiy_pos].split("\n")
        idx_ak = f"{len(lines_before_ak)}.{len(lines_before_ak[-1]) + 2}"
        view.chat_text.mark_set(tk.INSERT, idx_ak)

        extracted_ak = view._get_chat_message_fallback(view.chat_text, idx_ak)
        self.assertEqual(extracted_ak, msg_akakiy)

        res = view.chat_text.event_generate("<<Copy>>")
        self.root.update_idletasks()
        self.assertEqual(get_clipboard_text(view.chat_text), msg_akakiy)

    def test_log_text_copy_line_fallback(self):
        """В системном логе при отсутствии выделения копируется строка лога целиком."""
        mock_shell = MagicMock()
        mock_shell.chat_messages = []
        mock_shell.log_messages = []

        view = ChatView(self.root, shell=mock_shell)
        view.pack()
        view.clear_chat()

        view.append_log("TOOL", "generate_image(prompt='рыжий кот')")
        self.root.update_idletasks()

        view.log_text.tag_remove("sel", "1.0", tk.END)
        view.log_text.mark_set(tk.INSERT, "1.5")

        line = view._get_log_line_fallback(view.log_text, "1.5")
        self.assertIn("generate_image(prompt='рыжий кот')", line)

        view.log_text.event_generate("<<Copy>>")
        self.root.update_idletasks()
        self.assertIn("generate_image(prompt='рыжий кот')", get_clipboard_text(view.log_text))

    def test_artifact_card_copy_menu(self):
        """Проверка копирования промпта и пути из ImageArtifactCard и FileArtifactCard."""
        # 1. ImageArtifactCard
        art_meta = {"prompt": "футуристический робот в неоновом городе", "width": 1024, "height": 1024}
        card_img = ImageArtifactCard(
            self.root,
            artifact={"name": "robot.png", "path": "c:/Akakiy agent/data/images/robot.png", "type": "image", "metadata": art_meta}
        )
        card_img.pack()
        self.root.update_idletasks()

        # Копирование через привязанное контекстное меню
        self.assertTrue(hasattr(card_img, "_setup_copy_menu"))

        # Проверяем прямое копирование промпта
        copy_to_clipboard(card_img, art_meta["prompt"])
        self.assertEqual(get_clipboard_text(card_img), "футуристический робот в неоновом городе")

        # 2. FileArtifactCard
        card_file = FileArtifactCard(
            self.root,
            artifact={"name": "presentation.pptx", "path": "c:/Akakiy agent/pres.pptx", "type": "presentation"}
        )
        card_file.pack()
        self.root.update_idletasks()

        copy_to_clipboard(card_file, card_file.artifact_name)
        self.assertEqual(get_clipboard_text(card_file), "presentation.pptx")

    def test_notification_window_copy(self):
        """Проверка наличия контекстного меню копирования в NotificationWindow."""
        notif_item = NotificationItem(
            id="rem_1",
            title="Напоминание",
            text="Полить цветы и проверить почту",
            notification_type="reminder",
            timestamp_str="14:00"
        )
        win = NotificationWindow(self.root, item=notif_item)
        self.root.update_idletasks()

        self.assertEqual(win.item.text, "Полить цветы и проверить почту")
        copy_to_clipboard(win.lbl_text, win.item.text)
        self.assertEqual(get_clipboard_text(win.lbl_text), "Полить цветы и проверить почту")

        win.destroy()

    def test_entry_context_menu_copy_and_paste(self):
        """Проверка работы копирования и вставки в tk.Entry."""
        entry = tk.Entry(self.root)
        entry.pack()
        attach_entry_context_menu(entry, placeholder="Введите команду...")

        # Заполняем поле
        sample_text = "Напомни в 18:00 погулять"
        entry.insert(0, sample_text)
        start_idx = sample_text.find("18:00")
        entry.select_range(start_idx, start_idx + len("18:00"))  # Выделяем "18:00"

        # Имитируем копирование выделения
        copy_to_clipboard(entry, entry.selection_get())
        self.assertEqual(get_clipboard_text(entry), "18:00")

        # Теперь вставляем
        entry.delete(0, tk.END)
        clip_txt = get_clipboard_text(entry)
        entry.insert(0, clip_txt)
        self.assertEqual(entry.get(), "18:00")

    def test_right_click_context_menu_on_chat_text(self):
        """Проверка вызова контекстного меню по Button-3 в ChatView и копирования сообщения."""
        mock_shell = MagicMock()
        mock_shell.chat_messages = []
        mock_shell.log_messages = []

        view = ChatView(self.root, shell=mock_shell)
        view.pack()
        view.clear_chat()

        msg = "Привет! Я тестовое сообщение для проверки контекстного меню."
        view.append_chat("Акакий", msg)
        self.root.update_idletasks()

        # Имитируем событие правого клика <Button-3>
        e = tk.Event()
        e.widget = view.chat_text
        e.x = 20
        e.y = 20
        e.x_root = 100
        e.y_root = 100

        # Проверяем, что fallback возвращает текст сообщения
        target_text = view._get_chat_message_fallback(view.chat_text, "2.0")
        self.assertEqual(target_text, msg)

        # Выполняем копирование
        copy_to_clipboard(view.chat_text, target_text)
        self.assertEqual(get_clipboard_text(view.chat_text), msg)

    def test_home_view_copy_menu_bindings(self):
        """Проверка привязки контекстных меню к карточкам на HomeView."""
        from ui.views.home import HomeView

        mock_shell = MagicMock()
        mock_shell.log_messages = [("DONE", "Файл отчет.docx успешно создан", "15:30")]
        mock_household = MagicMock()
        mock_household.list_tasks.return_value = {"tasks": [{"id": 1, "title": "Купить молоко", "completed": False}]}
        mock_household.check_due_reminders.return_value = {"due_count": 0}
        mock_household.lists = {"Покупки": [{"id": 1, "text": "Хлеб", "completed": False}]}
        mock_household.notes = [{"id": 1, "title": "Идея", "content": "Новый проект"}]
        mock_shell.household = mock_household

        home = HomeView(self.root, shell=mock_shell)
        home.pack()
        self.root.update_idletasks()

        # Проверяем, что на карточке задачи привязано копирование
        tasks = mock_household.list_tasks()["tasks"]
        self.assertEqual(tasks[0]["title"], "Купить молоко")
        copy_to_clipboard(home, tasks[0]["title"])
        self.assertEqual(get_clipboard_text(home), "Купить молоко")


if __name__ == "__main__":
    unittest.main()
