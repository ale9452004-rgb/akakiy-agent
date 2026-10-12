"""
Модуль поддержки буфера обмена и контекстных меню (Clipboard & Context Menu) для Desktop Hub Акакия.

Обеспечивает:
1. Безопасное копирование текста в системный буфер обмена Windows (copy_to_clipboard).
2. Стилизованные контекстные меню по правому клику в теме Visual Direction 2.0.
3. Обработку выделения мышью, Ctrl+C (включая русскую раскладку) и контекстного меню для tk.Text:
   - При наличии выделения: копирует выделенный фрагмент;
   - При отсутствии выделения: копирует текст сообщения или строки целиком.
4. Контекстные меню для полей ввода (tk.Entry) и текстовых карточек/меток (tk.Label).
"""

import re
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ui.typography import typography


# Цветовая палитра контекстных меню (Visual Direction 2.0)
MENU_BG = "#0c111c"
MENU_FG = "#cbd5e1"
MENU_ACTIVE_BG = "#0284c7"
MENU_ACTIVE_FG = "#ffffff"
MENU_DISABLED_FG = "#475569"
MENU_BORDER = "#1e293b"


def copy_to_clipboard(widget: tk.Widget, text: str) -> bool:
    """
    Безопасное копирование строки в системный буфер обмена ОС через Tkinter.
    Возвращает True при успешном копировании, иначе False.
    """
    if text is None:
        return False
    try:
        if not widget or not widget.winfo_exists():
            return False
        widget.clipboard_clear()
        widget.clipboard_append(text)
        try:
            widget.update_idletasks()
        except Exception:
            pass
        return True
    except Exception:
        return False


def get_clipboard_text(widget: tk.Widget) -> str:
    """Безопасное чтение текста из системного буфера обмена."""
    try:
        if not widget or not widget.winfo_exists():
            return ""
        return widget.clipboard_get() or ""
    except Exception:
        return ""


def create_context_menu(
    master: tk.Widget,
    items: List[Tuple[str, Optional[Callable[[], None]], bool]],
    bg: str = MENU_BG,
    fg: str = MENU_FG,
    active_bg: str = MENU_ACTIVE_BG,
    active_fg: str = MENU_ACTIVE_FG,
    font: Any = ("Segoe UI", 9)
) -> tk.Menu:
    """
    Создание всплывающего контекстного меню Tkinter в едином визуальном стиле Акакия.
    Каждый элемент в items: (label, command, is_enabled).
    Если label == "---", вставляется разделитель.
    """
    menu = tk.Menu(
        master,
        tearoff=0,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=active_fg,
        disabledforeground=MENU_DISABLED_FG,
        activeborderwidth=0,
        bd=1,
        relief="solid",
        font=font
    )
    for label, cmd, is_enabled in items:
        if label == "---":
            menu.add_separator(background=bg)
        else:
            state = "normal" if is_enabled else "disabled"
            menu.add_command(label=label, command=cmd, state=state)
    return menu


def show_context_menu(menu: tk.Menu, event: tk.Event) -> None:
    """Безопасное отображение всплывающего меню с корректным освобождением захвата (grab)."""
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        try:
            menu.grab_release()
        except Exception:
            pass


def is_copy_shortcut(event: tk.Event) -> bool:
    """Проверка, соответствует ли нажатие комбинации Ctrl+C (с учётом русской раскладки)."""
    ctrl_pressed = bool(getattr(event, "state", 0) & 4)
    if not ctrl_pressed:
        return False
    keysym = getattr(event, "keysym", "")
    keycode = getattr(event, "keycode", 0)
    char = getattr(event, "char", "")
    # На Windows keycode 67 = клавиша C
    return (
        keysym in ("c", "C", "Cyrillic_es", "Cyrillic_ES")
        or keycode == 67
        or char == "\x03"
    )


def is_select_all_shortcut(event: tk.Event) -> bool:
    """Проверка, соответствует ли нажатие комбинации Ctrl+A (с учётом русской раскладки)."""
    ctrl_pressed = bool(getattr(event, "state", 0) & 4)
    if not ctrl_pressed:
        return False
    keysym = getattr(event, "keysym", "")
    keycode = getattr(event, "keycode", 0)
    char = getattr(event, "char", "")
    # На Windows keycode 65 = клавиша A
    return (
        keysym in ("a", "A", "Cyrillic_ef", "Cyrillic_EF")
        or keycode == 65
        or char == "\x01"
    )


def is_paste_shortcut(event: tk.Event) -> bool:
    """Проверка, соответствует ли нажатие комбинации Ctrl+V (с учётом русской раскладки)."""
    ctrl_pressed = bool(getattr(event, "state", 0) & 4)
    if not ctrl_pressed:
        return False
    keysym = getattr(event, "keysym", "")
    keycode = getattr(event, "keycode", 0)
    char = getattr(event, "char", "")
    # На Windows keycode 86 = клавиша V
    return (
        keysym in ("v", "V", "Cyrillic_em", "Cyrillic_EM")
        or keycode == 86
        or char == "\x16"
    )


