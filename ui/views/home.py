"""
Модульный главный экран дашборда (HomeView) для Desktop Hub Акакия 2.0.
"""

from pathlib import Path
import tkinter as tk
from typing import Any

from ui.neural_core import NeuralCore
from ui.views.base import BaseView


class HomeView(BaseView):
    """
    Главный экран рабочего пространства (Dashboard Hub).
    Отображает:
    1. Состояние дня: сводка «Сегодня», 3D Neural Core, счётчики дел.
    2. Быстрые карточки: активные задачи, ближайшие события и напоминания, списки.
    3. Активность и рабочие результаты Акакия: действия Agent/Sub-Agents/Planner/Executor/Tools.
    4. Последние сохранённые заметки.
    """

    def __init__(self, master: tk.Widget, shell: Any = None, **kwargs):
        super().__init__(master, shell=shell, **kwargs)
        self.neural_core: NeuralCore = None
        self.render()

    def render(self) -> None:
        """Построение интерфейса главного дашборда Desktop Hub."""
        for w in self.winfo_children():
            w.destroy()

        # -------------------------------------------------------------
        # 1. Верхний ряд: Приветствие + Сводка «Сегодня» + Neural Core
        # -------------------------------------------------------------
        top_row = tk.Frame(self, bg=self.BG_MAIN)
        top_row.pack(fill="x", pady=(0, 16))

        # Левая часть верхнего ряда: приветствие и «Сегодня»
        welcome_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid")
        welcome_box.pack(side="left", fill="both", expand=True, padx=(0, 16))

        tk.Label(
            welcome_box,
            text="ДОБРО ПОЖАЛОВАТЬ В АКАКИЙ 2.0",
            font=("Segoe UI", 15, "bold"),
            fg=self.FG_WHITE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(16, 2))

        tk.Label(
            welcome_box,
            text="Персональный автономный ИИ-хаб и рабочий центр задач, заметок и проектов.",
            font=("Segoe UI", 9),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=24, pady=(0, 12))

        # Внутренний блок «Сегодня» (Day State)
        today_box = tk.Frame(welcome_box, bg="#13171f", bd=1, relief="solid")
        today_box.pack(fill="x", padx=24, pady=(0, 16))

        today_header = tk.Frame(today_box, bg="#13171f")
        today_header.pack(fill="x", padx=16, pady=(10, 6))

        tk.Label(
            today_header,
            text="📅  СОСТОЯНИЕ ДНЯ И СВОДКА «СЕГОДНЯ»",
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
        total_notes = len(self.household.notes) if self.household and hasattr(self.household, "notes") else 0

        info_line1 = f"• Активных задач: {pending_tasks}    • Ближайших событий / напоминаний: {due_reminders}"
        info_line2 = f"• Именованных списков дел: {total_lists}    • Сохранённых заметок: {total_notes}"
        info_line3 = "• Автономное ядро: Sub-Agents (Image, Presentation, Document, Research, Coding, File, Planner)"

        tk.Label(
            today_box,
            text=f"{info_line1}\n{info_line2}\n{info_line3}",
            font=("Segoe UI", 9),
            fg=self.FG_MAIN,
            bg="#13171f",
            justify="left",
            lineheight=1.3 if hasattr(tk.Label, "lineheight") else None
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # Правая часть верхнего ряда: NEURAL CORE
        core_box = tk.Frame(top_row, bg=self.BG_CARD, bd=1, relief="solid", width=250)
        core_box.pack(side="right", fill="y")
        core_box.pack_propagate(False)

        tk.Label(
            core_box,
            text="NEURAL CORE 3D",
            font=("Segoe UI", 8, "bold"),
            fg=self.FG_MUTED,
            bg=self.BG_CARD
        ).pack(pady=(10, 2))

        self.neural_core = NeuralCore(core_box, size=160, bg=self.BG_CARD)
        self.neural_core.pack(pady=2)

        if self.shell:
            self.shell.neural_core = self.neural_core
            cur_state = getattr(self.shell, "current_state", "idle")
            self.neural_core.set_state(cur_state)

        # -------------------------------------------------------------
        # 2. Средний ряд: 3 интерактивные карточки (Задачи / События / Списки)
        # -------------------------------------------------------------
        mid_row = tk.Frame(self, bg=self.BG_MAIN)
        mid_row.pack(fill="x", pady=(0, 16))

        # Карточка 1: Задачи
        card_t = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_t.pack(side="left", fill="both", expand=True, padx=(0, 12))

        tk.Label(
            card_t,
            text="✓  ЗАДАЧИ",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(12, 6))

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
        btn_all_t.pack(anchor="w", padx=16, pady=(8, 10))

        # Карточка 2: Ближайшие события и напоминания
        card_r = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_r.pack(side="left", fill="both", expand=True, padx=(0, 12))

        tk.Label(
            card_r,
            text="🔔  БЛИЖАЙШИЕ СОБЫТИЯ",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_PURPLE,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(12, 6))

        rems_dict = self.household.list_reminders() if self.household and hasattr(self.household, "list_reminders") else {}
        rems = rems_dict.get("reminders", []) if isinstance(rems_dict, dict) else []
        due_dict = self.household.check_due_reminders() if self.household and hasattr(self.household, "check_due_reminders") else {}
        due_ids = {r.get("id") for r in due_dict.get("due_reminders", [])} if isinstance(due_dict, dict) else set()

        if not rems:
            tk.Label(
                card_r,
                text="Ближайших событий нет.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=16, pady=4)
        else:
            for r in rems[:3]:
                is_due = r.get("id") in due_ids
                r_row = tk.Frame(card_r, bg=self.BG_CARD)
                r_row.pack(fill="x", padx=16, pady=2)
                icon = "⏰" if not is_due else "🔔"
                tag_fg = self.ACCENT_RED if is_due else self.ACCENT_PURPLE
                tk.Label(r_row, text=icon, font=("Segoe UI", 9), fg=tag_fg, bg=self.BG_CARD).pack(side="left")
                t_snip = r["text"][:22] + ("..." if len(r["text"]) > 22 else "")
                tk.Label(r_row, text=f" {t_snip}", font=("Segoe UI", 9), fg=self.FG_MAIN, bg=self.BG_CARD).pack(side="left")
                time_badge = "Наступило!" if is_due else r.get("remind_at", "")[:10]
                tk.Label(r_row, text=f"({time_badge})", font=("Segoe UI", 8), fg=tag_fg if is_due else self.FG_DIM, bg=self.BG_CARD).pack(side="right")

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
        btn_all_r.pack(anchor="w", padx=16, pady=(8, 10))

        # Карточка 3: Списки
        card_l = tk.Frame(mid_row, bg=self.BG_CARD, bd=1, relief="solid")
        card_l.pack(side="left", fill="both", expand=True)

        tk.Label(
            card_l,
            text="📋  СПИСКИ",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_GREEN,
            bg=self.BG_CARD
        ).pack(anchor="w", padx=16, pady=(12, 6))

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
        btn_all_l.pack(anchor="w", padx=16, pady=(8, 10))

        # -------------------------------------------------------------
        # 3. Нижний ряд: Активность Акакия и рабочие результаты + Заметки
        # -------------------------------------------------------------
        bot_row = tk.Frame(self, bg=self.BG_MAIN)
        bot_row.pack(fill="both", expand=True)

        # Левая часть (60%): Активность и рабочие результаты Акакия
        act_box = tk.Frame(bot_row, bg=self.BG_CARD, bd=1, relief="solid")
        act_box.pack(side="left", fill="both", expand=True, padx=(0, 12))

        act_header = tk.Frame(act_box, bg=self.BG_CARD)
        act_header.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            act_header,
            text="⚡  АКТИВНОСТЬ И РАБОЧИЕ РЕЗУЛЬТАТЫ",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_AMBER,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_to_chat = tk.Button(
            act_header,
            text="Открыть Чат →",
            font=("Segoe UI", 8, "bold"),
            fg=self.ACCENT_BLUE,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("chat")
        )
        btn_to_chat.pack(side="right")

        # Получаем последние структурированные рабочие результаты из Shell
        recent_results = []
        if self.shell and hasattr(self.shell, "recent_work_results"):
            raw_w = getattr(self.shell, "recent_work_results")
            if isinstance(raw_w, list):
                recent_results = list(raw_w)[-3:]

        # Если явных результатов еще нет, берем недавние системные логи
        if not recent_results and self.shell and hasattr(self.shell, "log_messages"):
            raw_logs = getattr(self.shell, "log_messages")
            if isinstance(raw_logs, list) and raw_logs:
                recent_results = [
                    {
                        "type": p.lower(),
                        "title": f"Событие [{p}]",
                        "message": txt,
                        "time": tm,
                        "success": p not in ("ERR", "FAIL"),
                        "created_files": []
                    }
                    for p, txt, tm in raw_logs[-3:]
                ]

        if not recent_results:
            tk.Label(
                act_box,
                text="Акакий готов к работе. Начните диалог, запустите команду в нижней строке ввода или используйте голосовой ввод.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD,
                justify="left",
                wraplength=480
            ).pack(anchor="w", padx=16, pady=12)
        else:
            for item in reversed(recent_results):
                row = tk.Frame(act_box, bg="#13171f", bd=1, relief="solid")
                row.pack(fill="x", padx=16, pady=3)

                top_l = tk.Frame(row, bg="#13171f")
                top_l.pack(fill="x", padx=10, pady=(6, 2))

                is_ok = item.get("success", True)
                b_color = self.ACCENT_GREEN if is_ok else self.ACCENT_RED
                badge_type = str(item.get("type", "ДЕЙСТВИЕ")).upper()
                tk.Label(
                    top_l,
                    text=f"[{badge_type}]",
                    font=("Consolas", 8, "bold"),
                    fg=b_color,
                    bg="#1a222e",
                    padx=4,
                    pady=1
                ).pack(side="left")

                title_txt = str(item.get("title", "") or item.get("query", ""))
                if len(title_txt) > 42:
                    title_txt = title_txt[:39] + "..."
                tk.Label(
                    top_l,
                    text=f"  {title_txt}",
                    font=("Segoe UI", 9, "bold"),
                    fg=self.FG_WHITE,
                    bg="#13171f"
                ).pack(side="left")

                tk.Label(
                    top_l,
                    text=str(item.get("time", "")),
                    font=("Consolas", 8),
                    fg=self.FG_DIM,
                    bg="#13171f"
                ).pack(side="right")

                # Текст сообщения
                msg_snip = str(item.get("message", ""))
                if msg_snip:
                    if len(msg_snip) > 110:
                        msg_snip = msg_snip[:107] + "..."
                    tk.Label(
                        row,
                        text=msg_snip,
                        font=("Segoe UI", 8),
                        fg=self.FG_MAIN,
                        bg="#13171f",
                        justify="left",
                        anchor="w"
                    ).pack(fill="x", padx=10, pady=(0, 4))

                # Блок артефактов при наличии
                c_files = item.get("created_files") or []
                if c_files:
                    art_row = tk.Frame(row, bg="#13171f")
                    art_row.pack(fill="x", padx=10, pady=(0, 6))
                    tk.Label(
                        art_row,
                        text="Артефакты: ",
                        font=("Segoe UI", 8, "bold"),
                        fg=self.ACCENT_CYAN,
                        bg="#13171f"
                    ).pack(side="left")
                    for fp in c_files[:2]:
                        fname = Path(str(fp)).name
                        tk.Label(
                            art_row,
                            text=f"📁 {fname}",
                            font=("Consolas", 8),
                            fg=self.ACCENT_CYAN,
                            bg="#162536",
                            padx=4,
                            pady=1
                        ).pack(side="left", padx=2)

        # Правая часть (40%): Последние заметки
        notes_box = tk.Frame(bot_row, bg=self.BG_CARD, bd=1, relief="solid", width=360)
        notes_box.pack(side="right", fill="both", expand=True)

        n_hdr = tk.Frame(notes_box, bg=self.BG_CARD)
        n_hdr.pack(fill="x", padx=16, pady=(12, 6))

        tk.Label(
            n_hdr,
            text="📝  ПОСЛЕДНИЕ ЗАМЕТКИ",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD
        ).pack(side="left")

        btn_all_n = tk.Button(
            n_hdr,
            text="Все заметки →",
            font=("Segoe UI", 8, "bold"),
            fg=self.ACCENT_CYAN,
            bg=self.BG_CARD,
            bd=0,
            cursor="hand2",
            command=lambda: self.switch_section("notes")
        )
        btn_all_n.pack(side="right")

        notes = self.household.notes[-2:] if self.household and self.household.notes else []
        if not notes:
            tk.Label(
                notes_box,
                text="Заметок пока нет. Создайте первую заметку через раздел Заметки или нижнюю команду.",
                font=("Segoe UI", 9),
                fg=self.FG_MUTED,
                bg=self.BG_CARD,
                wraplength=300,
                justify="left"
            ).pack(anchor="w", padx=16, pady=12)
        else:
            for n in reversed(notes):
                item_card = tk.Frame(notes_box, bg="#13171f", bd=1, relief="solid")
                item_card.pack(fill="x", padx=14, pady=3)
                tk.Label(
                    item_card,
                    text=n.get("title", ""),
                    font=("Segoe UI", 9, "bold"),
                    fg=self.FG_WHITE,
                    bg="#13171f"
                ).pack(anchor="w", padx=10, pady=(6, 2))
                c_prev = n.get("content", "")[:70] + ("..." if len(n.get("content", "")) > 70 else "")
                tk.Label(
                    item_card,
                    text=c_prev,
                    font=("Segoe UI", 8),
                    fg=self.FG_MUTED,
                    bg="#13171f",
                    justify="left",
                    wraplength=300
                ).pack(anchor="w", padx=10, pady=(0, 6))

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
