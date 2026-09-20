"""
Модульный экран долговременной памяти (MemoryView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any

from ui.views.base import BaseView, _bind_hover


class MemoryView(BaseView):
    """
    Экран управления долговременной памятью (Memory).
    Обеспечивает сохранение фактов, просмотр всех записей и удаление фактов (забывание).
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_mem: tk.Entry = None
        self.mem_list_frame: tk.Frame = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса управления долговременной памятью."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="ДОЛГОВРЕМЕННАЯ ПАМЯТЬ (MEMORY)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        # Форма добавления факта
        add_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(
            add_box,
            text="Запомнить факт:",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=12)

        self.entry_mem = tk.Entry(
            add_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_mem.pack(side="left", fill="x", expand=True, padx=6, pady=8)
        self.entry_mem.bind("<Return>", lambda e: self.ui_remember())

        btn_add = tk.Button(
            add_box,
            text="Запомнить",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_CYAN,
            fg="#0d1117",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_remember
        )
        btn_add.pack(side="left", padx=12)
        _bind_hover(btn_add, self.ACCENT_CYAN, "#7dd3fc", "#0d1117", "#0d1117")

        # Контейнер списка памяти
        self.mem_list_frame = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        self.mem_list_frame.pack(fill="both", expand=True)

        self.refresh()

    def ui_remember(self) -> None:
        """Сохранение нового факта из поля ввода."""
        if not self.entry_mem:
            return
        txt = self.entry_mem.get().strip()
        if txt and self.memory:
            ok, msg, _ = self.memory.remember(txt)
            if not ok:
                messagebox.showwarning("Память", msg)
            self.entry_mem.delete(0, tk.END)
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление списка фактов памяти."""
        if not self.mem_list_frame or not self.mem_list_frame.winfo_exists():
            return

        for w in self.mem_list_frame.winfo_children():
            w.destroy()

        if not self.memory:
            tk.Label(
                self.mem_list_frame,
                text="Сервис памяти недоступен.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        memories = self.memory.get_all()
        if not memories:
            tk.Label(
                self.mem_list_frame,
                text="Долговременная память пуста.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        for m in reversed(memories):
            row = tk.Frame(self.mem_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            tk.Label(
                row,
                text="🧠",
                font=("Segoe UI", 10),
                fg=self.ACCENT_CYAN,
                bg="#13171f"
            ).pack(side="left", padx=10, pady=8)

            tk.Label(
                row,
                text=f"#{m['id']} {m['text']}",
                font=("Segoe UI", 9),
                fg=self.FG_WHITE,
                bg="#13171f"
            ).pack(side="left", padx=4)

            btn_del = tk.Button(
                row,
                text="✕",
                font=("Segoe UI", 8),
                fg=self.ACCENT_RED,
                bg="#13171f",
                bd=0,
                cursor="hand2",
                command=lambda mid=m["id"]: self.ui_forget(mid)
            )
            btn_del.pack(side="right", padx=8)

            tk.Label(
                row,
                text=m.get("created_at", ""),
                font=("Consolas", 8),
                fg=self.FG_DIM,
                bg="#13171f"
            ).pack(side="right", padx=8)

    def ui_forget(self, mem_id: int) -> None:
        """Удаление факта из памяти с запросом подтверждения."""
        if not self.memory:
            return
        if messagebox.askyesno("Подтверждение", f"Забыть запись #{mem_id}?"):
            self.memory.forget(mem_id)
            self.refresh()