def is_cut_shortcut(event: tk.Event) -> bool:
    """Проверка, соответствует ли нажатие комбинации Ctrl+X (с учётом русской раскладки)."""
    ctrl_pressed = bool(getattr(event, "state", 0) & 4)
    if not ctrl_pressed:
        return False
    keysym = getattr(event, "keysym", "")
    keycode = getattr(event, "keycode", 0)
    char = getattr(event, "char", "")
    # На Windows keycode 88 = клавиша X
    return (
        keysym in ("x", "X", "Cyrillic_che", "Cyrillic_CHE")
        or keycode == 88
        or char == "\x18"
    )


def attach_text_copy_handler(
    text_widget: tk.Text,
    get_message_fallback: Optional[Callable[[tk.Text, str], str]] = None
) -> None:
    """
    Привязка обработчиков копирования, выделения и контекстного меню к tk.Text:
    - Настройка цветов выделения (Visual Direction 2.0);
    - Поддержка Ctrl+C: копирование выделения, либо всего сообщения/строки под курсором;
    - Поддержка Ctrl+A: выделение всего текста;
    - Правый клик: контекстное меню («Копировать», «Выделить всё»).
    """
    try:
        text_widget.config(
            selectbackground="#1e3a5f",
            selectforeground="#ffffff",
            inactiveselectbackground="#14283f"
        )
    except Exception:
        pass

    def perform_copy_at_index(target_index: str) -> None:
        """Логика копирования: выделение, либо fallback (целое сообщение / строка)."""
        sel_ranges = text_widget.tag_ranges("sel")
        if sel_ranges:
            text_to_copy = text_widget.get(sel_ranges[0], sel_ranges[1])
            if text_to_copy:
                copy_to_clipboard(text_widget, text_to_copy)
                return

        # Если выделения нет — берём текст сообщения / строки целиком
        text_to_copy = ""
        if get_message_fallback:
            try:
                text_to_copy = get_message_fallback(text_widget, target_index) or ""
            except Exception:
                text_to_copy = ""

        if not text_to_copy:
            # Универсальный fallback: берём строку под курсором
            try:
                line_idx = str(target_index).split(".")[0]
                text_to_copy = text_widget.get(f"{line_idx}.0", f"{line_idx}.end").strip()
            except Exception:
                text_to_copy = ""

        if text_to_copy:
            copy_to_clipboard(text_widget, text_to_copy)

    def on_copy_key(event: tk.Event) -> str:
        """Обработка клавиш Ctrl+C (включая русскую раскладку и virtual <<Copy>>)."""
        sel_ranges = text_widget.tag_ranges("sel")
        if sel_ranges:
            text_to_copy = text_widget.get(sel_ranges[0], sel_ranges[1])
            if text_to_copy:
                copy_to_clipboard(text_widget, text_to_copy)
                return "break"
        else:
            # Нет выделения: копируем текущее сообщение под курсором вставки
            current_idx = text_widget.index(tk.INSERT)
            perform_copy_at_index(current_idx)
            return "break"
        return "break"

    def on_ctrl_keypress(event: tk.Event) -> Optional[str]:
        if is_copy_shortcut(event):
            return on_copy_key(event)
        if is_select_all_shortcut(event):
            text_widget.tag_add("sel", "1.0", "end-1c")
            return "break"
        return None

    def on_right_click(event: tk.Event) -> str:
        """Показ контекстного меню по правому клику мышью."""
        try:
            click_idx = text_widget.index(f"@{event.x},{event.y}")
        except Exception:
            click_idx = text_widget.index(tk.INSERT)

        sel_ranges = text_widget.tag_ranges("sel")
        if sel_ranges:
            try:
                is_inside = (
                    text_widget.compare(sel_ranges[0], "<=", click_idx)
                    and text_widget.compare(click_idx, "<=", sel_ranges[1])
                )
            except Exception:
                is_inside = False
            # Если кликнули вне выделения — снимаем старое выделение и ставим курсор
            if not is_inside:
                text_widget.tag_remove("sel", "1.0", tk.END)
                text_widget.mark_set(tk.INSERT, click_idx)

        # Вычисляем текст, который будет скопирован
        has_sel = bool(text_widget.tag_ranges("sel"))
        target_copy_text = ""
        if has_sel:
            target_copy_text = text_widget.get("sel.first", "sel.last")
        else:
            if get_message_fallback:
                try:
                    target_copy_text = get_message_fallback(text_widget, click_idx) or ""
                except Exception:
                    target_copy_text = ""
            if not target_copy_text:
                try:
                    line_idx = str(click_idx).split(".")[0]
                    target_copy_text = text_widget.get(f"{line_idx}.0", f"{line_idx}.end").strip()
                except Exception:
                    target_copy_text = ""

        can_copy = bool(target_copy_text and target_copy_text.strip())

        def do_copy():
            if target_copy_text:
                copy_to_clipboard(text_widget, target_copy_text)

        def do_select_all():
            text_widget.tag_add("sel", "1.0", "end-1c")

        menu_items = [
            ("Копировать", do_copy, can_copy),
            ("---", None, False),
            ("Выделить всё", do_select_all, True),
        ]

        menu = create_context_menu(text_widget, menu_items)
        show_context_menu(menu, event)
        return "break"

    # Привязка обработчиков
    text_widget.bind("<Button-3>", on_right_click, add="+")
    text_widget.bind("<<Copy>>", on_copy_key, add="+")
    text_widget.bind("<Control-c>", on_copy_key, add="+")
    text_widget.bind("<Control-C>", on_copy_key, add="+")
    text_widget.bind("<Control-KeyPress>", on_ctrl_keypress, add="+")


