"""
Модульный экран управления напоминаниями (RemindersView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Any

from ui.views.base import BaseView, _bind_hover


class RemindersView(BaseView):
    """
    Экран управления напоминаниями (Reminders).
    Обеспечивает создание, просмотр, проверку наступивших и удаление напоминаний.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.entry_rem_text: tk.Entry = None
        self.entry_rem_time: tk.Entry = None
        self.rems_list_frame: tk.Frame = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса управления напоминаниями."""
        for w in self.winfo_children():
            w.destroy()

        header_row = tk.Frame(self, bg=self.BG_MAIN)
        header_row.pack(fill="x", pady=(0, 16))

        tk.Label(
            header_row,
            text="НАПОМИНАНИЯ (REMINDERS)",
            font=("Segoe UI", 14, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_MAIN
        ).pack(side="left")

        btn_check = tk.Button(
            header_row,
            text="🔔 Проверить наступившие",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_PURPLE,
            fg=self.FG_WHITE,
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.ui_check_reminders
        )
        btn_check.pack(side="right")
        _bind_hover(btn_check, self.ACCENT_PURPLE, "#b78bf9")

        # Форма добавления
        add_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        add_box.pack(fill="x", pady=(0, 16), ipady=4)

        tk.Label(
            add_box,
            text="О чём напомнить:",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=12)

        self.entry_rem_text = tk.Entry(
            add_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid"
        )
        self.entry_rem_text.pack(side="left", fill="x", expand=True, padx=6, pady=8)

        tk.Label(
            add_box,
            text="Время (19:00 / каждый день в 10:00 / каждые 2 ч):",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(side="left", padx=12)

        self.entry_rem_time = tk.Entry(
            add_box,
            font=("Segoe UI", 10),
            bg="#13171f",
            fg=self.FG_WHITE,
            bd=1,
            relief="solid",
            width=22
        )
        self.entry_rem_time.pack(side="left", padx=6, pady=8)

        btn_add = tk.Button(
            add_box,
            text="Установить",
            font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT_PURPLE,
            fg=self.FG_WHITE,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.ui_create_reminder
        )
        btn_add.pack(side="left", padx=12)
        _bind_hover(btn_add, self.ACCENT_PURPLE, "#b78bf9")

        # Контейнер списка
        self.rems_list_frame = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        self.rems_list_frame.pack(fill="both", expand=True)

        self.refresh()

    def ui_create_reminder(self) -> None:
        """Создание нового напоминания."""
        if not self.entry_rem_text or not self.entry_rem_time:
            return
        txt = self.entry_rem_text.get().strip()
        tm = self.entry_rem_time.get().strip()
        if txt and tm and self.household:
            self.household.create_reminder(txt, tm)
            self.entry_rem_text.delete(0, tk.END)
            self.entry_rem_time.delete(0, tk.END)
            self.refresh()

    def ui_check_reminders(self) -> None:
        """Проверка наступивших напоминаний."""
        if self.household:
            res = self.household.check_due_reminders()
            messagebox.showinfo("Напоминания", res["message"])
            self.refresh()

    def refresh(self) -> None:
        """Реактивное обновление списка напоминаний."""
        if not self.rems_list_frame or not self.rems_list_frame.winfo_exists():
            return

        for w in self.rems_list_frame.winfo_children():
            w.destroy()

        if not self.household:
            tk.Label(
                self.rems_list_frame,
                text="Сервис напоминаний недоступен.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        rems = self.household.list_reminders(include_triggered=True)["reminders"]
        if not rems:
            tk.Label(
                self.rems_list_frame,
                text="Напоминаний нет.",
                font=("Segoe UI", 11),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(pady=40)
            return

        from tools.datetime_utils import format_repeat_rule

        for r in reversed(rems):
            row = tk.Frame(self.rems_list_frame, bg="#13171f", bd=1, relief="solid")
            row.pack(fill="x", padx=16, pady=4)

            icon = "🔔" if not r.get("triggered") else "✔"
            tk.Label(
                row,
                text=icon,
                font=("Segoe UI", 11),
                fg=self.ACCENT_PURPLE,
                bg="#13171f"
            ).pack(side="left", padx=12, pady=8)

            tk.Label(
                row,
                text=f"#{r['id']} {r['text']}",
                font=("Segoe UI", 10),
                fg=self.FG_WHITE,
                bg="#13171f"
            ).pack(side="left", padx=4)

            repeat_val = r.get("repeat")
            if repeat_val:
                rep_text = format_repeat_rule(repeat_val)
                tk.Label(
                    row,
                    text=f"🔁 {rep_text}",
                    font=("Segoe UI", 9, "italic"),
                    fg="#a78bfa",
                    bg="#13171f"
                ).pack(side="left", padx=8)

            btn_del = tk.Button(
                row,
                text="✕",
                font=("Segoe UI", 9),
                fg=self.ACCENT_RED,
                bg="#13171f",
                bd=0,
                cursor="hand2",
                command=lambda rid=r["id"]: self.ui_delete_reminder(rid)
            )
            btn_del.pack(side="right", padx=8)

            btn_done = tk.Button(
                row,
                text="✓",
                font=("Segoe UI", 9, "bold"),
                fg=self.ACCENT_GREEN,
                bg="#13171f",
                bd=0,
                cursor="hand2",
                command=lambda rid=r["id"]: self.ui_complete_reminder(rid)
            )
            btn_done.pack(side="right", padx=4)

            tk.Label(
                row,
                text=f"Время: {r['remind_at']}",
                font=("Consolas", 9),
                fg=self.ACCENT_CYAN,
                bg="#13171f"
            ).pack(side="right", padx=12)

    def ui_complete_reminder(self, reminder_id: Any) -> None:
        """Отметка выполнения напоминания."""
        if self.household:
            self.household.complete_reminder(reminder_id)
            self.refresh()

    def ui_delete_reminder(self, reminder_id: Any) -> None:
        """Удаление напоминания с подтверждением пользователя."""
        if messagebox.askyesno("Подтверждение", f"Удалить напоминание #{reminder_id}?"):
            if self.household:
                self.household.delete_reminder(reminder_id)
                self.refresh()

