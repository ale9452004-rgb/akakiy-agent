"""
Модульный экран управления задачами (TasksView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any

from ui.views.base import BaseView, _bind_hover


class TasksView(BaseView):
    """
    Экран управления бытовыми задачами (Tasks).
    Обеспечивает создание, просмотр, переключение статуса и удаление задач.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_task: tk.Entry = None
        self.tasks_list_frame: tk.Frame = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса управления задачами."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="УПРАВЛЕНИЕ ЗАДАЧАМИ (TASKS)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        # Форма добавления задачи
        add_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(
            add_box,
            text="Новая задача:",
            font=("Segoe UI", 10, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=16)

        self.entry_task = tk.Entry(
            add_box,
            font=("Segoe UI", 11),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_task.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self.entry_task.bind("<Return>", lambda e: self.ui_create_task())

        btn_add = tk.Button(
            add_box,
            text="Добавить",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_CYAN,
            fg="#0d1117",
            bd=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=self.ui_create_task
        )
        btn_add.pack(side="left", padx=16)
        _bind_hover(btn_add, self.ACCENT_CYAN, "#7dd3fc", "#0d1117", "#0d1117")

        # Контейнер списка задач
        self.tasks_list_frame = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        self.tasks_list_frame.pack(fill="both", expand=True)

        self.refresh()

    def ui_create_task(self) -> None:
        """Создание новой задачи из поля ввода."""
        if not self.entry_task:
            return
        txt = self.entry_task.get().strip()
        if txt and self.household:
            self.household.create_task(txt)
            self.entry_task.delete(0, tk.END)
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление списка задач."""
        if not self.tasks_list_frame or not self.tasks_list_frame.winfo_exists():
            return

        for w in self.tasks_list_frame.winfo_children():
            w.destroy()

        if not self.household:
            tk.Label(
                self.tasks_list_frame,
                text="Сервис задач недоступен.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        tasks = self.household.list_tasks(status="all")["tasks"]
        if not tasks:
            tk.Label(
                self.tasks_list_frame,
                text="Задач пока нет.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        for t in reversed(tasks):
            row = tk.Frame(self.tasks_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            # Чекбокс
            is_done = t.get("completed", False)
            btn_txt = "☑" if is_done else "☐"
            btn_color = self.ACCENT_GREEN if is_done else self.FG_MUTED

            chk = tk.Button(
                row,
                text=btn_txt,
                font=("Segoe UI", 12),
                fg=btn_color,
                bg="#13171f",
                bd=0,
                cursor="hand2",
                command=lambda tid=t["id"]: self.ui_toggle_task(tid)
            )
            chk.pack(side="left", padx=12, pady=8)

            t_fg = self.FG_MUTED if is_done else self.FG_WHITE
            tk.Label(
                row,
                text=f"#{t['id']} {t['title']}",
                font=("Segoe UI", 10),
                fg=t_fg,
                bg="#13171f"
            ).pack(side="left", padx=4)

            # Дата
            tk.Label(
                row,
                text=t.get("created_at", ""),
                font=("Consolas", 8),
                fg=self.FG_DIM,
                bg="#13171f"
            ).pack(side="right", padx=12)

            # Кнопка удаления
            btn_del = tk.Button(
                row,
                text="✕",
                font=("Segoe UI", 9),
                fg=self.ACCENT_RED,
                bg="#13171f",
                bd=0,
                cursor="hand2",
                command=lambda tid=t["id"]: self.ui_delete_task(tid)
            )
            btn_del.pack(side="right", padx=8)

    def ui_toggle_task(self, task_id: Any) -> None:
        """Отметка задачи как выполненной."""
        if self.household:
            self.household.complete_task(task_id)
            self.refresh()

    def ui_delete_task(self, task_id: Any) -> None:
        """Удаление задачи с подтверждением пользователя."""
        if messagebox.askyesno("Подтверждение", f"Удалить задачу #{task_id}?"):
            if self.household:
                self.household.delete_task(task_id)
                self.refresh()