def attach_entry_context_menu(
    entry_widget: tk.Entry,
    placeholder: Optional[str] = None
) -> None:
    """
    Привязка контекстного меню («Копировать», «Вставить», «Вырезать», «Выделить всё»)
    и кросс-раскладочных горячих клавиш к tk.Entry.
    """
    def on_right_click(event: tk.Event) -> str:
        entry_widget.focus_set()
        has_sel = False
        sel_text = ""
        try:
            sel_text = entry_widget.selection_get()
            has_sel = bool(sel_text)
        except Exception:
            has_sel = False

        full_val = entry_widget.get()
        is_placeholder = bool(placeholder and full_val == placeholder)

        # Что копировать: выделение либо всё поле
        text_to_copy = sel_text if has_sel else ("" if is_placeholder else full_val)
        can_copy = bool(text_to_copy)

        # Текст в буфере обмена для вставки
        clip_content = get_clipboard_text(entry_widget)
        can_paste = bool(clip_content)

        def do_copy():
            if text_to_copy:
                copy_to_clipboard(entry_widget, text_to_copy)

        def do_cut():
            if has_sel:
                copy_to_clipboard(entry_widget, sel_text)
                try:
                    entry_widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except Exception:
                    pass
            elif not is_placeholder and full_val:
                copy_to_clipboard(entry_widget, full_val)
                entry_widget.delete(0, tk.END)

        def do_paste():
            if clip_content:
                if is_placeholder:
                    entry_widget.delete(0, tk.END)
                try:
                    if entry_widget.selection_present():
                        entry_widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except Exception:
                    pass
                entry_widget.insert(tk.INSERT, clip_content)

        def do_select_all():
            entry_widget.select_range(0, tk.END)
            entry_widget.icursor(tk.END)

        menu_items = [
            ("Копировать", do_copy, can_copy),
            ("Вставить", do_paste, can_paste),
            ("Вырезать", do_cut, can_copy),
            ("---", None, False),
            ("Выделить всё", do_select_all, bool(full_val and not is_placeholder)),
        ]

        menu = create_context_menu(entry_widget, menu_items)
        show_context_menu(menu, event)
        return "break"

    def on_ctrl_keypress(event: tk.Event) -> Optional[str]:
        # Поддержка русских горячих клавиш
        if is_select_all_shortcut(event):
            entry_widget.select_range(0, tk.END)
            entry_widget.icursor(tk.END)
            return "break"
        if is_copy_shortcut(event):
            try:
                if entry_widget.selection_present():
                    copy_to_clipboard(entry_widget, entry_widget.selection_get())
                    return "break"
            except Exception:
                pass
        if is_paste_shortcut(event):
            clip = get_clipboard_text(entry_widget)
            if clip:
                try:
                    if entry_widget.selection_present():
                        entry_widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except Exception:
                    pass
                entry_widget.insert(tk.INSERT, clip)
                return "break"
        if is_cut_shortcut(event):
            try:
                if entry_widget.selection_present():
                    copy_to_clipboard(entry_widget, entry_widget.selection_get())
                    entry_widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
                    return "break"
            except Exception:
                pass
        return None

    entry_widget.bind("<Button-3>", on_right_click, add="+")
    entry_widget.bind("<Control-KeyPress>", on_ctrl_keypress, add="+")


def attach_widget_copy_menu(
    widget: tk.Widget,
    get_text: Callable[[], str],
    label: str = "Копировать",
    extra_items: Optional[List[Tuple[str, Callable[[], None]]]] = None
) -> None:
    """
    Привязка контекстного меню по правому клику к произвольному виджету (Label, Frame, Card).
    Позволяет скопировать результат get_text() в буфер обмена.
    """
    def on_right_click(event: tk.Event) -> str:
        try:
            val = get_text() or ""
        except Exception:
            val = ""

        def do_copy():
            if val:
                copy_to_clipboard(widget, val)

        menu_items = [
            (label, do_copy, bool(val and val.strip())),
        ]

        if extra_items:
            menu_items.append(("---", None, False))
            for item_label, item_cmd in extra_items:
                menu_items.append((item_label, item_cmd, True))

        menu = create_context_menu(widget, menu_items)
        show_context_menu(menu, event)
        return "break"

    widget.bind("<Button-3>", on_right_click, add="+")
