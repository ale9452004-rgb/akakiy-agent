"""
Модульный экран управления заметками (NotesView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any

from ui.views.base import BaseView, _bind_hover


class NotesView(BaseView):
    """
    Экран управления заметками (Notes).
    Обеспечивает создание, текстовый поиск, просмотр и удаление заметок.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_note_search: tk.Entry = None
        self.entry_note_title: tk.Entry = None
        self.entry_note_content: tk.Entry = None
        self.notes_list_frame: tk.Frame = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса управления заметками."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="ЗАМЕТКИ (NOTES)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        # Поиск заметок
        search_box = tk.Frame(header_row, bg=self.BG_MAIN)
        search_box.pack(side="right")

        tk.Label(
            search_box,
            text="Поиск:",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_MAIN
        ).pack(side="left", padx=4)

        self.entry_note_search = tk.Entry(
            search_box,
            font=("Segoe UI", 10),
            bg=self.BG_CARD,
            fg=self.FG_WHITE,
            width=20,
            bd=1,
            relief="solid"
        )
        self.entry_note_search.pack(side="left", padx=4)
        self.entry_note_search.bind("<KeyRelease>", lambda e: self.refresh())

        # Форма создания
        create_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        create_box.pack(fill="x", pady=(0, 16), padx=0)

        tk.Label(
            create_box,
            text="Заголовок:",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(10, 2))

        self.entry_note_title = tk.Entry(
            create_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_note_title.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(
            create_box,
            text="Текст заметки:",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(4, 2))

        self.entry_note_content = tk.Entry(
            create_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_note_content.pack(fill="x", padx=16, pady=(0, 10))

        btn_save = tk.Button(
            create_box,
            text="Сохранить заметку",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_CYAN,
            fg="#0d1117",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_create_note
        )
        btn_save.pack(anchor="e", padx=16, pady=(0, 12))
        _bind_hover(btn_save, self.ACCENT_CYAN, "#7dd3fc", "#0d1117", "#0d1117")

        # Контейнер плиток
        self.notes_list_frame = tk.Frame(self, bg=self.BG_MAIN)
        self.notes_list_frame.pack(fill="both", expand=True)

        self.refresh()

    def ui_create_note(self) -> None:
        """Создание новой заметки из полей ввода."""
        if not self.entry_note_title or not self.entry_note_content:
            return
        title = self.entry_note_title.get().strip()
        content = self.entry_note_content.get().strip()
        if (title or content) and self.household:
            self.household.create_note(title, content)
            self.entry_note_title.delete(0, tk.END)
            self.entry_note_content.delete(0, tk.END)
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление списка заметок."""
        if not self.notes_list_frame or not self.notes_list_frame.winfo_exists():
            return

        for w in self.notes_list_frame.winfo_children():
            w.destroy()

        if not self.household:
            tk.Label(
                self.notes_list_frame,
                text="Сервис заметок недоступен.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_MAIN
            ).pack(pady=30)
            return

        query = self.entry_note_search.get().strip() if self.entry_note_search else ""
        if query:
            notes = self.household.search_notes(query)["notes"]
        else:
            notes = self.household.list_notes()["notes"]

        if not notes:
            tk.Label(
                self.notes_list_frame,
                text="Заметок не найдено.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_MAIN
            ).pack(pady=30)
            return

        for n in reversed(notes):
            card = tk.Frame(self.notes_list_frame, bg=self.BG_CARD, bd=1, relief="solid")
            card.pack(fill="x", pady=4)

            top_line = tk.Frame(card, bg=self.BG_CARD)
            top_line.pack(fill="x", padx=14, pady=(10, 4))

            tk.Label(
                top_line,
                text=f"#{n['id']} {n['title']}",
                font=("Segoe UI", 10, "bold"),
                fg=self.FG_WHITE,
                bg=self.BG_CARD
            ).pack(side="left")

            tk.Label(
                top_line,
                text=n.get("created_at", ""),
                font=("Consolas", 8),
                fg=self.FG_DIM,
                bg=self.BG_CARD
            ).pack(side="right", padx=8)

            btn_del = tk.Button(
                top_line,
                text="✕",
                font=("Segoe UI", 9),
                fg=self.ACCENT_RED,
                bg=self.BG_CARD,
                bd=0,
                cursor="hand2",
                command=lambda nid=n["id"]: self.ui_delete_note(nid)
            )
            btn_del.pack(side="right")

            tk.Label(
                card,
                text=n.get("content", ""),
                font=("Segoe UI", 9),
                fg=self.FG_MAIN,
                bg=self.BG_CARD,
                justify="left",
                wraplength=800
            ).pack(anchor="w", padx=14, pady=(0, 12))

    def ui_delete_note(self, note_id: Any) -> None:
        """Удаление заметки с подтверждением пользователя."""
        if messagebox.askyesno("Подтверждение", f"Удалить заметку #{note_id}?"):
            if self.household:
                self.household.delete_note(note_id)
                self.refresh()
