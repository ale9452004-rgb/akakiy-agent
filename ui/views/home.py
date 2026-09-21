"""
Модульный главный экран дашборда (HomeView) для Desktop Hub Акакия 2.0.
"""

import tkinter as tk
from typing import Any

from ui.neural_core import NeuralCore
from ui.views.base import BaseView


class HomeView(BaseView):
    """
    Главный экран рабочего пространства (Dashboard Hub).
    Отображает приветствие, сводку «Сегодня», 3D Neural Core, быстрые карточки
    активных задач, напоминаний, списков и последних заметок.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.neural_core: NeuralCore = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса главного дашборда."""
        for w in self.winfo_children():
            w.destroy()

        # Верхний ряд: Приветствие + блок Сегодня + Neural Core
        top_row = tk.Frame(self, bg=self.BG_MAIN)
        top_row.pack(fill="x", pady=(0, 20))

        # Левая часть верхнего ряда: приветствие и «Сегодня»
        welcome_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid")
        welcome_box.pack(side="left", fill="both", expand=True, padx=(0, 20))

        tk.Label(
            welcome_box,
            text="ДОБРО ПОЖАЛОВАТЬ В АКАКИЙ 2.0",
            font=("Segoe UI", 15, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(20, 4))

        tk.Label(
            welcome_box,
            text="Ваш персональный автономный ИИ-хаб и бытовой ассистент.",
            font=("Segoe UI", 10),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(0, 16))

        # Внутренний блок «Сегодня»
        today_box = tk.Frame(welcome_box, bg="#13171f", bd=1, relief="solid")
        today_box.pack(fill="x", padx=24, pady=(0, 20))

        today_header = tk.Frame(today_box, bg="#13171f")
        today_header.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            today_header,
            text="📅  СВОДКА «СЕГОДНЯ»",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_CYAN,
            bg="#13171f"
        ).pack(side="left")

        btn_brief = tk.Button(
            today_header,
            text="⚡ Сводка дня",
            font=("Segoe UI", 8, "bold"),
            bg="#1f242c",
            fg=self.ACCENT_AMBER,
            activebackground="#2a323d",
            activeforeground="#fff",
            bd=1,
            relief="solid",
            cursor="hand2",
            padx=8,
            pady=2,
            command=self.ui_show_daily_briefing
        )
        btn_brief.pack(side="right")
        self.bind_hover(btn_brief, "#1f242c", "#2a323d")

        pending_tasks = len(self.household.list_tasks(status="pending")["tasks"]) if self.household else 0
        due_reminders = self.household.check_due_reminders()["due_count"] if self.household else 0
        total_lists = len(self.household.lists) if self.household and hasattr(self.household, "lists") else 0

        info_text = (
            f"• Активных задач: {pending_tasks}\n"
            f"• Наступивших/ближайших напоминаний: {due_reminders}\n"
            f"• Именованных списков дел: {total_lists}"
        )
        tk.Label(
            today_box,
            text=info_text,
            font=("Segoe UI", 10),
            fg=self.FG_MAIN,
            bg="#13171f",
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # Правая часть верхнего ряда: NEURAL CORE
        core_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid", width=260)
        core_box.pack(side="right", fill="y")
        core_box.pack_propagate(False)

        tk.Label(
            core_box,
            text="NEURAL CORE",
            font=("Segoe UI", 9, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(pady=(12, 4))

        self.neural_core = NeuralCore(core_box, size=180, bg=self.BG_CARD)
        self.neural_core.pack(pady=4)

        if self.shell:
            self.shell.neural_core = self.neural_core
            cur_state = getattr(self.shell, "current_state", "idle")
            self.neural_core.set_state(cur_state)

        # Средний ряд: 3 интерактивные карточки (Задачи / Напоминания / Списки)
        mid_row = tk.Frame(self, bg=self.BG_MAIN)
        mid_row.pack(fill="x", pady=(0, 20))

        # Карточка 1: Задачи
        card_t = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_t.pack(side="left", fill="both", expand=True, padx=(0, 14))

        tk.Label(
            card_t,
            text="✓  ЗАДАЧИ",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        tasks = self.household.list_tasks(status="pending")["tasks"][:3] if self.household else []
        if not tasks:
            tk.Label(
                card_t,
                text="Нет активных задач.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=4)
        else:
            for t in tasks:
                t_row = tk.Frame(card_t, bg=self.BG_CARD)
                t_row.pack(fill="x", padx=16, pady=2)
                chk = tk.Button(
                    t_row,
                    text="☐",
                    font=("Segoe UI", 10),
                    bg=self.BG_CARD,
                    fg=self.FG_MUTED,
                    bd=0,
                    cursor="hand2",
                    command=lambda tid=t["id"]: self.quick_complete_task(tid)
                )
                chk.pack(side="left")
                lbl = t["title"] if len(t["title"]) <= 28 else t["title"][:25] + "..."
                tk.Label(
                    t_row,
                    text=lbl,
                    font=("Segoe UI", 9),
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(side="left", padx=4)

        btn_all_t = tk.Button(
            card_t,
            text="Все задачи →",
            font=("Segoe UI", 8, "bold"),
            fg=self.ACCENT_BLUE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("tasks")
        )
        btn_all_t.pack(anchor="w", padx=16, pady=(10, 12))

        # Карточка 2: Напоминания
        card_r = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_r.pack(side="left", fill="both", expand=True, padx=(0, 14))

        tk.Label(
            card_r,
            text="🔔  НАПОМИНАНИЯ",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        rems_dict = self.household.list_reminders() if self.household and hasattr(self.household, "list_reminders") else {}
        rems = rems_dict.get("reminders", [])[:3] if isinstance(rems_dict, dict) else []
        if not rems:
            tk.Label(
                card_r,
                text="Напоминаний нет.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=4)
        else:
            for r in rems:
                r_lbl = f"• {r['text'][:22]} ({r['remind_at']})"
                tk.Label(
                    card_r,
                    text=r_lbl,
                    font=("Segoe UI", 9),
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(anchor="w", padx=16, pady=2)

        btn_all_r = tk.Button(
            card_r,
            text="Все напоминания →",
            font=("Segoe UI", 8, "bold"),
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("reminders")
        )
        btn_all_r.pack(anchor="w", padx=16, pady=(10, 12))

        # Карточка 3: Списки
        card_l = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_l.pack(side="left", fill="both", expand=True)

        tk.Label(
            card_l,
            text="📋  СПИСКИ",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(14, 8))

        lists_keys = list(self.household.lists.keys())[:3] if self.household and hasattr(self.household, "lists") else []
        if not lists_keys:
            tk.Label(
                card_l,
                text="Списков пока нет.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=4)
        else:
            for l_name in lists_keys:
                cnt = len(self.household.lists[l_name])
                tk.Label(
                    card_l,
                    text=f"• {l_name} ({cnt} эл.)",
                    font=("Segoe UI", 9),
                    fg=self.FG_MAIN,
                    bg=self.BG_CARD
                ).pack(anchor="w", padx=16, pady=2)

        btn_all_l = tk.Button(
            card_l,
            text="Все списки →",
            font=("Segoe UI", 8, "bold"),
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("lists")
        )
        btn_all_l.pack(anchor="w", padx=16, pady=(10, 12))

        # Нижний ряд: Последние заметки
        notes_box = tk.Frame(self, bg=self.BG_CARD, bd=1, relief="solid")
        notes_box.pack(fill="both", expand=True)

        tk.Label(
            notes_box,
            text="📝  ПОСЛЕДНИЕ ЗАМЕТКИ",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=20, pady=(14, 8))

        notes = self.household.notes[-3:] if self.household and self.household.notes else []
        if not notes:
            tk.Label(
                notes_box,
                text="Заметок пока нет. Создайте первую заметку через раздел Заметки или команду внизу.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=20, pady=6)
        else:
            n_row = tk.Frame(notes_box, bg=self.BG_CARD)
            n_row.pack(fill="both", expand=True, padx=20, pady=(0, 14))
            for n in notes:
                item_card = tk.Frame(n_row, bg="#13171f", bd=1, relief="solid")
                item_card.pack(side="left", fill="both", expand=True, padx=6)
                tk.Label(
                    item_card,
                    text=n["title"],
                    font=("Segoe UI", 10, "bold"),
                    fg=self.FG_WHITE,
                    bg="#13171f"
                ).pack(anchor="w", padx=12, pady=(10, 4))
                c_prev = n["content"][:80] + ("..." if len(n["content"]) > 80 else "")
                tk.Label(
                    item_card,
                    text=c_prev,
                    font=("Segoe UI", 9),
                    fg=self.FG_MUTED,
                    bg="#13171f",
                    justify="left",
                    wraplength=280
                ).pack(anchor="w", padx=12, pady=(0, 10))

    def quick_complete_task(self, task_id: int) -> None:
        """Быстрое завершение задачи из сводки главной страницы."""
        if self.household:
            self.household.complete_task(task_id)
        self.refresh()

    def ui_show_daily_briefing(self) -> None:
        """Отображает структурированную сводку дня в окне и озвучивает, если активен голос."""
        from tkinter import messagebox
        from tools.daily_briefing import get_daily_briefing

        briefing = get_daily_briefing(self.household)
        text = briefing.get("text", "")

        # Безопасная озвучка, если VoiceService инициализирован и активен
        if self.voice and hasattr(self.voice, "speak_phrase") and getattr(self.voice, "is_running", False):
            try:
                self.voice.speak_phrase(text)
            except Exception:
                pass

        messagebox.showinfo("⚡ Сводка дня", text)

    def refresh(self) -> None:
        """Реактивное обновление дашборда."""
        self.render()
